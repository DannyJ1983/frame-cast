"""Shared state: what's playing, which TVs and phones are listening, what's pending.

Everything here runs on the server's event loop, so there are no locks. TVs and
phones each get a queue of (event, data) pairs that the server streams to them
as Server-Sent Events.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

log = logging.getLogger(__name__)

PENDING_TTL = 600.0  # A link shared while the TV app was closed plays if it's opened within this time.
QUEUE_SIZE = 100
# Statuses that show the TV has received a play command.
ACK_STATES = {"loading", "buffering", "playing", "paused", "ended", "error"}
CONTROL_ACTIONS = {"toggle", "pause", "resume", "stop", "seek"}

Event = tuple[str, dict[str, Any]]


@dataclass
class PlayCommand:
    """One stream for the TV to play.

    ``url`` is absolute, or a relay path starting "/p/" that the TV resolves
    against the hub's own address.
    """

    url: str
    title: str
    kind: str
    page_url: str
    is_live: bool = False
    user_agent: str | None = None
    relayed: bool = False
    id: str = field(default_factory=lambda: secrets.token_urlsafe(6))
    created: float = field(default_factory=time.time)

    def to_event(self) -> dict[str, Any]:
        """Return the command as sent to the TV."""
        return asdict(self)


def sse(event: str, data: dict[str, Any]) -> str:
    """Format one Server-Sent Event."""
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


class Hub:
    """Routes play and control commands to TVs, and TV status back to phones."""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._tvs: set[asyncio.Queue[Event]] = set()
        self._phones: set[asyncio.Queue[Event]] = set()
        self._acks: dict[str, asyncio.Event] = {}
        self.current: PlayCommand | None = None
        self.pending: PlayCommand | None = None
        self.tv_status: dict[str, Any] = {"state": "idle"}
        self.last_message: dict[str, Any] | None = None
        self.recent: deque[dict[str, Any]] = deque(maxlen=10)

    # Subscribers ---------------------------------------------------------------

    @property
    def tv_count(self) -> int:
        """How many TV apps are connected."""
        return len(self._tvs)

    def subscribe_tv(self) -> asyncio.Queue[Event]:
        """Register a TV app; it gets any play command shared while it was closed."""
        queue: asyncio.Queue[Event] = asyncio.Queue(QUEUE_SIZE)
        self._tvs.add(queue)
        log.info("TV app connected (%d connected)", len(self._tvs))
        pending = self.pending
        if pending is not None:
            if self._clock() - pending.created <= PENDING_TTL:
                log.info("Sending pending link to the TV: %s", pending.title)
                queue.put_nowait(("play", pending.to_event()))
            else:
                self.pending = None
        self._publish_state()
        return queue

    def unsubscribe_tv(self, queue: asyncio.Queue[Event]) -> None:
        """Forget a TV app that disconnected."""
        self._tvs.discard(queue)
        log.info("TV app disconnected (%d connected)", len(self._tvs))
        self._publish_state()

    def subscribe_phone(self) -> asyncio.Queue[Event]:
        """Register a phone page; it gets the current state straight away."""
        queue: asyncio.Queue[Event] = asyncio.Queue(QUEUE_SIZE)
        self._phones.add(queue)
        queue.put_nowait(("state", self.state()))
        return queue

    def unsubscribe_phone(self, queue: asyncio.Queue[Event]) -> None:
        """Forget a phone page that closed."""
        self._phones.discard(queue)

    @staticmethod
    def _put(queue: asyncio.Queue[Event], event: Event) -> None:
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            log.warning("Dropping %s event for a slow listener", event[0])

    def _to_tvs(self, event: Event) -> int:
        for queue in list(self._tvs):
            self._put(queue, event)
        return len(self._tvs)

    def _to_phones(self, event: Event) -> None:
        for queue in list(self._phones):
            self._put(queue, event)

    def _publish_state(self) -> None:
        self._to_phones(("state", self.state()))

    # Commands ------------------------------------------------------------------

    def play(self, command: PlayCommand) -> int:
        """Send a play command to every connected TV. Returns how many got it.

        The command stays pending until a TV acknowledges it, so a TV app that
        connects (or reconnects) shortly afterwards still plays it.
        """
        self.current = command
        self.pending = command
        self._acks[command.id] = asyncio.Event()
        self.recent.appendleft(
            {"title": command.title, "page_url": command.page_url, "at": self._clock()}
        )
        sent = self._to_tvs(("play", command.to_event()))
        log.info("Play %r sent to %d TV(s)", command.title, sent)
        self._publish_state()
        return sent

    def control(self, action: str, seconds: float | None = None) -> int:
        """Send a playback control to every connected TV. Returns how many got it."""
        if action not in CONTROL_ACTIONS:
            raise ValueError(f"Unknown action {action!r}")
        data: dict[str, Any] = {"action": action}
        if seconds is not None:
            data["seconds"] = seconds
        if action == "stop" and self.pending is not None:
            self.pending = None
        return self._to_tvs(("control", data))

    def report_status(self, status: dict[str, Any]) -> None:
        """Record a status report from a TV app and pass it on to phones."""
        state = str(status.get("state") or "idle")
        self.tv_status = {
            "state": state,
            "message": status.get("message"),
            "position": status.get("position"),
            "duration": status.get("duration"),
            "command_id": status.get("command_id"),
            "title": status.get("title"),
            "at": self._clock(),
        }
        command_id = status.get("command_id")
        if command_id and state in ACK_STATES:
            ack = self._acks.get(command_id)
            if ack is not None:
                ack.set()
            if self.pending is not None and self.pending.id == command_id:
                self.pending = None
        if state == "error":
            log.warning("TV reported an error: %s", status.get("message"))
        self._publish_state()

    def note(self, text: str, level: str = "info") -> None:
        """Show a progress or error message on phone pages."""
        self.last_message = {"text": text, "level": level, "at": self._clock()}
        self._to_phones(("message", self.last_message))

    async def wait_for_ack(self, command_id: str, timeout: float) -> bool:
        """Wait until a TV acknowledges ``command_id``; False if it times out."""
        ack = self._acks.get(command_id)
        if ack is None:
            return False
        try:
            await asyncio.wait_for(ack.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            return False

    def state(self) -> dict[str, Any]:
        """Snapshot of everything a phone page shows."""
        current = self.current
        return {
            "tv_connected": bool(self._tvs),
            "tv": self.tv_status,
            "current": None if current is None else {
                "id": current.id,
                "title": current.title,
                "page_url": current.page_url,
                "is_live": current.is_live,
                "relayed": current.relayed,
            },
            "pending": self.pending is not None,
            "recent": list(self.recent),
            "message": self.last_message,
        }
