"""What the dashboard shows, set from the phone page and kept in ``dashboard.json``.

The file holds the train and traffic keys, so it's written readable by the
Frame Cast service only, and the keys are never sent back to phones.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from .news import DEFAULT_FEED
from .sport import DEFAULT_LEAGUES

log = logging.getLogger(__name__)

SECRETS = ("rail_key", "traffic_key")


class DashboardError(ValueError):
    """A dashboard change or update failed. The message is written for the person reading it."""


@dataclass
class DashboardSettings:
    """Everything the dashboard needs to know. Place names are as the lookup found them."""

    place: str = ""
    place_name: str = ""
    latitude: float | None = None
    longitude: float | None = None
    station: str = ""
    station_to: str = ""
    rail_key: str = ""
    traffic_to: str = ""
    traffic_label: str = ""
    traffic_to_name: str = ""
    traffic_to_latitude: float | None = None
    traffic_to_longitude: float | None = None
    traffic_key: str = ""
    news: str = DEFAULT_FEED
    news_url: str = ""
    leagues: list[str] = field(default_factory=lambda: list(DEFAULT_LEAGUES))
    teams: str = ""

    @property
    def has_place(self) -> bool:
        """True once a location has been found."""
        return self.latitude is not None and self.longitude is not None

    @property
    def team_list(self) -> list[str]:
        """The viewer's teams, from the comma-separated setting."""
        return [t.strip() for t in self.teams.split(",") if t.strip()]

    def setup(self) -> dict[str, bool]:
        """Which cards have what they need."""
        return {
            "weather": self.has_place,
            "trains": bool(self.station and self.rail_key),
            "traffic": bool(
                self.has_place and self.traffic_to_latitude is not None and self.traffic_to_longitude is not None
                and self.traffic_key
            ),
            "news": True,
            "sport": bool(self.leagues),
        }

    def public(self) -> dict[str, Any]:
        """The settings as phones see them: keys are replaced by whether one is saved."""
        data = {k: v for k, v in asdict(self).items() if k not in SECRETS}
        data["has_rail_key"] = bool(self.rail_key)
        data["has_traffic_key"] = bool(self.traffic_key)
        return data


class DashboardStore:
    """Loads and saves the dashboard settings in a folder on disk."""

    def __init__(self, folder: Path) -> None:
        self.folder = Path(folder)
        self.file = self.folder / "dashboard.json"
        self.settings = self._load()

    def save(self, settings: DashboardSettings) -> None:
        """Replace the settings, writing the file so only its owner can read it."""
        self.folder.mkdir(parents=True, exist_ok=True)
        temp = self.file.with_suffix(".json.tmp")
        descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            json.dump(asdict(settings), handle, indent=2)
        os.replace(temp, self.file)
        self.settings = settings

    def _load(self) -> DashboardSettings:
        if not self.file.exists():
            return DashboardSettings()
        try:
            data = json.loads(self.file.read_text())
            known = {f.name for f in fields(DashboardSettings)}
            return DashboardSettings(**{k: v for k, v in data.items() if k in known})
        except (ValueError, TypeError, OSError, AttributeError) as err:
            broken = self.file.with_suffix(".broken.json")
            log.error("Couldn't read %s (%s); moving it to %s and starting afresh", self.file, err, broken)
            os.replace(self.file, broken)
            return DashboardSettings()
