"""Answers shaped like Spotify's Web API (per its published API specification), and a fake Spotify to serve them."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs

import httpx

CLIENT_ID = "0123456789abcdef0123456789abcdef"


def images(name: str) -> list[dict[str, Any]]:
    return [{"url": f"https://i.scdn.co/image/{name}-640", "width": 640, "height": 640},
            {"url": f"https://i.scdn.co/image/{name}-300", "width": 300, "height": 300},
            {"url": f"https://i.scdn.co/image/{name}-64", "width": 64, "height": 64}]


def track(track_id: str, name: str, artists: list[str], album: str, duration_ms: int = 215000) -> dict[str, Any]:
    return {"type": "track", "id": track_id, "uri": f"spotify:track:{track_id}", "name": name,
            "duration_ms": duration_ms, "artists": [{"name": a, "type": "artist"} for a in artists],
            "album": {"name": album, "images": images(track_id), "album_type": "album"}}


EPISODE = {"type": "episode", "id": "ep1", "name": "Episode 12: Brighton Pier", "duration_ms": 3000000,
           "images": images("ep1"), "show": {"name": "Seaside Stories", "publisher": "Sussex Audio", "images": images("show")}}

NOW = track("t1", "Blue Monday", ["New Order"], "Power, Corruption & Lies", 449000)
NEXT = [track("t2", "Age of Consent", ["New Order"], "Power, Corruption & Lies"),
        track("t3", "Ceremony", ["New Order", "Joy Division"], "Movement"),
        track("t4", "Temptation", ["New Order"], "Substance")]


def device(name: str = "Office", active: bool = True) -> dict[str, Any]:
    return {"id": f"dev-{name}", "name": name, "type": "Speaker", "is_active": active,
            "is_private_session": False, "is_restricted": False, "volume_percent": 40, "supports_volume": True}


def player_state(item: dict[str, Any] | None = NOW, name: str = "Office", playing: bool = True,
                 progress: int = 61000, kind: str = "track") -> dict[str, Any]:
    return {"device": device(name), "repeat_state": "off", "shuffle_state": False, "context": None,
            "timestamp": 1762700000000, "progress_ms": progress, "is_playing": playing, "item": item,
            "currently_playing_type": kind, "actions": {"disallows": {"resuming": True}}}


class FakeSpotify:
    """A stand-in for accounts.spotify.com and api.spotify.com, for httpx.MockTransport."""

    def __init__(self) -> None:
        self.player: Any = player_state()
        self.queue: Any = {"currently_playing": NOW, "queue": NEXT}
        self.devices = [device("Office"), device("Kitchen", False)]
        self.requests: list[httpx.Request] = []
        self.token_count = 0
        self.refresh_ok = True
        self.status: dict[str, int] = {}  # path -> forced status
        self.expire_next = False

    def form(self, request: httpx.Request) -> dict[str, str]:
        return {k: v[0] for k, v in parse_qs(request.content.decode()).items()}

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host == "accounts.spotify.com":
            form = self.form(request)
            if form.get("grant_type") == "refresh_token" and not self.refresh_ok:
                return httpx.Response(400, json={"error": "invalid_grant", "error_description": "Refresh token revoked"})
            self.token_count += 1
            return httpx.Response(200, json={"access_token": f"access-{self.token_count}", "token_type": "Bearer",
                                             "expires_in": 3600, "scope": "user-read-playback-state",
                                             "refresh_token": f"refresh-{self.token_count}"})
        path = request.url.path.removeprefix("/v1")
        if self.expire_next and path != "/me":
            self.expire_next = False
            return httpx.Response(401, json={"error": {"status": 401, "message": "The access token expired"}})
        if path in self.status:
            code = self.status[path]
            return httpx.Response(code, headers={"retry-after": "30"}, json={"error": {"status": code, "message": "no"}})
        if path == "/me":
            return httpx.Response(200, json={"id": "danny", "display_name": "Danny"})
        if path == "/me/player":
            return httpx.Response(204) if self.player is None else httpx.Response(200, json=self.player)
        if path == "/me/player/queue":
            return httpx.Response(200, json=self.queue)
        if path == "/me/player/devices":
            return httpx.Response(200, json={"devices": self.devices})
        return httpx.Response(404, json={"error": {"status": 404, "message": "Not found"}})

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))

    def calls(self, path: str) -> int:
        return sum(1 for r in self.requests if r.url.path == "/v1" + path)
