"""Signing in to Spotify with the authorisation code flow and PKCE.

Spotify only accepts plain-http redirect addresses on the loopback address
(127.0.0.1), and the Pi is reached by its network address, so the redirect
usually lands on a page that doesn't load. The address it was sent to still
holds the code: the phone page asks for it to be pasted back.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from urllib.parse import parse_qs, urlencode, urlsplit

AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API_URL = "https://api.spotify.com/v1"
SCOPES = "user-read-playback-state user-read-currently-playing"
CALLBACK_PATH = "/spotify/callback"


class SpotifyError(ValueError):
    """Something went wrong with Spotify. The message is written for the person reading it."""


def redirect_uri(port: int) -> str:
    """The redirect address to register in the Spotify app: the loopback address and the hub's port."""
    return f"http://127.0.0.1:{port}{CALLBACK_PATH}"


def code_verifier() -> str:
    """A random PKCE verifier: 86 URL-safe characters (43 to 128 are allowed)."""
    return secrets.token_urlsafe(64)


def code_challenge(verifier: str) -> str:
    """The S256 challenge for a verifier: base64url of its SHA-256, without padding."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def authorize_url(client_id: str, redirect: str, challenge: str, state: str) -> str:
    """The Spotify page that asks the person to allow access."""
    return AUTHORIZE_URL + "?" + urlencode({
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
        "scope": SCOPES,
        "state": state,
    })


def code_from_redirect(text: str, expected_state: str) -> str:
    """Find the authorisation code in the address Spotify redirected to (as pasted from the browser)."""
    value = text.strip()
    query = parse_qs(urlsplit(value).query) if "?" in value else parse_qs(value)
    if query.get("error"):
        if query["error"][0] == "access_denied":
            raise SpotifyError("Spotify access wasn't allowed. Press Connect and choose Agree to try again.")
        raise SpotifyError(f"Spotify said: {query['error'][0]}.")
    code = (query.get("code") or [""])[0]
    if not code:
        raise SpotifyError("That address doesn't have a code in it. Copy the whole address from the browser after agreeing.")
    if (query.get("state") or [""])[0] != expected_state:
        raise SpotifyError("That address is from an older attempt. Press Connect again and use the new address.")
    return code
