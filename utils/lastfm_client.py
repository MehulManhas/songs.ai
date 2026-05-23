"""
Last.fm API client - we use it strictly for similar-artist data, which is
the most reliable free replacement for Spotify's killed /recommendations
endpoint (deprecated Nov 2024).

Docs: https://www.last.fm/api/show/artist.getSimilar
"""

from __future__ import annotations

import os
from typing import Any

import aiohttp


class LastFmClient:
    BASE = "https://ws.audioscrobbler.com/2.0/"

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session
        self._key = os.environ["LASTFM_API_KEY"]

    async def _get(self, **params: Any) -> dict:
        params = {**params, "api_key": self._key, "format": "json"}
        async with self._session.get(self.BASE, params=params, timeout=10) as r:
            r.raise_for_status()
            return await r.json()

    async def similar_artists(self, artist: str, limit: int = 20) -> list[str]:
        data = await self._get(
            method="artist.getsimilar", artist=artist, limit=limit, autocorrect=1
        )
        return [
            a["name"]
            for a in data.get("similarartists", {}).get("artist", [])
        ]

    async def top_tracks(self, artist: str, limit: int = 5) -> list[tuple[str, str]]:
        data = await self._get(
            method="artist.gettoptracks", artist=artist, limit=limit, autocorrect=1
        )
        return [
            (t["name"], t["artist"]["name"])
            for t in data.get("toptracks", {}).get("track", [])
        ]
