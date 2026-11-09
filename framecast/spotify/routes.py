"""The Now Playing web routes: its data, the Spotify settings and sign-in, and the screen itself."""

from __future__ import annotations

import html
import json
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from ..hub import Hub
from .auth import CALLBACK_PATH, SpotifyError
from .service import NowPlaying


def add_spotify_routes(app: FastAPI, service: NowPlaying, hub: Hub) -> None:
    """Add /api/spotify*, /api/nowplaying*, the sign-in callback and /nowplaying."""

    def message(status: int, text: str, **extra: Any) -> JSONResponse:
        return JSONResponse({"ok": status < 400, "message": text, **extra}, status_code=status)

    async def body(request: Request) -> dict[str, Any]:
        try:
            data = json.loads(await request.body() or b"{}")
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    @app.get("/api/nowplaying")
    async def now_playing() -> Response:
        return JSONResponse(await service.snapshot(), headers={"cache-control": "no-store"})

    @app.post("/api/nowplaying/show")
    async def show_now_playing() -> Response:
        if not hub.show("nowplaying"):
            return message(409, "The TV app isn't open.")
        return message(200, "Showing Now Playing on the TV.")

    @app.get("/api/spotify")
    async def spotify_status() -> dict[str, Any]:
        return service.status()

    @app.put("/api/spotify/settings")
    async def spotify_settings(request: Request) -> Response:
        try:
            status = service.update_settings(await body(request))
        except SpotifyError as err:
            return message(400, str(err))
        return message(200, "Saved.", **status)

    @app.post("/api/spotify/connect")
    async def spotify_connect() -> Response:
        try:
            url = service.start_connect()
        except SpotifyError as err:
            return message(400, str(err))
        return message(200, "Opening Spotify.", url=url)

    @app.post("/api/spotify/finish")
    async def spotify_finish(request: Request) -> Response:
        try:
            status = await service.finish_connect(str((await body(request)).get("address") or ""))
        except SpotifyError as err:
            return message(400, str(err))
        account = status["settings"]["account"]
        return message(200, f"Connected to Spotify{' as ' + account if account else ''}.", **status)

    @app.post("/api/spotify/disconnect")
    async def spotify_disconnect() -> Response:
        service.disconnect()
        return message(200, "Disconnected from Spotify.", **service.status())

    @app.get("/api/spotify/devices")
    async def spotify_devices() -> Response:
        try:
            return message(200, "OK", devices=await service.devices())
        except SpotifyError as err:
            return message(400, str(err))

    @app.get(CALLBACK_PATH)
    async def spotify_callback(request: Request) -> HTMLResponse:
        # Reached when the browser can get to the hub on 127.0.0.1 (say, through an SSH tunnel).
        try:
            await service.finish_connect(str(request.url.query))
            text, status = "Spotify is connected. You can close this page.", 200
        except SpotifyError as err:
            text, status = str(err), 400
        return HTMLResponse(
            f'<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            f'<title>Frame Cast</title><p style="font:18px sans-serif;margin:2em">{html.escape(text)}</p>',
            status_code=status,
        )

    @app.get("/nowplaying")
    async def now_playing_page() -> RedirectResponse:
        return RedirectResponse("/dashboard/nowplaying.html")
