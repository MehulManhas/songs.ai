"""
songs.ai - Discord music bot entrypoint (legal-sources-only build).

Audio sources used by this bot:
  - Jamendo               (Creative Commons licensed indie music)
  - Navidrome / Subsonic  (self-hosted personal library you own)
  - Internet Archive      (artist-permitted live + public-domain audio)
  - radio-browser.info    (licensed internet radio relay)

There is no YouTube fallback, no Spotify integration, and no audio
from major-label streaming services. This is by design: it eliminates
takedown risk so the bot can be safely published publicly.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import discord
import wavelink
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)-7s %(name)s :: %(message)s",
)
log = logging.getLogger("songs.ai")


INITIAL_COGS = (
    "cogs.music",        # /play (Jamendo), queue, controls, /jamendo group
    "cogs.library",      # /library group  (Navidrome / Subsonic)
    "cogs.archive",      # /archive group  (Internet Archive)
    "cogs.radio",        # /radio group    (radio-browser.info)
    "cogs.discover",     # /discover group (Last.fm + Jamendo)
    "cogs.ux",           # /nowplaying /lyrics /skip /forceskip /credits
)


class SongsBot(commands.AutoShardedBot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        # No privileged intents needed - slash commands only.
        intents.voice_states = True
        intents.guilds = True
        super().__init__(
            command_prefix="!",  # unused
            intents=intents,
            help_command=None,
            description="songs.ai - legally-clean Discord music bot",
        )
        self.dev_guild_id: int | None = (
            int(os.environ["DEV_GUILD_ID"]) if os.getenv("DEV_GUILD_ID") else None
        )

    async def setup_hook(self) -> None:
        for cog in INITIAL_COGS:
            try:
                await self.load_extension(cog)
                log.info("Loaded cog: %s", cog)
            except Exception:
                log.exception("Failed to load cog %s", cog)

        # Connect to Lavalink
        nodes = [
            wavelink.Node(
                uri=f"http://{os.environ['LAVALINK_HOST']}:{os.environ['LAVALINK_PORT']}",
                password=os.environ["LAVALINK_PASSWORD"],
                identifier="songs-ai-main",
            )
        ]
        await wavelink.Pool.connect(nodes=nodes, client=self, cache_capacity=100)

        # Sync slash commands
        if self.dev_guild_id:
            guild = discord.Object(id=self.dev_guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("Synced %d guild commands to dev guild %s",
                     len(synced), self.dev_guild_id)
        else:
            synced = await self.tree.sync()
            log.info("Synced %d global commands (up to 1h to propagate)",
                     len(synced))

    async def on_ready(self) -> None:
        log.info("Logged in as %s (id=%s, %d guilds, %d shards)",
                 self.user, self.user.id if self.user else "?",
                 len(self.guilds), self.shard_count or 1)

    async def on_wavelink_node_ready(
        self, payload: wavelink.NodeReadyEventPayload
    ) -> None:
        log.info("Lavalink node ready: %s (resumed=%s)",
                 payload.node.identifier, payload.resumed)


async def main() -> None:
    token = os.environ.get("DISCORD_TOKEN")
    if not token or token == "replace-me":
        raise SystemExit("DISCORD_TOKEN missing. Copy .env.example to .env.")

    Path(__file__).parent.joinpath("cogs", "__init__.py").touch(exist_ok=True)
    Path(__file__).parent.joinpath("utils", "__init__.py").touch(exist_ok=True)

    async with SongsBot() as bot:
        await bot.start(token)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Shutting down.")
