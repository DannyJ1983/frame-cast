"""The dashboard's web routes: its data, its settings, the page itself, and showing it on the TV."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from ..hub import Hub
from .service import DashboardService
from .settings import DashboardError

PAGE_DIR = Path(__file__).resolve().parent / "page"


def page_version(folder: Path = PAGE_DIR) -> str:
    """A short fingerprint of the page's files, so an open page can reload itself after an update."""
    digest = hashlib.sha1()
    for path in sorted(folder.rglob("*")):
        if path.is_file():
            digest.update(path.name.encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()[:10]


def add_dashboard_routes(app: FastAPI, service: DashboardService, hub: Hub) -> None:
    """Add /api/dashboard*, the page at /dashboard/, and the departures board at /board."""
    version = page_version()

    def message(status: int, text: str) -> JSONResponse:
        return JSONResponse({"ok": status < 400, "message": text}, status_code=status)

    @app.get("/api/dashboard")
    async def dashboard_data(cards: str | None = None) -> Response:
        only = [name.strip() for name in cards.split(",")] if cards else None
        data = await service.snapshot(only)
        data["page_version"] = version
        return JSONResponse(data, headers={"cache-control": "no-store"})

    @app.get("/api/dashboard/settings")
    async def dashboard_settings() -> dict[str, Any]:
        return {"settings": service.store.settings.public(), "options": service.options()}

    @app.put("/api/dashboard/settings")
    async def change_dashboard_settings(request: Request) -> Response:
        try:
            data = json.loads(await request.body() or b"{}")
        except ValueError:
            data = None
        if not isinstance(data, dict):
            return message(400, "Expected the settings as JSON.")
        try:
            settings = await service.update_settings(data)
        except DashboardError as err:
            return message(400, str(err))
        return JSONResponse({"ok": True, "message": "Saved. The dashboard will update in a moment.", "settings": settings})

    @app.post("/api/dashboard/show")
    async def show_dashboard() -> Response:
        if not hub.show("dashboard"):
            return message(409, "The TV app isn't open.")
        return message(200, "Showing the dashboard on the TV.")

    @app.get("/board")
    async def departures_board() -> RedirectResponse:
        return RedirectResponse("/dashboard/board.html")

    app.mount("/dashboard", StaticFiles(directory=PAGE_DIR, html=True), name="dashboard")
