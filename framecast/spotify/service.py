"""Now Playing: the sign-in steps, and a cached view of one device's playback and queue.

Spotify is only asked while a screen is watching: the player at most every
few seconds, and the queue when the track changes or every 20 seconds. Every
viewer shares the same answers, and a "slow down" from Spotify is respected.
"""

from __future__ import annotations

import asyncio
import logging
import re
import secrets
import time
from typing import Any, Callable

import httpx

from . import player
from .auth import SpotifyError, authorize_url, code_challenge, code_from_redirect, code_verifier, redirect_uri
from .client import RateLimited, SpotifyClient
from .store import SpotifyStore

log = logging.getLogger(__name__)

PLAYER_FRESH = 4.0  # seconds a player answer is reused
QUEUE_FRESH = 20.0
_CLIENT_ID = re.compile(r"^[0-9a-f]{32}$")
REFUSED = (
    "Spotify refused access. The Spotify app's owner needs Premium, and your account must be "
    "listed under User Management in the app's settings on developer.spotify.com."
)
FAILED = "Couldn't get what's playing from Spotify just now."


class NowPlaying:
    """Answers the Now Playing screen and the phone page's Spotify settings."""

    def __init__(
        self,
        store: SpotifyStore,
        client: SpotifyClient | None = None,
        port: int = 8090,
        clock: Callable[[], float] = time.monotonic,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self.store = store
        self.client = client or SpotifyClient(store, http)
        self.redirect = redirect_uri(port)
        self._clock = clock
        self._lock = asyncio.Lock()
        self._pending: tuple[str, str] | None = None  # (state, verifier) for a sign-in under way
        self._reset()

    def _reset(self) -> None:
        self._player: dict[str, Any] | None = None
        self._player_at: float | None = None
        self._queue: list[dict[str, Any]] = []
        self._queue_for: str | None = None
        self._queue_at = 0.0
        self._note: str | None = None
        self._quiet_until = 0.0

    # The screen ------------------------------------------------------------------------

    async def snapshot(self) -> dict[str, Any]:
        """What's on the chosen device now, with progress brought up to this moment."""
        settings = self.store.settings
        if not settings.client_id:
            return {"state": "not_set_up", "device": settings.device_name}
        if not settings.connected:
            return {"state": "not_connected", "device": settings.device_name}
        async with self._lock:
            now = self._clock()
            due = self._player_at is None or now - self._player_at >= PLAYER_FRESH
            if due and now >= self._quiet_until:
                await self._refresh()
        if not self.store.settings.connected:  # the sign-in was refused while refreshing
            return {"state": "not_connected", "device": settings.device_name, "note": self._note}
        result = dict(self._player or {"state": "idle", "device": settings.device_name})
        track = result.get("track")
        if track and result["state"] == "playing" and self._player_at is not None:
            elapsed = (self._clock() - self._player_at) * 1000
            result["progress_ms"] = int(min(track["duration_ms"] or 0, result["progress_ms"] + elapsed) or result["progress_ms"] + elapsed)
        result["queue"] = self._queue if track else []
        if self._note:
            result["note"] = self._note
        return result

    async def _refresh(self) -> None:
        settings = self.store.settings
        try:
            status, data = await self.client.get("/me/player", {"additional_types": "episode"})
            if status == 403:
                self._note = REFUSED
                self._player_at = self._clock()
                return
            if status >= 400:
                self._note = FAILED
                self._player_at = self._clock()
                return
            current = player.playback(data if status == 200 else None, settings.device_name)
            self._player, self._player_at, self._note = current, self._clock(), None
            track = current.get("track")
            if not track:
                self._queue, self._queue_for = [], None
                return
            if track["id"] != self._queue_for or self._clock() - self._queue_at >= QUEUE_FRESH:
                status, queue = await self.client.get("/me/player/queue")
                if status == 200:
                    self._queue, self._queue_for, self._queue_at = player.up_next(queue), track["id"], self._clock()
        except RateLimited as err:
            log.warning("Spotify asked us to wait %.0f seconds", err.retry_after)
            self._quiet_until = self._clock() + err.retry_after
        except SpotifyError as err:
            self._note = str(err)
            self._player_at = self._clock()
            if "sign in again" in str(err):
                self.disconnect(keep_note=True)

    # Settings and signing in -----------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """The settings for the phone page, and the redirect address to register with Spotify."""
        return {"settings": self.store.settings.public(), "redirect_uri": self.redirect}

    def update_settings(self, data: dict[str, Any]) -> dict[str, Any]:
        """Apply changes from the phone page. A new Client ID needs a new sign-in."""
        settings = self.store.settings
        if "client_id" in data:
            client_id = str(data["client_id"] or "").strip().lower()
            if client_id and not _CLIENT_ID.match(client_id):
                raise SpotifyError("That doesn't look like a Client ID: it's 32 letters and numbers, from your Spotify app's settings.")
            if client_id != settings.client_id:
                settings.client_id = client_id
                self.disconnect()
        if "device_name" in data:
            name = " ".join(str(data["device_name"] or "").split())[:60]
            if not name:
                raise SpotifyError("Give the name of the speaker or device to watch, as Spotify shows it.")
            if name != settings.device_name:
                settings.device_name = name
                self._reset()
        if "auto_show" in data:
            settings.auto_show = bool(data["auto_show"])
        self.store.save()
        return self.status()

    def start_connect(self) -> str:
        """Begin signing in: returns the Spotify page to open."""
        settings = self.store.settings
        if not settings.client_id:
            raise SpotifyError("Add your Spotify app's Client ID first.")
        verifier, state = code_verifier(), secrets.token_urlsafe(16)
        self._pending = (state, verifier)
        return authorize_url(settings.client_id, self.redirect, code_challenge(verifier), state)

    async def finish_connect(self, address: str) -> dict[str, Any]:
        """Finish signing in with the address Spotify sent the browser to (or just its query string)."""
        if self._pending is None:
            raise SpotifyError("Press Connect first, then paste the address you end up on.")
        state, verifier = self._pending
        code = code_from_redirect(address, state)
        await self.client.exchange(code, verifier, self.redirect)
        self._pending = None
        self._reset()
        log.info("Spotify connected for %s", self.store.settings.account or "an account")
        return self.status()

    def disconnect(self, keep_note: bool = False) -> None:
        """Forget the sign-in."""
        note = self._note
        settings = self.store.settings
        settings.refresh_token, settings.account = "", ""
        self.store.save()
        self.client.forget()
        self._reset()
        if keep_note:
            self._note = note

    async def devices(self) -> list[str]:
        """Names of the Spotify Connect devices Spotify can see right now (asleep ones may be missing)."""
        status, data = await self.client.get("/me/player/devices")
        if status == 403:
            raise SpotifyError(REFUSED)
        if status != 200 or not isinstance(data, dict):
            raise SpotifyError("Couldn't get the list of devices from Spotify just now.")
        return [str(d["name"]) for d in data.get("devices") or [] if isinstance(d, dict) and d.get("name")]

    async def aclose(self) -> None:
        """Close connections."""
        await self.client.aclose()
