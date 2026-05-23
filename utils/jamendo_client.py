"""
Jamendo API client - the bot's default music source.

Jamendo distributes ~600k Creative Commons licensed tracks. Their
developer terms (https://devportal.jamendo.com/v3.0/tracks) explicitly
permit streaming the audio URLs returned by the API, including for
background-music use. This is the legally cleanest streaming source
we ship with the bot.

API key: free, get one at https://devporter.jamendo.com/
Free tier: 35,000 requests / month - plenty for normal use.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import aiohttp


@dataclass(slots=True)
class JamendoTrack:
    """One Jamendo track. `audio` is a direct streamable MP3 URL."""
    id: str
    name: str
    artist_name: str
    album_name: str
    duration_s: int
    audio: str             # MP3 stream URL (this is what Lavalink plays)
    share_url: str         # Page on jamendo.com (for /nowplaying embed link)
    image: str | None      # Album art
    license_url: str       # Specific CC license URL for this track

    @property
    def duration_ms(self) -> int:
        return self.duration_s * 1000


class JamendoClient:
    BASE = "https://api.jamendo.com/v3.0/"

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session
        self._client_id = os.environ["JAMENDO_CLIENT_ID"]

    async def _get(self, path: str, **params: Any) -> dict:
        params = {
            **params,
            "client_id": self._client_id,
            "format": "json",
            # `audioformat=mp32` -> 128kbit MP3. Use mp31 for low-bw, ogg for OGG.
            "audioformat": params.get("audioformat", "mp32"),
        }
        async with self._session.get(self.BASE + path, params=params, timeout=10) as r:
            r.raise_for_status()
            data = await r.json()
            if data.get("headers", {}).get("status") != "success":
                raise RuntimeError(f"Jamendo error: {data.get('headers')}")
            return data

    # ------------------------------------------------------------------ search
    async def search_tracks(
        self, query: str, limit: int = 20, order: str = "popularity_week"
    ) -> list[JamendoTrack]:
        """Free-text search across all tracks."""
        data = await self._get(
            "tracks/",
            search=query,
            limit=limit,
            order=order,
            include="musicinfo licenses",
        )
        return [self._track(t) for t in data.get("results", [])]

    async def tracks_by_tag(
        self, tag: str, limit: int = 20
    ) -> list[JamendoTrack]:
        """Browse by mood / genre tag (e.g. 'rock', 'chill', 'electronic')."""
        data = await self._get(
            "tracks/",
            tags=tag,
            limit=limit,
            order="popularity_week",
            include="musicinfo licenses",
        )
        return [self._track(t) for t in data.get("results", [])]

    async def popular(self, limit: int = 20) -> list[JamendoTrack]:
        """Most-played tracks this week."""
        data = await self._get(
            "tracks/", limit=limit, order="popularity_week", include="licenses"
        )
        return [self._track(t) for t in data.get("results", [])]

    async def track(self, track_id: str) -> JamendoTrack | None:
        """Fetch a single track by ID."""
        data = await self._get("tracks/", id=track_id, include="licenses")
        results = data.get("results") or []
        return self._track(results[0]) if results else None

    async def tracks_by_artist(
        self, artist_name: str, limit: int = 10
    ) -> list[JamendoTrack]:
        """Find tracks by a specific artist name (used by /discover)."""
        data = await self._get(
            "tracks/",
            artist_name=artist_name,
            limit=limit,
            order="popularity_total",
            include="licenses",
        )
        return [self._track(t) for t in data.get("results", [])]

    # ------------------------------------------------------------------ helper
    @staticmethod
    def _track(obj: dict) -> JamendoTrack:
        return JamendoTrack(
            id=str(obj["id"]),
            name=obj["name"],
            artist_name=obj["artist_name"],
            album_name=obj.get("album_name", ""),
            duration_s=int(obj.get("duration", 0)),
            audio=obj["audio"],
            share_url=obj.get("shareurl", ""),
            image=obj.get("album_image") or obj.get("image"),
            license_url=obj.get("license_ccurl", ""),
        )
