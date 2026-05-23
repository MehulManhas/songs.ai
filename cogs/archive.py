"""
Archive cog - Internet Archive integration.

Two collections we surface:
  - etree            : Live Music Archive (artist-permitted concerts)
  - opensource_audio : indie / CC / public-domain uploads

Commands:
  /archive search <query>     Show matching items (concerts/albums)
  /archive play <item_id>     Queue every track from an item
  /archive sample             Queue a random recent upload from etree
"""

from __future__ import annotations

import logging
import random

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from cogs.music import Music
from utils.archive_client import ArchiveClient, ArchiveItem

log = logging.getLogger("songs.ai.archive")


class Archive(commands.Cog):
    archive_group = app_commands.Group(
        name="archive", description="Play from the Internet Archive."
    )

    COLLECTION_CHOICES = [
        app_commands.Choice(name="Live Music Archive (etree)", value="etree"),
        app_commands.Choice(name="Open Source Audio", value="opensource_audio"),
        app_commands.Choice(name="Audio / Music", value="audio_music"),
        app_commands.Choice(name="Netlabels", value="netlabels"),
    ]

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._http: aiohttp.ClientSession | None = None
        self._client: ArchiveClient | None = None

    async def cog_load(self) -> None:
        self._http = aiohttp.ClientSession()
        self._client = ArchiveClient(self._http)

    async def cog_unload(self) -> None:
        if self._http:
            await self._http.close()

    def _music(self) -> Music | None:
        return self.bot.get_cog("Music")  # type: ignore[return-value]

    # ----------------------------------------------- /archive search
    @archive_group.command(name="search", description="Search the Internet Archive.")
    @app_commands.choices(collection=COLLECTION_CHOICES)
    async def search(
        self, interaction: discord.Interaction, query: str,
        collection: app_commands.Choice[str] | None = None,
    ) -> None:
        await interaction.response.defer()
        assert self._client is not None
        col = collection.value if collection else "etree"
        try:
            items = await self._client.search_items(query, collection=col, limit=10)
        except Exception:
            log.exception("Archive search failed")
            await interaction.followup.send(
                "Internet Archive search failed.", ephemeral=True
            )
            return
        if not items:
            await interaction.followup.send("No results.", ephemeral=True)
            return
        embed = discord.Embed(
            title=f"Archive: {query} ({col})",
            description="\n".join(
                f"`{i+1}.` **{it.title[:80]}** — {it.creator[:60]} "
                f"(`{it.identifier}`)"
                for i, it in enumerate(items)
            ),
            color=discord.Color.dark_gold(),
        )
        embed.set_footer(
            text="Copy an identifier and use `/archive play <identifier>` to queue it."
        )
        await interaction.followup.send(embed=embed)

    # ----------------------------------------------- /archive play
    @archive_group.command(name="play", description="Queue every track from an Archive item.")
    @app_commands.describe(identifier="The item identifier (e.g. gd1977-05-08.sbd)")
    async def play(self, interaction: discord.Interaction, identifier: str) -> None:
        await interaction.response.defer()
        music = self._music()
        if music is None:
            await interaction.followup.send("Music cog not loaded.", ephemeral=True)
            return
        assert self._client is not None
        try:
            tracks = await self._client.item_tracks(identifier)
        except Exception:
            log.exception("Archive item fetch failed")
            await interaction.followup.send("Couldn't fetch that item.", ephemeral=True)
            return
        if not tracks:
            await interaction.followup.send(
                "That item has no playable audio.", ephemeral=True
            )
            return
        player = await music.ensure_voice(interaction)
        if player is None:
            return
        queued = 0
        for t in tracks:
            if await music.queue_url(
                player, interaction.guild.id,  # type: ignore[union-attr]
                interaction.user.id, t.stream_url, source_url=t.page_url,
            ):
                queued += 1
        await interaction.followup.send(
            f"Queued **{queued}** tracks from `{identifier}`."
        )

    # ----------------------------------------------- /archive sample
    @archive_group.command(name="sample", description="Queue a random Live Music Archive item.")
    async def sample(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        music = self._music()
        if music is None:
            await interaction.followup.send("Music cog not loaded.", ephemeral=True)
            return
        assert self._client is not None
        # Use a single-letter wildcard query to get a broad sampling.
        items = await self._client.search_items(
            random.choice(["a", "e", "i", "o", "u"]), collection="etree", limit=50
        )
        if not items:
            await interaction.followup.send("Archive returned nothing.", ephemeral=True)
            return
        pick: ArchiveItem = random.choice(items)
        tracks = await self._client.item_tracks(pick.identifier)
        if not tracks:
            await interaction.followup.send(
                f"`{pick.identifier}` had no playable audio. Try again.",
                ephemeral=True,
            )
            return
        player = await music.ensure_voice(interaction)
        if player is None:
            return
        queued = 0
        for t in tracks:
            if await music.queue_url(
                player, interaction.guild.id,  # type: ignore[union-attr]
                interaction.user.id, t.stream_url, source_url=t.page_url,
            ):
                queued += 1
        await interaction.followup.send(
            f"Random sample: **{pick.title}** — {pick.creator} "
            f"({queued} tracks queued)."
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Archive(bot))
