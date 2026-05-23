"""
Radio cog - completely separate from on-demand playback.

Radio is *continuous* - no queue, no skip-to-position, no loop. So we
keep it in its own cog with its own commands. Playing a station stops
whatever queued music was playing and starts the stream; stopping the
station disconnects the bot.

Stations come from radio-browser.info, a community database of legally-
licensed internet stations.

Commands:
  /radio search <name>
  /radio top
  /radio tag <tag>
  /radio play <uuid>
  /radio stop
"""

from __future__ import annotations

import logging

import aiohttp
import discord
import wavelink
from discord import app_commands
from discord.ext import commands

from cogs.music import Music
from utils.radio_browser import RadioBrowserClient, Station

log = logging.getLogger("songs.ai.radio")


class Radio(commands.Cog):
    radio_group = app_commands.Group(
        name="radio",
        description="Play a licensed internet radio station.",
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._http: aiohttp.ClientSession | None = None
        self._client: RadioBrowserClient | None = None

    async def cog_load(self) -> None:
        self._http = aiohttp.ClientSession()
        self._client = RadioBrowserClient(self._http)

    async def cog_unload(self) -> None:
        if self._http:
            await self._http.close()

    def _music(self) -> Music | None:
        return self.bot.get_cog("Music")  # type: ignore[return-value]

    # ----------------------------------------------- /radio search
    @radio_group.command(name="search", description="Search radio stations by name.")
    async def search(self, interaction: discord.Interaction, name: str) -> None:
        await interaction.response.defer()
        assert self._client is not None
        stations = await self._client.search(name=name, limit=10)
        await self._render_list(interaction, stations, title=f"Stations: {name}")

    @radio_group.command(name="tag", description="Browse stations by tag (jazz, classical, news, lofi, …).")
    async def tag(self, interaction: discord.Interaction, tag: str) -> None:
        await interaction.response.defer()
        assert self._client is not None
        stations = await self._client.search(tag=tag, limit=10)
        await self._render_list(interaction, stations, title=f"Tag: {tag}")

    @radio_group.command(name="top", description="Most-clicked stations right now.")
    async def top(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        assert self._client is not None
        stations = await self._client.top(limit=10)
        await self._render_list(interaction, stations, title="Top stations")

    async def _render_list(
        self,
        interaction: discord.Interaction,
        stations: list[Station],
        *,
        title: str,
    ) -> None:
        if not stations:
            await interaction.followup.send("No stations found.", ephemeral=True)
            return
        embed = discord.Embed(title=title, color=discord.Color.dark_teal())
        lines = []
        for i, s in enumerate(stations, 1):
            kbps = f"{s.bitrate}kbps" if s.bitrate else "?"
            lines.append(
                f"`{i:>2}.` **{s.name[:60]}** — {s.country or '?'} "
                f"[{kbps}] (`{s.uuid}`)"
            )
        embed.description = "\n".join(lines)
        embed.set_footer(text="Copy a UUID and use `/radio play <uuid>` to tune in.")
        await interaction.followup.send(embed=embed)

    # ----------------------------------------------- /radio play
    @radio_group.command(name="play", description="Tune in to a station by UUID.")
    async def play(self, interaction: discord.Interaction, uuid: str) -> None:
        await interaction.response.defer()
        music = self._music()
        if music is None:
            await interaction.followup.send("Music cog not loaded.", ephemeral=True)
            return
        assert self._client is not None
        station = await self._client.by_uuid(uuid)
        if station is None or not station.url:
            await interaction.followup.send("Station not found or no stream URL.", ephemeral=True)
            return
        player = await music.ensure_voice(interaction)
        if player is None:
            return
        # Wipe the queue - radio replaces on-demand playback entirely.
        music.queues.get(interaction.guild.id).clear()  # type: ignore[union-attr]
        if player.playing:
            await player.stop()
        # Stream the radio URL directly via Lavalink's HTTP source.
        results = await wavelink.Playable.search(station.url)
        if not results:
            await interaction.followup.send(
                "Lavalink couldn't open that stream URL. "
                "Try a different station.", ephemeral=True
            )
            return
        await player.play(results[0])
        embed = discord.Embed(
            title=f"📻 {station.name}",
            description=f"{station.country} • {station.tags}",
            color=discord.Color.dark_teal(),
            url=station.homepage or None,
        )
        if station.favicon:
            embed.set_thumbnail(url=station.favicon)
        await interaction.followup.send(embed=embed)

    # ----------------------------------------------- /radio stop
    @radio_group.command(name="stop", description="Stop the radio and disconnect.")
    async def stop(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Server-only.", ephemeral=True)
            return
        player: wavelink.Player | None = interaction.guild.voice_client  # type: ignore[assignment]
        if player is None:
            await interaction.response.send_message("Not connected.", ephemeral=True)
            return
        await player.disconnect()
        await interaction.response.send_message("Off the air.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Radio(bot))
