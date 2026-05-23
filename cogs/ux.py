"""
UX cog - now-playing, lyrics (LRCLIB), skip voting.

  /nowplaying  - rich embed with progress bar
  /lyrics      - look up lyrics for the current track (LRCLIB - openly licensed)
  /skip        - vote-based skip with SKIP_VOTE_RATIO threshold
  /forceskip   - admin-only instant skip
"""

from __future__ import annotations

import logging
import os

import aiohttp
import discord
import wavelink
from discord import app_commands
from discord.ext import commands

from cogs.music import Music
from utils.lrclib import fetch_lyrics

log = logging.getLogger("songs.ai.ux")


def _progress_bar(position_ms: int, total_ms: int, width: int = 20) -> str:
    if total_ms <= 0:
        return "─" * width
    pct = min(1.0, position_ms / total_ms)
    filled = int(width * pct)
    return "▬" * filled + "🔘" + "─" * (width - filled - 1)


def _fmt_ms(ms: int) -> str:
    s = ms // 1000
    return f"{s // 60}:{s % 60:02d}"


class UX(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.skip_vote_ratio = float(os.getenv("SKIP_VOTE_RATIO", "0.5"))
        self._http: aiohttp.ClientSession | None = None

    async def cog_load(self) -> None:
        self._http = aiohttp.ClientSession()

    async def cog_unload(self) -> None:
        if self._http:
            await self._http.close()

    def _music(self) -> Music | None:
        return self.bot.get_cog("Music")  # type: ignore[return-value]

    # -------------------------------------------------------- /nowplaying
    @app_commands.command(name="nowplaying", description="Show the current track.")
    async def nowplaying(self, interaction: discord.Interaction) -> None:
        player: wavelink.Player | None = (
            interaction.guild.voice_client if interaction.guild else None  # type: ignore[assignment]
        )
        if not player or not player.current:
            await interaction.response.send_message("Nothing playing.", ephemeral=True)
            return
        t = player.current
        embed = discord.Embed(
            title=t.title,
            url=t.uri or discord.utils.MISSING,
            description=f"by **{t.author}**" if t.author else None,
            color=discord.Color.green(),
        )
        if t.artwork:
            embed.set_thumbnail(url=t.artwork)
        bar = _progress_bar(player.position, t.length)
        embed.add_field(
            name="Progress",
            value=f"`{_fmt_ms(player.position)}` {bar} `{_fmt_ms(t.length)}`",
            inline=False,
        )
        await interaction.response.send_message(embed=embed)

    # -------------------------------------------------------- /lyrics
    @app_commands.command(
        name="lyrics", description="Fetch openly-licensed lyrics for the current track."
    )
    async def lyrics(self, interaction: discord.Interaction) -> None:
        player: wavelink.Player | None = (
            interaction.guild.voice_client if interaction.guild else None  # type: ignore[assignment]
        )
        if not player or not player.current:
            await interaction.response.send_message("Nothing playing.", ephemeral=True)
            return
        await interaction.response.defer()
        track = player.current
        assert self._http is not None
        text = await fetch_lyrics(
            self._http,
            artist=track.author or "",
            title=track.title or "",
            duration_s=int((track.length or 0) / 1000) or None,
        )
        if not text:
            await interaction.followup.send(
                "No lyrics in LRCLIB for this track. "
                "(Consider contributing them at https://lrclib.net/.)",
                ephemeral=True,
            )
            return
        if len(text) > 4000:
            text = text[:4000].rsplit("\n", 1)[0] + "\n\n*(truncated)*"
        embed = discord.Embed(
            title=f"{track.title} — {track.author}",
            description=text,
            color=discord.Color.purple(),
        )
        embed.set_footer(text="Lyrics: LRCLIB (CC0 community database)")
        await interaction.followup.send(embed=embed)

    # -------------------------------------------------------- /skip
    @app_commands.command(name="skip", description="Vote to skip the current track.")
    async def skip(self, interaction: discord.Interaction) -> None:
        music = self._music()
        player: wavelink.Player | None = (
            interaction.guild.voice_client if interaction.guild else None  # type: ignore[assignment]
        )
        if not music or not player or not player.playing:
            await interaction.response.send_message("Nothing playing.", ephemeral=True)
            return
        state = music.queues.get(interaction.guild.id)  # type: ignore[union-attr]
        voice_channel = player.channel
        listeners = [m for m in voice_channel.members if not m.bot] if voice_channel else []
        if not listeners:
            await player.stop()
            await interaction.response.send_message("Skipped.")
            return
        state.skip_votes.add(interaction.user.id)
        needed = max(1, int(len(listeners) * self.skip_vote_ratio))
        if len(state.skip_votes) >= needed:
            await player.stop()
            await interaction.response.send_message(
                f"Skipped ({len(state.skip_votes)}/{needed} votes)."
            )
        else:
            await interaction.response.send_message(
                f"Skip vote: **{len(state.skip_votes)}/{needed}**."
            )

    # -------------------------------------------------------- /forceskip
    @app_commands.command(name="forceskip", description="Admin: skip immediately.")
    @app_commands.default_permissions(manage_guild=True)
    async def forceskip(self, interaction: discord.Interaction) -> None:
        player: wavelink.Player | None = (
            interaction.guild.voice_client if interaction.guild else None  # type: ignore[assignment]
        )
        if not player or not player.playing:
            await interaction.response.send_message("Nothing playing.", ephemeral=True)
            return
        await player.stop()
        await interaction.response.send_message("Force-skipped.")

    # -------------------------------------------------------- /credits
    @app_commands.command(name="credits", description="Show music sources and licensing info.")
    async def credits(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="songs.ai — credits & licensing",
            description=(
                "All music played by this bot comes from legally clean sources:\n\n"
                "• **Jamendo** — Creative Commons licensed indie music. "
                "Each track shows its specific CC license in the queue.\n"
                "• **Internet Archive** — Live Music Archive (artist-permitted concerts) "
                "and Open Source Audio.\n"
                "• **radio-browser.info** — community database of properly-licensed "
                "internet radio stations.\n"
                "• **Self-hosted libraries** — music you legally own, served via Navidrome/Subsonic.\n\n"
                "Metadata sources: **Last.fm** (similar-artist data), "
                "**LRCLIB** (CC0 community lyrics)."
            ),
            color=discord.Color.gold(),
        )
        embed.set_footer(text="Source: https://github.com/yourname/songs.ai")
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(UX(bot))
