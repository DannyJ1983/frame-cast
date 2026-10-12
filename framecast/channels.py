"""Saved channels: a name, the page to open, and an optional logo, kept on disk.

A channel stores the page address rather than a stream address, because
stream addresses usually expire; the stream is found afresh when it's played.
The list lives in ``channels.json`` in the state folder, logos beside it.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .links import extract_url

log = logging.getLogger(__name__)

MAX_CHANNELS = 200
MAX_NAME_LENGTH = 60
MAX_LOGO_BYTES = 2 * 1024 * 1024
# Image types the TV's browser shows, recognised by their first bytes.
_LOGO_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "png", "image/png"),
    (b"\xff\xd8\xff", "jpg", "image/jpeg"),
    (b"GIF87a", "gif", "image/gif"),
    (b"GIF89a", "gif", "image/gif"),
)


class ChannelError(ValueError):
    """A channel change was refused. The message is written for the person on the phone."""


@dataclass
class Channel:
    """One saved channel. ``logo`` is a file name in the logos folder."""

    id: str
    name: str
    url: str
    logo: str | None = None
    logo_version: int = 0

    def public(self) -> dict[str, Any]:
        """The channel as phones and the TV see it."""
        return {
            "id": self.id,
            "name": self.name,
            "url": self.url,
            "has_logo": self.logo is not None,
            "logo_version": self.logo_version,
        }


def logo_type(data: bytes) -> tuple[str, str] | None:
    """Return (extension, media type) for a PNG, JPEG, GIF or WebP image, else None."""
    for signature, extension, media_type in _LOGO_SIGNATURES:
        if data.startswith(signature):
            return extension, media_type
    if len(data) > 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", "image/webp"
    return None


def _clean_name(name: object) -> str:
    text = " ".join(str(name or "").split())
    if not text:
        raise ChannelError("Give the channel a name.")
    return text[:MAX_NAME_LENGTH]


def _clean_url(url: object) -> str:
    found = extract_url(str(url or ""))
    if not found:
        raise ChannelError("That doesn't look like a web address.")
    return found


class ChannelStore:
    """The saved channels, in order, kept in a folder on disk."""

    def __init__(self, folder: Path) -> None:
        self.folder = Path(folder)
        self.file = self.folder / "channels.json"
        self.logos = self.folder / "logos"
        self._channels: list[Channel] = self._load()

    # Reading -------------------------------------------------------------------

    def all(self) -> list[Channel]:
        """The channels in their saved order."""
        return list(self._channels)

    def public(self) -> list[dict[str, Any]]:
        """The channels as phones and the TV see them."""
        return [c.public() for c in self._channels]

    def get(self, channel_id: str) -> Channel | None:
        """The channel with this id, if there is one."""
        return next((c for c in self._channels if c.id == channel_id), None)

    def neighbour(self, channel_id: str, step: int) -> Channel | None:
        """The channel ``step`` places after (or before) this one, wrapping round."""
        ids = [c.id for c in self._channels]
        if channel_id not in ids:
            return self._channels[0] if self._channels else None
        return self._channels[(ids.index(channel_id) + step) % len(ids)]

    def logo_file(self, channel_id: str) -> tuple[Path, str] | None:
        """The logo's path and media type, if the channel has one."""
        channel = self.get(channel_id)
        if channel is None or channel.logo is None:
            return None
        path = self.logos / channel.logo
        if not path.is_file():
            return None
        kind = logo_type(path.read_bytes()[:16])
        return path, (kind[1] if kind else "application/octet-stream")

    # Changing ------------------------------------------------------------------

    def add(self, name: object, url: object) -> Channel:
        """Save a new channel at the end of the list."""
        if len(self._channels) >= MAX_CHANNELS:
            raise ChannelError(f"That's the limit of {MAX_CHANNELS} channels.")
        channel = Channel(id=secrets.token_urlsafe(6), name=_clean_name(name), url=_clean_url(url))
        self._channels.append(channel)
        self._save()
        log.info("Saved channel %r", channel.name)
        return channel

    def update(self, channel_id: str, name: object = None, url: object = None) -> Channel:
        """Rename a channel or change its page."""
        channel = self._require(channel_id)
        if name is not None:
            channel.name = _clean_name(name)
        if url is not None:
            channel.url = _clean_url(url)
        self._save()
        return channel

    def delete(self, channel_id: str) -> None:
        """Remove a channel and its logo."""
        channel = self._require(channel_id)
        self._remove_logo_file(channel)
        self._channels.remove(channel)
        self._save()
        log.info("Deleted channel %r", channel.name)

    def move(self, channel_id: str, step: int) -> None:
        """Move a channel up (negative) or down (positive) the list."""
        channel = self._require(channel_id)
        index = self._channels.index(channel)
        target = max(0, min(len(self._channels) - 1, index + step))
        self._channels.insert(target, self._channels.pop(index))
        self._save()

    def set_logo(self, channel_id: str, data: bytes) -> Channel:
        """Store a logo image (PNG, JPEG, GIF or WebP) for a channel."""
        channel = self._require(channel_id)
        if not data:
            raise ChannelError("That image was empty.")
        if len(data) > MAX_LOGO_BYTES:
            raise ChannelError("That image is too big; try one under 2 MB.")
        kind = logo_type(data)
        if kind is None:
            raise ChannelError("Use a PNG, JPEG, GIF or WebP image for the logo.")
        self.logos.mkdir(parents=True, exist_ok=True)
        self._remove_logo_file(channel)
        channel.logo = f"{channel.id}.{kind[0]}"
        temp = self.logos / f".{channel.logo}.tmp"
        temp.write_bytes(data)
        os.replace(temp, self.logos / channel.logo)
        channel.logo_version += 1
        self._save()
        return channel

    def remove_logo(self, channel_id: str) -> Channel:
        """Take a channel's logo away."""
        channel = self._require(channel_id)
        self._remove_logo_file(channel)
        channel.logo = None
        channel.logo_version += 1
        self._save()
        return channel

    # Storage -------------------------------------------------------------------

    def _require(self, channel_id: str) -> Channel:
        channel = self.get(channel_id)
        if channel is None:
            raise ChannelError("That channel doesn't exist any more.")
        return channel

    def _remove_logo_file(self, channel: Channel) -> None:
        if channel.logo:
            (self.logos / channel.logo).unlink(missing_ok=True)

    def _load(self) -> list[Channel]:
        if not self.file.exists():
            return []
        try:
            data = json.loads(self.file.read_text())
            return [Channel(**{k: v for k, v in item.items() if k in Channel.__dataclass_fields__}) for item in data]
        except (ValueError, TypeError, OSError) as err:
            broken = self.file.with_suffix(".broken.json")
            log.error("Couldn't read %s (%s); moving it to %s and starting afresh", self.file, err, broken)
            os.replace(self.file, broken)
            return []

    def _save(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        temp = self.file.with_suffix(".json.tmp")
        temp.write_text(json.dumps([asdict(c) for c in self._channels], indent=2))
        os.replace(temp, self.file)
