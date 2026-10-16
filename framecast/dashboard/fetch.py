"""Getting JSON and text from the internet for the dashboard's sources."""

from __future__ import annotations

import logging
import os
from pathlib import Path
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

    async def download(self, url: str, path: Path, max_bytes: int) -> None:
        """Stream ``url`` into ``path``, replacing it only once the whole file has arrived."""
        host = urlsplit(url).hostname
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + ".part")
        try:
            async with self._client.stream("GET", url, timeout=httpx.Timeout(60.0, read=300.0)) as response:
                if response.status_code >= 400:
                    raise FetchError(f"{host} answered {response.status_code}", response.status_code)
                size = 0
                with open(temp, "wb") as handle:
                    async for chunk in response.aiter_bytes(256 * 1024):
                        size += len(chunk)
                        if size > max_bytes:
                            raise FetchError(f"{host} sent more than expected")
                        handle.write(chunk)
            os.replace(temp, path)
        except httpx.HTTPError as err:
            raise FetchError(f"Couldn't download from {host}: {type(err).__name__}") from err
        finally:
            temp.unlink(missing_ok=True)

    async def aclose(self) -> None:
        """Close the connection pool."""
        await self._client.aclose()
