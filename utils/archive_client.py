"""
Internet Archive client.

Two collections we tap:
  - `etree` : the Live Music Archive. Concerts uploaded with the
    artist's permission (Grateful Dead, Phish, Smashing Pumpkins, and
    thousands more). These are explicitly distributable.
  - `opensource_audio` : indie/CC/public-domain uploads from individuals.

The advanced-search API returns "items" (think albums/concerts);
each item's metadata API returns a file list. We pick the first
playable audio file (mp3 preferred, falling back to ogg/flac).

API docs: https://archive.org/developers/internetarchive/api.html
No API key required. No rate limit listed, but be polite.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import aiohttp

SEARCH_URL = "https://archive.org/advancedsearch.php"
METADATA_URL = "https://archive.org/metadata/{identifier}"
DOWNLOAD_BASE = "https://archive.org/download/"

ALLOWED_COLLECTIONS = ("etree", "opensource_audio", "audio_music", "netlabels")


@dataclass(slots=True)
class ArchiveItem:
    identifier: str
    title: str
    creator: str
    collection: str
    date: str | None


@dataclass(slots=True)
class ArchiveTrack:
    identifier: str        # parent item identifier
    title: str
    creator: str
    duration_s: int
    stream_url: str        # direct MP3/OGG URL
    page_url: str          # archive.org item page


class ArchiveClient:
    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    async def search_items(
        self,
        query: str,
        collection: str = "etree",
        limit: int = 10,
    ) -> list[ArchiveItem]:
        """Search items (concerts/albums) within a collection."""
        if collection not in ALLOWED_COLLECTIONS:
            raise ValueError(f"collection must be one of {ALLOWED_COLLECTIONS}")
        q = f'collection:{collection} AND ({query})'
        params = {
            "q": q,
            "fl[]": ["identifier", "title", "creator", "collection", "date"],
            "rows": limit,
            "output": "json",
            "sort[]": "downloads desc",
        }
        async with self._session.get(SEARCH_URL, params=params, timeout=15) as r:
            r.raise_for_status()
            data = await r.json()
        items = []
        for doc in data.get("response", {}).get("docs", []):
            creator = doc.get("creator", "")
            if isinstance(creator, list):
                creator = ", ".join(creator)
            items.append(ArchiveItem(
                identifier=doc["identifier"],
                title=doc.get("title", doc["identifier"]),
                creator=creator,
                collection=collection,
                date=doc.get("date"),
            ))
        return items

    async def item_tracks(self, identifier: str) -> list[ArchiveTrack]:
        """Return playable audio files from a single item."""
        url = METADATA_URL.format(identifier=identifier)
        async with self._session.get(url, timeout=15) as r:
            r.raise_for_status()
            meta = await r.json()
        files = meta.get("files", [])
        item_meta = meta.get("metadata", {})
        creator = item_meta.get("creator", "")
        if isinstance(creator, list):
            creator = ", ".join(creator)

        # Prefer compact-MP3 versions if present (smaller, faster to stream).
        preferred_format = ("VBR MP3", "128Kbps MP3", "MP3", "Ogg Vorbis", "Flac")
        tracks: list[ArchiveTrack] = []
        for fmt in preferred_format:
            for f in files:
                if f.get("format") != fmt:
                    continue
                name = f.get("name")
                if not name:
                    continue
                try:
                    duration = int(float(f.get("length", "0").split(":")[-1]))
                except (ValueError, AttributeError):
                    duration = 0
                tracks.append(ArchiveTrack(
                    identifier=identifier,
                    title=f.get("title", name),
                    creator=creator,
                    duration_s=duration,
                    stream_url=f"{DOWNLOAD_BASE}{identifier}/{name}",
                    page_url=f"https://archive.org/details/{identifier}",
                ))
            if tracks:
                return tracks  # found one preferred format, stop
        return tracks
