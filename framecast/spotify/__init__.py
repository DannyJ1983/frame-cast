"""Spotify "now playing": what's playing on one Spotify Connect device, and what's queued next.

The Pi signs in to your own Spotify developer app (authorisation code with
PKCE, so no client secret), keeps the refresh token in the state folder, and
reads the player and queue from the Web API while a screen is showing them.
"""

from .service import NowPlaying
from .store import SpotifyStore

__all__ = ["NowPlaying", "SpotifyStore"]
