"""
Navidrome / Subsonic API client.

Navidrome is the recommended self-hosted server because it implements
the open Subsonic API spec (also used by Airsonic, Gonic, etc.), so
this client works with all of those.

Auth model:
  - Each Discord guild's admin configures one Navidrome connection.
  - We store the password encrypted with Fernet (utils/crypto.py).
  - Every API call uses salted MD5 token auth, per Subsonic spec:
        t = md5(password + salt), salt = random per request.

Lavalink plays the /rest/stream.view URL directly via its built-in
HTTP source - no special connector required.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import aiohttp

API_VERSION = "1.16.1"
CLIENT_NAME = "songs.ai"


@dataclass(slots=True)
class LibraryTrack:
    id: str
    title: str
    artist: str
    album: str
    duration_s: int
    stream_url: str         # Already includes auth params - Lavalink can fetch it
    cover_url: str | None

    @property
    def duration_ms(self) -> int:
        return self.duration_s * 1000


class NavidromeClient:
    """Per-guild client. Instantiate once with the decrypted credentials."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        username: str,
        password: str,
    ) -> None:
        self._session = session
        # Normalize: strip trailing slash, append /rest if missing.
        base = base_url.rstrip("/")
        if not base.endswith("/rest"):
            base = base + "/rest"
        self._base = base
        self._user = username
        self._password = password

    # ------------------------------------------------------------------ auth
    def _auth_params(self) -> dict[str, str]:
        salt = secrets.token_hex(8)
        token = hashlib.md5((self._password + salt).encode("utf-8")).hexdigest()
        return {
            "u": self._user,
            "t": token,
            "s": salt,
            "v": API_VERSION,
            "c": CLIENT_NAME,
            "f": "json",
        }

    async def _get(self, method: str, **params: Any) -> dict:
        url = f"{self._base}/{method}.view"
        merged = {**self._auth_params(), **{k: v for k, v in params.items() if v is not None}}
        async with self._session.get(url, params=merged, timeout=10) as r:
            r.raise_for_status()
            data = await r.json()
            sr = data.get("subsonic-response", {})
            if sr.get("status") != "ok":
                err = sr.get("error", {})
                raise RuntimeError(f"Subsonic error: {err}")
            return sr

    def _stream_url(self, song_id: str) -> str:
        """Build a streamable URL that includes auth params inline."""
        params = {**self._auth_params(), "id": song_id, "format": "mp3"}
        return f"{self._base}/stream.view?{urlencode(params)}"

    # ------------------------------------------------------------------ ping
    async def ping(self) -> bool:
        """Used by /library setup to validate credentials."""
        try:
            await self._get("ping")
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------ search
    async def search(self, query: str, limit: int = 20) -> list[LibraryTrack]:
        data = await self._get(
            "search3",
            query=query,
            songCount=limit,
            artistCount=0,
            albumCount=0,
        )
        songs = data.get("searchResult3", {}).get("song", [])
        return [self._track(s) for s in songs]

    async def random_songs(self, limit: int = 20, genre: str | None = None) -> list[LibraryTrack]:
        data = await self._get("getRandomSongs", size=limit, genre=genre)
        songs = data.get("randomSongs", {}).get("song", [])
        return [self._track(s) for s in songs]

    async def album_tracks(self, album_id: str) -> list[LibraryTrack]:
        data = await self._get("getAlbum", id=album_id)
        songs = data.get("album", {}).get("song", [])
        return [self._track(s) for s in songs]

    async def playlist_tracks(self, playlist_id: str) -> list[LibraryTrack]:
        data = await self._get("getPlaylist", id=playlist_id)
        songs = data.get("playlist", {}).get("entry", [])
        return [self._track(s) for s in songs]

    # ------------------------------------------------------------------ helper
    def _track(self, obj: dict) -> LibraryTrack:
        cover_url = None
        cover_id = obj.get("coverArt")
        if cover_id:
            params = {**self._auth_params(), "id": cover_id, "size": 300}
            cover_url = f"{self._base}/getCoverArt.view?{urlencode(params)}"
        return LibraryTrack(
            id=str(obj["id"]),
            title=obj.get("title", "Unknown"),
            artist=obj.get("artist", "Unknown"),
            album=obj.get("album", ""),
            duration_s=int(obj.get("duration", 0)),
            stream_url=self._stream_url(str(obj["id"])),
            cover_url=cover_url,
        )
