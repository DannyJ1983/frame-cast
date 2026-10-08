"""Open the Frame Cast app on the TV, so sharing a link works even when it's closed.

Samsung TVs from 2016 onwards answer a small local API: a REST interface on port
8001 and a WebSocket remote-control channel on port 8002. The first WebSocket
connection makes the TV ask "Allow?" on screen; the token it then hands out is
saved so later connections are silent.

None of this has been tried on the 2019 Frame yet. Each attempt is logged so a
failure can be traced, and ``python -m framecast tv-apps`` lists the app IDs the
TV reports in case the default one is wrong.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx

log = logging.getLogger(__name__)

REST_PORT = 8001
WS_PORT = 8002
REMOTE_NAME = "Frame Cast"


class TvLauncher:
    """Starts an app on a Samsung TV over the local network."""

    def __init__(
        self,
        host: str,
        app_id: str,
        token_file: Path,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.host = host
        self.app_id = app_id
        self.token_file = token_file
        self._transport = transport

    def _rest_url(self, route: str = "") -> str:
        return f"http://{self.host}:{REST_PORT}/api/v2/{route}"

    async def device_info(self) -> dict[str, Any] | None:
        """Return the TV's device info, or None if it doesn't answer (off or unreachable)."""
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=3) as client:
                response = await client.get(self._rest_url())
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPError, ValueError) as err:
            log.info("TV at %s didn't answer: %s", self.host, err)
            return None

    async def launch_rest(self) -> bool:
        """Ask the TV to open the app through its REST interface."""
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=5) as client:
                response = await client.post(self._rest_url(f"applications/{self.app_id}"))
            log.info("REST launch of %s: HTTP %s %s", self.app_id, response.status_code, response.text[:200])
            return response.is_success
        except httpx.HTTPError as err:
            log.info("REST launch of %s failed: %s", self.app_id, err)
            return False

    def _remote(self, timeout: float) -> Any:
        from samsungtvws import SamsungTVWS

        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        return SamsungTVWS(
            self.host,
            port=WS_PORT,
            token_file=str(self.token_file),
            timeout=timeout,
            name=REMOTE_NAME,
        )

    def _launch_ws_blocking(self, timeout: float) -> None:
        with self._remote(timeout) as remote:
            remote.run_app(self.app_id, "DEEP_LINK")

    async def launch_ws(self, timeout: float = 10) -> bool:
        """Ask the TV to open the app through the WebSocket remote channel."""
        try:
            await asyncio.to_thread(self._launch_ws_blocking, timeout)
            log.info("WebSocket launch of %s sent", self.app_id)
            return True
        except Exception as err:  # samsungtvws raises its own errors and socket ones
            log.info("WebSocket launch of %s failed: %r", self.app_id, err)
            return False

    def attempts(self) -> list[tuple[str, Callable[[], Awaitable[bool]]]]:
        """The launch methods to try, in order, with a name for logging."""
        return [("REST", self.launch_rest), ("WebSocket", self.launch_ws)]

    def pair(self, timeout: float = 30) -> None:
        """Connect once so the TV asks to allow Frame Cast, and save the token. Blocking."""
        with self._remote(timeout) as remote:
            remote.open()

    def installed_apps(self, timeout: float = 30) -> list[dict[str, Any]]:
        """Return the apps the TV reports (not every model answers). Blocking."""
        with self._remote(timeout) as remote:
            return remote.app_list() or []
