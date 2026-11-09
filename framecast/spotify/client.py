"""Talking to Spotify: exchanging and refreshing tokens, and GET requests to the Web API."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

import httpx

from .auth import API_URL, TOKEN_URL, SpotifyError
from .store import SpotifyStore

log = logging.getLogger(__name__)

EARLY_REFRESH = 60.0  # refresh a minute before the access token runs out


class RateLimited(Exception):
    """Spotify asked us to slow down; ``retry_after`` is in seconds."""

    def __init__(self, retry_after: float) -> None:
        super().__init__(f"rate limited for {retry_after}s")
        self.retry_after = retry_after


class SpotifyClient:
    """A signed-in connection to the Web API. Access tokens live in memory; the refresh token is saved."""

    def __init__(self, store: SpotifyStore, http: httpx.AsyncClient | None = None, clock: Callable[[], float] = time.time) -> None:
        self.store = store
        self.http = http or httpx.AsyncClient(timeout=10.0)
        self._clock = clock
        self._access_token = ""
        self._expires_at = 0.0

    async def _token_request(self, form: dict[str, str]) -> dict[str, Any]:
        try:
            response = await self.http.post(TOKEN_URL, data=form)
        except httpx.HTTPError as err:
            raise SpotifyError("Couldn't reach Spotify just now.") from err
        data = response.json() if response.content else {}
        if response.status_code >= 400:
            reason = data.get("error_description") or data.get("error") or str(response.status_code)
            log.warning("Spotify token request failed: %s", reason)
            if data.get("error") == "invalid_grant":
                raise SpotifyError("Spotify didn't accept the sign-in. Press Connect to sign in again.")
            if data.get("error") == "invalid_client":
                raise SpotifyError("Spotify didn't recognise the Client ID. Check it in the Spotify settings.")
            raise SpotifyError(f"Spotify sign-in failed ({reason}).")
        self._access_token = data["access_token"]
        self._expires_at = self._clock() + float(data.get("expires_in", 3600))
        if data.get("refresh_token"):
            # With PKCE, Spotify can hand out a new refresh token each time; the old one may stop working.
            self.store.settings.refresh_token = data["refresh_token"]
            self.store.save()
        return data

    async def exchange(self, code: str, verifier: str, redirect: str) -> None:
        """Swap an authorisation code for tokens, and note whose account it is."""
        await self._token_request({
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect,
            "client_id": self.store.settings.client_id,
            "code_verifier": verifier,
        })
        status, me = await self.get("/me")
        if status == 200 and isinstance(me, dict):
            self.store.settings.account = str(me.get("display_name") or me.get("id") or "")
            self.store.save()

    async def _token(self) -> str:
        if self._access_token and self._clock() < self._expires_at - EARLY_REFRESH:
            return self._access_token
        settings = self.store.settings
        if not settings.connected:
            raise SpotifyError("Spotify isn't connected.")
        await self._token_request({
            "grant_type": "refresh_token",
            "refresh_token": settings.refresh_token,
            "client_id": settings.client_id,
        })
        return self._access_token

    def forget(self) -> None:
        """Drop the access token held in memory."""
        self._access_token, self._expires_at = "", 0.0

    async def get(self, path: str, params: dict[str, Any] | None = None) -> tuple[int, Any]:
        """GET a Web API path such as "/me/player". Returns (status, JSON or None for 204)."""
        for attempt in (1, 2):
            headers = {"Authorization": f"Bearer {await self._token()}"}
            try:
                response = await self.http.get(API_URL + path, params=params, headers=headers)
            except httpx.HTTPError as err:
                raise SpotifyError("Couldn't reach Spotify just now.") from err
            if response.status_code == 401 and attempt == 1:
                self.forget()  # expired early or revoked: refresh once and try again
                continue
            if response.status_code == 429:
                raise RateLimited(float(response.headers.get("retry-after") or 30))
            if response.status_code == 204 or not response.content:
                return response.status_code, None
            try:
                return response.status_code, response.json()
            except ValueError as err:
                raise SpotifyError("Spotify sent something unexpected.") from err
        return 401, None

    async def aclose(self) -> None:
        """Close the connection pool."""
        await self.http.aclose()
