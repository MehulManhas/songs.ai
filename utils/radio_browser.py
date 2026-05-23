"""
radio-browser.info client.

A community-maintained, open database of ~50k internet radio stations.
No API key required. We pick a random API server per session to spread
load (their recommended pattern: resolve `all.api.radio-browser.info`
via DNS to get a list of mirrors).

Internet radio stations are already licensed in their own jurisdictions
(SoundExchange / PRS / GEMA etc.), so relaying their public stream
URLs into a voice channel is legally clean - we're just acting as a
listener forwarding what we receive.

API: https://api.radio-browser.info/
"""

from __future__ import annotations

import random
import socket
from dataclasses import dataclass

import aiohttp


@dataclass(slots=True)
class Station:
    uuid: str
    name: str
    url: str               # stream URL (often Icecast/Shoutcast)
    homepage: str
    country: str
    tags: str
    bitrate: int
    favicon: str | None


class RadioBrowserClient:
    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session
        self._server: str | None = None

    def _resolve_server(self) -> str:
        """Pick a random API mirror (radio-browser's recommended approach)."""
        if self._server:
            return self._server
        try:
            hosts = socket.getaddrinfo(
                "all.api.radio-browser.info", 80, proto=socket.IPPROTO_TCP
            )
            names = {h[4][0] for h in hosts}
            # Resolve each IP back to a hostname for a friendlier URL.
            mirrors = set()
            for ip in names:
                try:
                    name = socket.gethostbyaddr(ip)[0]
                    mirrors.add(name)
                except socket.herror:
                    mirrors.add(ip)
            self._server = "https://" + random.choice(sorted(mirrors))
        except socket.gaierror:
            # Fallback: use the well-known endpoint.
            self._server = "https://de1.api.radio-browser.info"
        return self._server

    async def _get(self, path: str, **params) -> list[dict]:
        url = self._resolve_server() + path
        headers = {"User-Agent": "songs.ai-bot/1.0"}
        async with self._session.get(url, params=params, headers=headers, timeout=15) as r:
            r.raise_for_status()
            return await r.json()

    # ------------------------------------------------------------------ search
    async def search(
        self,
        name: str | None = None,
        tag: str | None = None,
        country: str | None = None,
        limit: int = 20,
    ) -> list[Station]:
        data = await self._get(
            "/json/stations/search",
            name=name or "",
            tag=tag or "",
            country=country or "",
            limit=limit,
            hidebroken="true",
            order="clickcount",
            reverse="true",
        )
        return [self._station(d) for d in data]

    async def by_uuid(self, uuid: str) -> Station | None:
        data = await self._get(f"/json/stations/byuuid/{uuid}")
        return self._station(data[0]) if data else None

    async def top(self, limit: int = 20) -> list[Station]:
        data = await self._get("/json/stations/topclick", limit=limit)
        return [self._station(d) for d in data]

    # ------------------------------------------------------------------ helper
    @staticmethod
    def _station(d: dict) -> Station:
        return Station(
            uuid=d.get("stationuuid", ""),
            name=d.get("name", "Unknown"),
            # url_resolved is the final stream URL after any redirects.
            url=d.get("url_resolved") or d.get("url", ""),
            homepage=d.get("homepage", ""),
            country=d.get("country", ""),
            tags=d.get("tags", ""),
            bitrate=int(d.get("bitrate", 0) or 0),
            favicon=d.get("favicon") or None,
        )
