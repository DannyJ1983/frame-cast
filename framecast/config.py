"""Settings for the home server, from environment variables and the command line."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

# Must match the application id in tv/config.xml.
DEFAULT_APP_ID = "FrameCast0.FrameCast"
RELAY_MODES = ("auto", "always", "never")
REPO_TV_DIR = Path(__file__).resolve().parent.parent / "tv"


def _default_tv_dir() -> Path | None:
    return REPO_TV_DIR if REPO_TV_DIR.is_dir() else None


@dataclass
class Settings:
    """How the hub runs.

    ``relay`` is "auto" (relay only streams that need it), "always" or "never".
    ``tv_host`` is the TV's address, used to open the app on the TV when a
    link is shared; leave it unset to open the app by hand.
    ``tv_dir`` is the TV app's folder, served at /tv/ for trying it in a browser.
    """

    host: str = "0.0.0.0"
    port: int = 8090
    relay: str = "auto"
    tv_host: str | None = None
    tv_app_id: str = DEFAULT_APP_ID
    state_dir: Path = Path("state")
    resolve_timeout: float = 60.0
    tv_dir: Path | None = field(default_factory=_default_tv_dir)

    def __post_init__(self) -> None:
        if self.relay not in RELAY_MODES:
            raise ValueError(f"relay must be one of {', '.join(RELAY_MODES)}")

    @property
    def token_file(self) -> Path:
        """Where the TV's remote-control token is kept."""
        return self.state_dir / "tv-token.txt"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] = os.environ) -> "Settings":
        """Build settings from FRAMECAST_* environment variables, using defaults for the rest."""
        settings = cls()
        if "FRAMECAST_HOST" in environ:
            settings.host = environ["FRAMECAST_HOST"]
        if "FRAMECAST_PORT" in environ:
            settings.port = int(environ["FRAMECAST_PORT"])
        if "FRAMECAST_RELAY" in environ:
            settings.relay = environ["FRAMECAST_RELAY"]
        if environ.get("FRAMECAST_TV_HOST"):
            settings.tv_host = environ["FRAMECAST_TV_HOST"]
        if environ.get("FRAMECAST_TV_APP_ID"):
            settings.tv_app_id = environ["FRAMECAST_TV_APP_ID"]
        if "FRAMECAST_STATE_DIR" in environ:
            settings.state_dir = Path(environ["FRAMECAST_STATE_DIR"])
        settings.__post_init__()
        return settings
