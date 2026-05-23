"""
Music cog - the playback engine + Jamendo (default /play source).

This cog owns:
  - The wavelink player lifecycle (join/leave voice, play next track)
  - The queue state (utils.queue.QueueManager)
  - The /play, /pause, /resume, /stop, /queue, /loop, /volume commands
  - A track-end handler that advances the queue and respects loop mode

Other cogs (library, archive, radio, discover) push tracks INTO this
cog's queue via the public `queue_url` helper. That keeps the playback
engine in one place and means every source benefits from queue/loop/
skip-vote behavior for free.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import aiohttp
import discord
import wavelink
from discord import app_commands
from discord.ext import commands

from utils.jamendo_client import JamendoClient, JamendoTrack
from utils.queue import LoopMode, QueueManager, QueuedTrack

log = logging.getLogger("songs.ai.music")


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.queues = QueueManager()
        self.default_volume = int(os.getenv("DEFAULT_VOLUME", "60"))
        self._http: aiohttp.ClientSession | None = None
        self._jamendo: JamendoClient | None = None

    async def cog_load(self) -> None:
        self._http = aiohttp.ClientSession()
        self._jamendo = JamendoClient(self._http)

    async def cog_unload(self) -> None:
        if self._http:
            await self._http.close()

    # ----------------------------------------------------------- public API
    # Other cogs use these helpers so they don't have to know wavelink.

    async def ensure_voice(
        self, interaction: discord.Interaction
    ) -> Optional[wavelink.Player]:
        """Connect the bot to the caller's voice channel."""
        if interaction.guild is None or not isinstance(
            interaction.user, discord.Member
        ):
            await self._respond(
                interaction, "This command only works inside a server.", ephemeral=True
            )
            return None

        voice_state = interaction.user.voice
        if voice_state is None or voice_state.channel is None:
            await self._respond(
                interaction, "Join a voice channel first.", ephemeral=True
            )
            return None

        player: wavelink.Player | None = interaction.guild.voice_client  # type: ignore[assignment]
        if player is None:
            player = await voice_state.channel.connect(cls=wavelink.Player)
            await player.set_volume(self.default_volume)
        elif player.channel != voice_state.channel:
            await self._respond(
                interaction,
                "I'm already playing in another voice channel.",
                ephemeral=True,
            )
            return None

        state = self.queues.get(interaction.guild.id)
        state.text_channel_id = interaction.channel_id
        return player

    async def queue_url(
        self,
        player: wavelink.Player,
        guild_id: int,
        requester_id: int,
        stream_url: str,
        source_url: str | None = None,
    ) -> wavelink.Playable | None:
        """
        Add a direct audio URL to the queue and start playback if idle.

        Returns the resolved Playable so callers can react (e.g. for embeds).
        """
        results = await wavelink.Playable.search(stream_url)
        if not results:
            return None
        # `Playable.search` on a direct URL returns a list of one.
        playable = results[0] if isinstance(results, list) else results
        state = self.queues.get(guild_id)
        state.push(
            QueuedTrack(
                track=playable,
                requester_id=requester_id,
                source_url=source_url,
            )
        )
        if not player.playing:
            first = state.pop()
            if first:
                await player.play(first.track, volume=self.default_volume)
        return playable

    # ------------------------------------------------------------------ /play
    @app_commands.command(
        name="play",
        description="Search Jamendo (Creative Commons music) and queue a track.",
    )
    @app_commands.describe(query="Song title, artist, or keyword")
    async def play(self, interaction: discord.Interaction, query: str) -> None:
        await interaction.response.defer()
        player = await self.ensure_voice(interaction)
        if player is None:
            return
        assert self._jamendo is not None

        try:
            tracks = await self._jamendo.search_tracks(query, limit=1)
        except Exception:
            log.exception("Jamendo search failed")
            await interaction.followup.send(
                "Couldn't reach Jamendo right now.", ephemeral=True
            )
            return

        if not tracks:
            await interaction.followup.send(
                "No Jamendo result for that. Try `/jamendo search` for a wider "
                "browse, or `/library` if your server has a personal library set up.",
                ephemeral=True,
            )
            return

        track = tracks[0]
        playable = await self.queue_url(
            player,
            interaction.guild.id,  # type: ignore[union-attr]
            interaction.user.id,
            track.audio,
            source_url=track.share_url,
        )
        if playable is None:
            await interaction.followup.send(
                "Couldn't resolve that stream URL.", ephemeral=True
            )
            return
        await interaction.followup.send(
            f"Queued **{track.name}** — {track.artist_name} "
            f"({_license_name(track.license_url)})"
        )

    # ----------------------------------------------------- /jamendo search
    jamendo_group = app_commands.Group(
        name="jamendo", description="Browse Jamendo Creative Commons music."
    )

    @jamendo_group.command(name="search", description="Search Jamendo and pick a result.")
    async def jamendo_search(self, interaction: discord.Interaction, query: str) -> None:
        await interaction.response.defer()
        assert self._jamendo is not None
        tracks = await self._jamendo.search_tracks(query, limit=5)
        if not tracks:
            await interaction.followup.send("No results.", ephemeral=True)
            return
        view = JamendoPickerView(self, tracks)
        embed = discord.Embed(
            title=f"Jamendo results: {query}",
            description="\n".join(
                f"`{i+1}.` **{t.name}** — {t.artist_name}"
                for i, t in enumerate(tracks)
            ),
            color=discord.Color.green(),
        )
        await interaction.followup.send(embed=embed, view=view)

    @jamendo_group.command(name="popular", description="Queue this week's most-played CC tracks.")
    @app_commands.describe(count="How many tracks (5-20)")
    async def jamendo_popular(
        self, interaction: discord.Interaction,
        count: app_commands.Range[int, 5, 20] = 10,
    ) -> None:
        await interaction.response.defer()
        player = await self.ensure_voice(interaction)
        if player is None:
            return
        assert self._jamendo is not None
        tracks = await self._jamendo.popular(limit=count)
        queued = 0
        for t in tracks:
            if await self.queue_url(
                player, interaction.guild.id,  # type: ignore[union-attr]
                interaction.user.id, t.audio, source_url=t.share_url,
            ):
                queued += 1
        await interaction.followup.send(f"Queued **{queued}** popular Jamendo tracks.")

    @jamendo_group.command(name="tag", description="Queue tracks by mood/genre tag.")
    @app_commands.describe(tag="e.g. chill, rock, electronic, jazz, ambient")
    async def jamendo_tag(
        self, interaction: discord.Interaction, tag: str,
        count: app_commands.Range[int, 5, 20] = 10,
    ) -> None:
        await interaction.response.defer()
        player = await self.ensure_voice(interaction)
        if player is None:
            return
        assert self._jamendo is not None
        tracks = await self._jamendo.tracks_by_tag(tag, limit=count)
        if not tracks:
            await interaction.followup.send("No tracks for that tag.", ephemeral=True)
            return
        queued = 0
        for t in tracks:
            if await self.queue_url(
                player, interaction.guild.id,  # type: ignore[union-attr]
                interaction.user.id, t.audio, source_url=t.share_url,
            ):
                queued += 1
        await interaction.followup.send(f"Queued **{queued}** `{tag}` tracks.")

    # ------------------------------------------------------------ controls
    @app_commands.command(name="pause", description="Pause playback.")
    async def pause(self, interaction: discord.Interaction) -> None:
        player = self._player(interaction)
        if not player or not player.playing:
            await interaction.response.send_message("Nothing playing.", ephemeral=True)
            return
        await player.pause(True)
        await interaction.response.send_message("Paused.")

    @app_commands.command(name="resume", description="Resume playback.")
    async def resume(self, interaction: discord.Interaction) -> None:
        player = self._player(interaction)
        if not player:
            await interaction.response.send_message("Not connected.", ephemeral=True)
            return
        await player.pause(False)
        await interaction.response.send_message("Resumed.")

    @app_commands.command(name="stop", description="Stop and disconnect.")
    async def stop(self, interaction: discord.Interaction) -> None:
        player = self._player(interaction)
        if not player:
            await interaction.response.send_message("Not connected.", ephemeral=True)
            return
        self.queues.get(interaction.guild.id).clear()  # type: ignore[union-attr]
        await player.disconnect()
        await interaction.response.send_message("Stopped.")

    @app_commands.command(name="queue", description="Show the upcoming queue.")
    async def show_queue(self, interaction: discord.Interaction) -> None:
        state = self.queues.get(interaction.guild.id)  # type: ignore[union-attr]
        if not state.queue:
            await interaction.response.send_message("Queue is empty.", ephemeral=True)
            return
        lines = [
            f"`{i:>2}.` **{item.track.title}** — <@{item.requester_id}>"
            for i, item in enumerate(list(state.queue)[:15], 1)
        ]
        extra = (
            f"\n…and {len(state.queue) - 15} more."
            if len(state.queue) > 15 else ""
        )
        embed = discord.Embed(
            title=f"Queue ({len(state.queue)} tracks)",
            description="\n".join(lines) + extra,
            color=discord.Color.blurple(),
        )
        embed.set_footer(text=f"Loop: {state.loop.name.lower()}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="loop", description="Set loop mode.")
    @app_commands.choices(mode=[
        app_commands.Choice(name="off", value=0),
        app_commands.Choice(name="track", value=1),
        app_commands.Choice(name="queue", value=2),
    ])
    async def loop(
        self, interaction: discord.Interaction, mode: app_commands.Choice[int]
    ) -> None:
        state = self.queues.get(interaction.guild.id)  # type: ignore[union-attr]
        state.loop = LoopMode(mode.value)
        await interaction.response.send_message(f"Loop: **{mode.name}**.")

    @app_commands.command(name="volume", description="Set volume (0-150).")
    async def volume(
        self, interaction: discord.Interaction,
        level: app_commands.Range[int, 0, 150],
    ) -> None:
        player = self._player(interaction)
        if not player:
            await interaction.response.send_message("Not connected.", ephemeral=True)
            return
        await player.set_volume(level)
        await interaction.response.send_message(f"Volume: **{level}**.")

    @app_commands.command(name="clear", description="Clear the queue without disconnecting.")
    async def clear_q(self, interaction: discord.Interaction) -> None:
        self.queues.get(interaction.guild.id).clear()  # type: ignore[union-attr]
        await interaction.response.send_message("Queue cleared.")

    # ------------------------------------------------------------ track end
    @commands.Cog.listener()
    async def on_wavelink_track_end(
        self, payload: wavelink.TrackEndEventPayload
    ) -> None:
        guild = payload.player.guild
        if guild is None:
            return
        state = self.queues.get(guild.id)
        state.skip_votes.clear()

        if state.loop == LoopMode.TRACK and payload.track is not None:
            await payload.player.play(payload.track)
            return

        next_item = state.pop()
        if next_item is None:
            if state.loop == LoopMode.QUEUE and state.history:
                for item in list(state.history):
                    state.push(item)
                next_item = state.pop()
            else:
                return

        state.history.append(next_item)
        await payload.player.play(next_item.track)

    # --------------------------------------------------------------- helpers
    @staticmethod
    def _player(
        interaction: discord.Interaction,
    ) -> wavelink.Player | None:
        if interaction.guild is None:
            return None
        return interaction.guild.voice_client  # type: ignore[return-value]

    @staticmethod
    async def _respond(
        interaction: discord.Interaction, content: str, *, ephemeral: bool = False
    ) -> None:
        if interaction.response.is_done():
            await interaction.followup.send(content, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(content, ephemeral=ephemeral)


# ---------------------------------------------------------------------------
# UI components
# ---------------------------------------------------------------------------
def _license_name(license_url: str) -> str:
    """Friendly label for a CC license URL."""
    if "by-nc-nd" in license_url: return "CC BY-NC-ND"
    if "by-nc-sa" in license_url: return "CC BY-NC-SA"
    if "by-nc" in license_url:    return "CC BY-NC"
    if "by-sa" in license_url:    return "CC BY-SA"
    if "by-nd" in license_url:    return "CC BY-ND"
    if "by" in license_url:       return "CC BY"
    if "cc0" in license_url or "publicdomain" in license_url: return "CC0"
    return "CC"


class JamendoPickerView(discord.ui.View):
    def __init__(self, cog: Music, tracks: list[JamendoTrack]) -> None:
        super().__init__(timeout=60)
        self.cog = cog
        self.tracks = tracks
        options = [
            discord.SelectOption(
                label=t.name[:100],
                description=f"{t.artist_name[:100]}",
                value=str(i),
            )
            for i, t in enumerate(tracks)
        ]
        select: discord.ui.Select = discord.ui.Select(
            placeholder="Pick a track…", options=options
        )
        select.callback = self._on_pick
        self.add_item(select)
        self._select = select

    async def _on_pick(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        idx = int(self._select.values[0])
        track = self.tracks[idx]
        player = await self.cog.ensure_voice(interaction)
        if player is None:
            return
        await self.cog.queue_url(
            player,
            interaction.guild.id,  # type: ignore[union-attr]
            interaction.user.id,
            track.audio,
            source_url=track.share_url,
        )
        await interaction.followup.send(
            f"Queued **{track.name}** — {track.artist_name}."
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Music(bot))
