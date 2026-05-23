"""
Per-guild queue state.

Wavelink ships with its own queue, but rolling our own gives us:
  - Loop modes (off / track / queue)
  - The "requester" attached to each track
  - Skip-vote state per current track
"""

from __future__ import annotations

import enum
from collections import deque
from dataclasses import dataclass, field
from typing import Deque

import wavelink


class LoopMode(enum.IntEnum):
    OFF = 0
    TRACK = 1
    QUEUE = 2


@dataclass(slots=True)
class QueuedTrack:
    track: wavelink.Playable
    requester_id: int
    # Source page URL for the embed link (e.g. jamendo.com track page,
    # archive.org item page). None for radio / library tracks.
    source_url: str | None = None


@dataclass
class GuildState:
    queue: Deque[QueuedTrack] = field(default_factory=deque)
    history: Deque[QueuedTrack] = field(default_factory=lambda: deque(maxlen=50))
    loop: LoopMode = LoopMode.OFF
    skip_votes: set[int] = field(default_factory=set)
    text_channel_id: int | None = None  # where to post now-playing embeds

    def push(self, item: QueuedTrack) -> None:
        self.queue.append(item)

    def push_front(self, item: QueuedTrack) -> None:
        self.queue.appendleft(item)

    def pop(self) -> QueuedTrack | None:
        if not self.queue:
            return None
        return self.queue.popleft()

    def clear(self) -> None:
        self.queue.clear()
        self.skip_votes.clear()


class QueueManager:
    """Holds one GuildState per guild."""

    def __init__(self) -> None:
        self._by_guild: dict[int, GuildState] = {}

    def get(self, guild_id: int) -> GuildState:
        state = self._by_guild.get(guild_id)
        if state is None:
            state = GuildState()
            self._by_guild[guild_id] = state
        return state

    def drop(self, guild_id: int) -> None:
        self._by_guild.pop(guild_id, None)
