"""
LRCLIB lyrics client.

LRCLIB is a community-maintained, openly-licensed lyrics database
(https://lrclib.net/). The API is free, no key required, and the data
is contributor-submitted under CC0. It's the legally-cleanest lyrics
source available; we use it in place of services like lyrics.ovh
(which scrapes without label deals) or Genius (whose ToS forbids
redistributing lyrics text).
"""

from __future__ import annotations

from typing import Any

import aiohttp


async def fetch_lyrics(
    session: aiohttp.ClientSession,
    artist: str,
    title: str,
    album: str | None = None,
    duration_s: int | None = None,
) -> str | None:
    """Best-effort lyric lookup. Returns plain (un-synced) lyrics or None."""
    params: dict[str, Any] = {"artist_name": artist, "track_name": title}
    if album:
        params["album_name"] = album
    if duration_s:
        params["duration"] = duration_s
    headers = {"User-Agent": "songs.ai/1.0 (https://github.com/yourname/songs.ai)"}
    try:
        async with session.get(
            "https://lrclib.net/api/get", params=params, headers=headers, timeout=10
        ) as r:
            if r.status == 404:
                # Fall back to free-text search.
                return await _search(session, artist, title, headers)
            r.raise_for_status()
            data = await r.json()
            return data.get("plainLyrics") or None
    except (aiohttp.ClientError, TimeoutError):
        return None


async def _search(
    session: aiohttp.ClientSession,
    artist: str,
    title: str,
    headers: dict[str, str],
) -> str | None:
    try:
        async with session.get(
            "https://lrclib.net/api/search",
            params={"track_name": title, "artist_name": artist},
            headers=headers,
            timeout=10,
        ) as r:
            r.raise_for_status()
            results = await r.json()
            if results and isinstance(results, list):
                return results[0].get("plainLyrics") or None
    except (aiohttp.ClientError, TimeoutError):
        pass
    return None
