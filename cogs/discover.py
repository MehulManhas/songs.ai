"""
Discover cog - taste-based recommendations using legal sources only.

How it works (no Spotify, no YouTube):
  1. Take a seed - either the currently-playing track's artist, or a
     user-supplied artist name.
  2. Ask Last.fm for similar artists (Last.fm is a metadata API; we
     are not streaming from it, so its ToS isn't an issue here).
  3. For each similar artist, search Jamendo for their tracks. Jamendo
     hosts mostly indie/CC artists so we'll find some overlap but not
     all mainstream artists - that's expected (and intentional).
  4. Queue what we find.

Commands:
  /discover similar [artist]   Queue tracks by artists similar to the seed
  /discover mood <tag>         Queue Jamendo tracks for a mood/genre
"""

from __future__ import annotations

import asyncio
import logging
import random

import aiohttp
import discord
import wavelink
from discord import app_commands
from discord.ext import commands

from cogs.music import Music
from utils.jamendo_client import JamendoClient
from utils.lastfm_client import LastFmClient

log = logging.getLogger("songs.ai.discover")


class Discover(commands.Cog):
    discover_group = app_commands.Group(
        name="discover", description="Find new music from legal sources."
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._http: aiohttp.ClientSession | None = None
        self._lastfm: LastFmClient | None = None
        self._jamendo: JamendoClient | None = None

    async def cog_load(self) -> None:
        self._http = aiohttp.ClientSession()
        self._lastfm = LastFmClient(self._http)
        self._jamendo = JamendoClient(self._http)

    async def cog_unload(self) -> None:
        if self._http:
            await self._http.close()

    def _music(self) -> Music | None:
        return self.bot.get_cog("Music")  # type: ignore[return-value]

    # -------------------------------------------------- /discover similar
    @discover_group.command(
        name="similar",
        description="Queue Jamendo tracks by artists similar to the seed.",
    )
    @app_commands.describe(
        artist="Seed artist (omit to use the currently-playing track)",
        count="How many tracks to queue (3-20)",
    )
    async def similar(
        self,
        interaction: discord.Interaction,
        artist: str | None = None,
        count: app_commands.Range[int, 3, 20] = 10,
    ) -> None:
        await interaction.response.defer()
        music = self._music()
        if music is None:
            await interaction.followup.send("Music cog not loaded.", ephemeral=True)
            return

        # Figure out the seed artist.
        seed = artist
        if seed is None:
            player: wavelink.Player | None = (
                interaction.guild.voice_client if interaction.guild else None  # type: ignore[assignment]
            )
            if player and player.current:
                seed = player.current.author
        if not seed:
            await interaction.followup.send(
                "Pass an artist name, or play something first so I can use its artist.",
                ephemeral=True,
            )
            return

        assert self._lastfm is not None and self._jamendo is not None
        similar_names = await self._lastfm.similar_artists(seed, limit=25)
        if not similar_names:
            await interaction.followup.send(
                f"Last.fm doesn't know any artists similar to **{seed}**.",
                ephemeral=True,
            )
            return
        random.shuffle(similar_names)

        player = await music.ensure_voice(interaction)
        if player is None:
            return

        queued = 0
        for name in similar_names:
            if queued >= count:
                break
            try:
                tracks = await self._jamendo.tracks_by_artist(name, limit=1)
            except Exception:
                log.exception("Jamendo per-artist search failed")
                continue
            if not tracks:
                continue
            t = tracks[0]
            if await music.queue_url(
                player, interaction.guild.id,  # type: ignore[union-attr]
                interaction.user.id, t.audio, source_url=t.share_url,
            ):
                queued += 1
            # Be polite to Jamendo's free tier.
            await asyncio.sleep(0.1)

        if queued == 0:
            await interaction.followup.send(
                f"None of the artists similar to **{seed}** had tracks on Jamendo. "
                "(This is the trade-off for using only CC sources — try `/jamendo tag` "
                "for genre-based discovery instead.)",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            f"Queued **{queued}** discovery tracks based on **{seed}**."
        )

    # -------------------------------------------------- /discover mood
    @discover_group.command(name="mood", description="Queue Jamendo tracks for a mood/genre tag.")
    @app_commands.describe(tag="e.g. chill, focus, upbeat, ambient, jazz, electronic")
    async def mood(
        self,
        interaction: discord.Interaction,
        tag: str,
        count: app_commands.Range[int, 3, 20] = 10,
    ) -> None:
        await interaction.response.defer()
        music = self._music()
        if music is None:
            await interaction.followup.send("Music cog not loaded.", ephemeral=True)
            return
        assert self._jamendo is not None
        tracks = await self._jamendo.tracks_by_tag(tag, limit=count)
        if not tracks:
            await interaction.followup.send(
                f"No Jamendo tracks for tag `{tag}`. Try another.", ephemeral=True
            )
            return
        player = await music.ensure_voice(interaction)
        if player is None:
            return
        queued = 0
        for t in tracks:
            if await music.queue_url(
                player, interaction.guild.id,  # type: ignore[union-attr]
                interaction.user.id, t.audio, source_url=t.share_url,
            ):
                queued += 1
        await interaction.followup.send(
            f"Queued **{queued}** `{tag}` tracks."
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Discover(bot))
