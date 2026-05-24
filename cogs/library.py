"""
Library cog - per-guild Navidrome (Subsonic) integration.

The "self-hosted personal library" path. Each Discord server admin
configures one Navidrome connection for their guild via /library setup.
Credentials are encrypted with Fernet (utils.crypto) before storage.

Commands:
  /library setup <url> <username> <password>  (admin only)
  /library disconnect                          (admin only)
  /library status
  /library play <query>
  /library random [genre]
"""

from __future__ import annotations

import logging
import os
from typing import Any

import aiohttp
import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands

from cogs.music import Music
from utils.crypto import decrypt, encrypt
from utils.navidrome_client import NavidromeClient

log = logging.getLogger("songs.ai.library")

# SONGS_DB_PATH is set by docker-compose to a path on a persistent volume
# so the SQLite file survives container rebuilds. Falls back to a local file
# when running outside Docker.
DB_PATH = os.environ.get("SONGS_DB_PATH", "songs.sqlite")


class Library(commands.Cog):
    library_group = app_commands.Group(
        name="library",
        description="Play from a self-hosted Navidrome/Subsonic library.",
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._db: aiosqlite.Connection | None = None
        self._http: aiohttp.ClientSession | None = None

    async def cog_load(self) -> None:
        self._http = aiohttp.ClientSession()
        self._db = await aiosqlite.connect(DB_PATH)
        await self._db.execute(
            "CREATE TABLE IF NOT EXISTS navidrome_guild ("
            "  guild_id INTEGER PRIMARY KEY,"
            "  base_url TEXT NOT NULL,"
            "  username TEXT NOT NULL,"
            "  password_enc TEXT NOT NULL"
            ")"
        )
        await self._db.commit()

    async def cog_unload(self) -> None:
        if self._db:
            await self._db.close()
        if self._http:
            await self._http.close()

    # --------------------------------------------------- internal helpers
    async def _client_for(self, guild_id: int) -> NavidromeClient | None:
        assert self._db is not None
        async with self._db.execute(
            "SELECT base_url, username, password_enc FROM navidrome_guild WHERE guild_id = ?",
            (guild_id,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        assert self._http is not None
        return NavidromeClient(
            self._http, base_url=row[0], username=row[1], password=decrypt(row[2])
        )

    def _music(self) -> Music | None:
        return self.bot.get_cog("Music")  # type: ignore[return-value]

    # --------------------------------------------------- /library setup
    @library_group.command(
        name="setup",
        description="Connect this server to a Navidrome / Subsonic instance.",
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(
        url="Base URL of your Navidrome (e.g. https://music.example.com)",
        username="Your Navidrome username",
        password="Your Navidrome password (stored encrypted)",
    )
    async def setup(
        self, interaction: discord.Interaction,
        url: str, username: str, password: str,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        if interaction.guild is None:
            await interaction.followup.send("Server-only.", ephemeral=True)
            return
        assert self._http is not None
        client = NavidromeClient(self._http, url, username, password)
        if not await client.ping():
            await interaction.followup.send(
                "Couldn't authenticate to that Navidrome instance. "
                "Check the URL, username, and password.", ephemeral=True
            )
            return
        assert self._db is not None
        await self._db.execute(
            "INSERT INTO navidrome_guild (guild_id, base_url, username, password_enc) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(guild_id) DO UPDATE SET "
            " base_url=excluded.base_url, "
            " username=excluded.username, "
            " password_enc=excluded.password_enc",
            (interaction.guild.id, url.rstrip("/"), username, encrypt(password)),
        )
        await self._db.commit()
        await interaction.followup.send(
            "Library connected. Try `/library random` or `/library play <query>`.",
            ephemeral=True,
        )

    # ---------------------------------------------- /library disconnect
    @library_group.command(name="disconnect", description="Forget this server's Navidrome connection.")
    @app_commands.default_permissions(manage_guild=True)
    async def disconnect(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Server-only.", ephemeral=True)
            return
        assert self._db is not None
        await self._db.execute(
            "DELETE FROM navidrome_guild WHERE guild_id = ?", (interaction.guild.id,)
        )
        await self._db.commit()
        await interaction.response.send_message("Disconnected.", ephemeral=True)

    # --------------------------------------------------- /library status
    @library_group.command(name="status", description="Show whether a library is connected.")
    async def status(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Server-only.", ephemeral=True)
            return
        client = await self._client_for(interaction.guild.id)
        if client is None:
            await interaction.response.send_message(
                "No library connected. An admin can run `/library setup`.",
                ephemeral=True,
            )
            return
        ok = await client.ping()
        await interaction.response.send_message(
            "Library reachable ✅" if ok else "Library unreachable ❌",
            ephemeral=True,
        )

    # --------------------------------------------------- /library play
    @library_group.command(name="play", description="Search your library and queue a track.")
    async def play(self, interaction: discord.Interaction, query: str) -> None:
        await interaction.response.defer()
        if interaction.guild is None:
            await interaction.followup.send("Server-only.", ephemeral=True)
            return
        music = self._music()
        if music is None:
            await interaction.followup.send("Music cog not loaded.", ephemeral=True)
            return
        client = await self._client_for(interaction.guild.id)
        if client is None:
            await interaction.followup.send(
                "No library connected. An admin can run `/library setup`.",
                ephemeral=True,
            )
            return
        try:
            results = await client.search(query, limit=1)
        except Exception:
            log.exception("Subsonic search failed")
            await interaction.followup.send(
                "Library search failed — is the server still reachable?",
                ephemeral=True,
            )
            return
        if not results:
            await interaction.followup.send("No matches in your library.", ephemeral=True)
            return
        track = results[0]
        player = await music.ensure_voice(interaction)
        if player is None:
            return
        await music.queue_url(
            player, interaction.guild.id, interaction.user.id,
            track.stream_url, source_url=None,
        )
        await interaction.followup.send(
            f"Queued from library: **{track.title}** — {track.artist}"
        )

    # --------------------------------------------------- /library random
    @library_group.command(name="random", description="Queue random tracks from your library.")
    @app_commands.describe(
        count="How many tracks (1-25)",
        genre="Optional: limit to a genre",
    )
    async def random(
        self, interaction: discord.Interaction,
        count: app_commands.Range[int, 1, 25] = 10,
        genre: str | None = None,
    ) -> None:
        await interaction.response.defer()
        if interaction.guild is None:
            await interaction.followup.send("Server-only.", ephemeral=True)
            return
        music = self._music()
        client = await self._client_for(interaction.guild.id)
        if music is None or client is None:
            await interaction.followup.send(
                "Music or library not configured.", ephemeral=True
            )
            return
        try:
            tracks = await client.random_songs(limit=count, genre=genre)
        except Exception:
            log.exception("Subsonic random failed")
            await interaction.followup.send("Library unreachable.", ephemeral=True)
            return
        if not tracks:
            await interaction.followup.send("Library returned nothing.", ephemeral=True)
            return
        player = await music.ensure_voice(interaction)
        if player is None:
            return
        queued = 0
        for t in tracks:
            if await music.queue_url(
                player, interaction.guild.id, interaction.user.id,
                t.stream_url, source_url=None,
            ):
                queued += 1
        await interaction.followup.send(f"Queued **{queued}** library tracks.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Library(bot))
