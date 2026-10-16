"""Getting JSON and text from the internet for the dashboard's sources."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlsplit

import httpx

log = logging.getLogger(__name__)

USER_AGENT = "FrameCast/0.1 (home dashboard; https://github.com/DannyJ1983/frame-cast)"
MAX_BYTES = 3 * 1024 * 1024


class FetchError(Exception):
    """A request failed. ``status`` is the HTTP status, if the server answered."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class Fetcher:
    """Makes the dashboard's requests. Messages name only the host, never keys in the address."""

    def __init__(self, client: httpx.AsyncClient | None = None, timeout: float = 10.0) -> None:
        self._client = client or httpx.AsyncClient(
            timeout=timeout, follow_redirects=True, headers={"user-agent": USER_AGENT}
        )

    async def _get(self, url: str, params: dict[str, Any] | None, headers: dict[str, str] | None) -> httpx.Response:
        host = urlsplit(url).hostname
        try:
            response = await self._client.get(url, params=params, headers=headers)
        except httpx.HTTPError as err:
            raise FetchError(f"Couldn't reach {host}: {type(err).__name__}") from err
        if response.status_code >= 400:
            raise FetchError(f"{host} answered {response.status_code}", response.status_code)
        if len(response.content) > MAX_BYTES:
            raise FetchError(f"{host} sent more than expected")
        return response

    async def json(self, url: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> Any:
        """GET ``url`` and decode its JSON."""
        response = await self._get(url, params, headers)
        try:
            return response.json()
        except ValueError as err:
            raise FetchError(f"{urlsplit(url).hostname} didn't send JSON") from err

    async def text(self, url: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> str:
        """GET ``url`` as text."""
        return (await self._get(url, params, headers)).text

    async def aclose(self) -> None:
        """Close the connection pool."""
        await self._client.aclose()
