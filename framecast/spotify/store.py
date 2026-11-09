"""The Spotify settings and sign-in, kept in ``spotify.json`` in the state folder (readable by the service only)."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_DEVICE = "Office"


@dataclass
class SpotifySettings:
    """Which Spotify app to sign in with, which device to watch, and the saved sign-in."""

    client_id: str = ""
    device_name: str = DEFAULT_DEVICE
    auto_show: bool = False
    refresh_token: str = ""
    account: str = ""

    @property
    def connected(self) -> bool:
        """True once someone has signed in."""
        return bool(self.client_id and self.refresh_token)

    def public(self) -> dict[str, Any]:
        """The settings as phones see them, without the sign-in token."""
        return {
            "client_id": self.client_id,
            "device_name": self.device_name,
            "auto_show": self.auto_show,
            "connected": self.connected,
            "account": self.account,
        }


class SpotifyStore:
    """Loads and saves the Spotify settings."""

    def __init__(self, folder: Path) -> None:
        self.folder = Path(folder)
        self.file = self.folder / "spotify.json"
        self.settings = self._load()

    def save(self, settings: SpotifySettings | None = None) -> None:
        """Write the settings so only the service's user can read them."""
        if settings is not None:
            self.settings = settings
        self.folder.mkdir(parents=True, exist_ok=True)
        temp = self.file.with_suffix(".json.tmp")
        descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            json.dump(asdict(self.settings), handle, indent=2)
        os.replace(temp, self.file)

    def _load(self) -> SpotifySettings:
        if not self.file.exists():
            return SpotifySettings()
        try:
            data = json.loads(self.file.read_text())
            known = {f.name for f in fields(SpotifySettings)}
            return SpotifySettings(**{k: v for k, v in data.items() if k in known})
        except (ValueError, TypeError, OSError, AttributeError) as err:
            broken = self.file.with_suffix(".broken.json")
            log.error("Couldn't read %s (%s); moving it to %s", self.file, err, broken)
            os.replace(self.file, broken)
            return SpotifySettings()
