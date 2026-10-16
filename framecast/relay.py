"""Relay streams the TV can't fetch on its own.

Some sites only hand out video to requests that carry a Referer, cookies or
other headers. The TV's player can't add those, so the hub fetches the stream
on the TV's behalf and adds them.

Relay addresses look like ``/p/<session>/<signature>/<folder>/<file>?<query>``.
``folder`` is the base64 of the upstream folder address and ``signature`` is an
HMAC over the session and folder, so the relay only fetches from folders it
handed out itself rather than acting as an open proxy. Anything under a signed
folder is allowed, which lets players resolve relative segment addresses (as
DASH manifests use) without any rewriting. HLS playlists are rewritten so every
address in them, absolute or relative, goes through the relay too.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import http.cookiejar
import logging
import re
import secrets
import time
import urllib.request
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import AsyncIterator, Callable
from urllib.parse import urljoin, urlsplit

import httpx
from starlette.background import BackgroundTask
from starlette.responses import PlainTextResponse, Response, StreamingResponse

log = logging.getLogger(__name__)

PREFIX = "/p/"
MAX_PLAYLIST_BYTES = 10 * 1024 * 1024
_PASS_HEADERS = ("content-type", "content-range", "accept-ranges", "last-modified", "etag")
_URI_ATTR = re.compile(r'URI="([^"]*)"')
_PLAYLIST_TYPES = ("mpegurl",)
_MEDIA_TYPE_PREFIXES = ("video/", "audio/", "image/")


@dataclass
class RelaySession:
    """Headers and cookies to send upstream for one shared stream."""

    headers: dict[str, str]
    cookies: http.cookiejar.CookieJar | None = None
    created: float = field(default_factory=time.time)
    # True when only the master playlist comes through the hub (to put the best quality first);
    # the TV then fetches everything else straight from the site.
    direct_segments: bool = False
    # The original audio language, so dubbed tracks can be left out of the master playlist.
    audio_language: str | None = None

    def upstream_headers(self, url: str, range_header: str | None) -> dict[str, str]:
        """Build the request headers for fetching ``url`` upstream."""
        headers = dict(self.headers)
        headers["Accept-Encoding"] = "identity"
        if self.cookies is not None:
            request = urllib.request.Request(url)
            self.cookies.add_cookie_header(request)
            cookie = request.get_header("Cookie")
            if cookie:
                headers["Cookie"] = cookie
        if range_header:
            headers["Range"] = range_header
        return headers


def _b64encode(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).rstrip(b"=").decode()


def _b64decode(text: str) -> str | None:
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4)).decode()
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None


def split_url(url: str) -> tuple[str, str, str]:
    """Split ``url`` into (folder, file, query); the folder ends with "/"."""
    parts = urlsplit(url)
    path = parts.path or "/"
    cut = path.rfind("/") + 1
    folder = f"{parts.scheme}://{parts.netloc}{path[:cut]}"
    return folder, path[cut:], parts.query


def rewrite_playlist(text: str, base_url: str, to_relay: Callable[[str], str]) -> str:
    """Point every address in an HLS playlist at the relay.

    Covers segment and variant lines and ``URI="..."`` attributes (keys, init
    sections, alternative renditions). Addresses that aren't http(s), such as
    ``skd://`` key identifiers or ``data:`` URIs, are left alone.
    """

    def relay(uri: str) -> str:
        absolute = urljoin(base_url, uri.strip())
        if urlsplit(absolute).scheme not in ("http", "https"):
            return uri
        return to_relay(absolute)

    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append(line)
        elif stripped.startswith("#"):
            lines.append(_URI_ATTR.sub(lambda m: f'URI="{relay(m.group(1))}"', line))
        else:
            lines.append(relay(stripped))
    return "\n".join(lines) + "\n"


_STREAM_INF = "#EXT-X-STREAM-INF"
_MEDIA = "#EXT-X-MEDIA:"
MAX_VARIANT_HEIGHT = 2160  # The Frame decodes up to 4K.
UNSUPPORTED_CODECS = ("av01",)  # 2019 Samsung TVs have no AV1 decoder.


def _attribute(tag_line: str, name: str) -> str:
    match = re.search(rf'(?:[:,]){name}=("[^"]*"|[^,]*)', tag_line)
    return match.group(1).strip('"') if match else ""


def _variant_height(tag_line: str) -> int:
    resolution = _attribute(tag_line, "RESOLUTION")
    try:
        return int(resolution.lower().split("x")[1])
    except (IndexError, ValueError):
        return 0


def _variant_bandwidth(tag_line: str) -> int:
    try:
        return int(_attribute(tag_line, "BANDWIDTH"))
    except ValueError:
        return 0


def _same_language(code: str, wanted: str) -> bool:
    """Compare language codes by their main part: "en-GB" and "en.4" both match "en"."""

    def main(c: str) -> str:
        return c.strip().lower().replace("_", "-").split("-")[0].split(".")[0]

    return bool(code) and main(code) == main(wanted)


def _choose_audio_renditions(lines: list[str], language: str) -> list[str]:
    """In each audio group, keep just the best rendition for ``language`` and make it the default."""
    groups: dict[str, list[int]] = {}
    for index, line in enumerate(lines):
        if line.startswith(_MEDIA) and _attribute(line, "TYPE") == "AUDIO":
            groups.setdefault(_attribute(line, "GROUP-ID"), []).append(index)

    def score(line: str) -> int:
        label = (_attribute(line, "NAME") + " " + _attribute(line, "URI")).lower()
        value = 100 if _same_language(_attribute(line, "LANGUAGE"), language) else 0
        value += 20 if "original" in label else 0
        value += 10 if _attribute(line, "DEFAULT") == "YES" else 0
        value -= 50 if "dub" in label else 0
        value -= 30 if "descripti" in label else 0
        return value

    drop: set[int] = set()
    for indexes in groups.values():
        if len(indexes) < 2:
            continue
        best = max(indexes, key=lambda i: score(lines[i]))
        drop.update(i for i in indexes if i != best)
        line = re.sub(r",?DEFAULT=(YES|NO)", "", lines[best])
        line = re.sub(r",?AUTOSELECT=(YES|NO)", "", line).replace(":,", ":", 1)
        lines[best] = line + ",DEFAULT=YES,AUTOSELECT=YES"
    return [line for i, line in enumerate(lines) if i not in drop]


def prioritise_variants(text: str, audio_language: str | None = None) -> str:
    """Put an HLS master playlist's best quality first, dropping levels the TV can't play.

    Players commonly start with the first level listed, and many sites list the
    lowest first, so short clips never climb to full quality. Levels above 4K or
    in AV1 are dropped, unless that would leave nothing.

    With ``audio_language`` (the original language), levels and audio tracks in
    other languages are dropped too. YouTube lists every level once per audio
    language, AI dubs included, marking each with YT-EXT-AUDIO-CONTENT-ID;
    other sites use alternative audio renditions. Media playlists are returned
    unchanged.
    """
    lines = text.splitlines()
    if not any(line.startswith(_STREAM_INF) for line in lines):
        return text
    if audio_language:
        lines = _choose_audio_renditions(lines, audio_language)
    others: list[str] = []
    variants: list[tuple[str, str]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith(_STREAM_INF):
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            variants.append((line, lines[j] if j < len(lines) else ""))
            i = j + 1
        else:
            others.append(line)
            i += 1
    playable = [
        v for v in variants
        if _variant_height(v[0]) <= MAX_VARIANT_HEIGHT
        and not any(c in _attribute(v[0], "CODECS").lower() for c in UNSUPPORTED_CODECS)
    ] or variants
    if audio_language:
        in_language = [
            v for v in playable
            if not _attribute(v[0], "YT-EXT-AUDIO-CONTENT-ID")
            or _same_language(_attribute(v[0], "YT-EXT-AUDIO-CONTENT-ID"), audio_language)
        ]
        playable = in_language or playable
    playable.sort(key=lambda v: (_variant_bandwidth(v[0]), _variant_height(v[0])), reverse=True)
    while others and not others[-1].strip():
        others.pop()
    return "\n".join(others + [part for v in playable for part in v]) + "\n"


def _looks_like_playlist_name(url: str) -> bool:
    path = urlsplit(url).path.lower()
    return path.endswith(".m3u8") or path.endswith(".m3u")


class Relay:
    """Hands out signed relay addresses and serves them."""

    def __init__(
        self,
        secret: bytes | None = None,
        max_sessions: int = 20,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._secret = secret or secrets.token_bytes(32)
        self._transport = transport
        self._max_sessions = max_sessions
        self._sessions: OrderedDict[str, RelaySession] = OrderedDict()
        self._client: httpx.AsyncClient | None = None

    # Addresses -----------------------------------------------------------------

    def open_session(
        self,
        headers: dict[str, str],
        cookies: http.cookiejar.CookieJar | None = None,
        direct_segments: bool = False,
        audio_language: str | None = None,
    ) -> str:
        """Start a relay session for one stream and return its id.

        With ``direct_segments`` only the master playlist is passed through (best
        quality first); everything it points to is fetched by the TV directly.
        """
        session_id = secrets.token_urlsafe(8)
        self._sessions[session_id] = RelaySession(
            dict(headers), cookies, direct_segments=direct_segments, audio_language=audio_language
        )
        while len(self._sessions) > self._max_sessions:
            self._sessions.popitem(last=False)
        return session_id

    def session(self, session_id: str) -> RelaySession | None:
        """Return the session with this id, if it's still kept."""
        return self._sessions.get(session_id)

    def _sign(self, session_id: str, folder: str) -> str:
        digest = hmac.new(self._secret, f"{session_id}\n{folder}".encode(), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest[:12]).decode()

    def path_for(self, session_id: str, url: str) -> str:
        """Return the relay path (starting "/p/") that fetches ``url`` upstream."""
        folder, name, query = split_url(url)
        path = f"{PREFIX}{session_id}/{self._sign(session_id, folder)}/{_b64encode(folder)}/{name}"
        return f"{path}?{query}" if query else path

    def target_for(self, raw_path: str, query: str) -> tuple[str, RelaySession] | None:
        """Check a relay path and return (upstream address, session), or None if invalid."""
        if not raw_path.startswith(PREFIX):
            return None
        parts = raw_path[len(PREFIX):].split("/", 3)
        if len(parts) != 4:
            return None
        session_id, signature, folder_b64, rest = parts
        session = self._sessions.get(session_id)
        folder = _b64decode(folder_b64)
        if session is None or folder is None:
            return None
        if not hmac.compare_digest(signature, self._sign(session_id, folder)):
            return None
        url = folder + rest
        return (f"{url}?{query}" if query else url), session

    # Serving -------------------------------------------------------------------

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                transport=self._transport,
                follow_redirects=True,
                timeout=httpx.Timeout(20.0, connect=10.0),
            )
        return self._client

    async def aclose(self) -> None:
        """Close the upstream HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def serve(self, raw_path: str, query: str, method: str, range_header: str | None) -> Response:
        """Fetch a relay path upstream and return the response for the TV."""
        found = self.target_for(raw_path, query)
        if found is None:
            return PlainTextResponse("Unknown or expired relay address", status_code=404)
        url, session = found
        session_id = raw_path[len(PREFIX):].split("/", 1)[0]
        headers = session.upstream_headers(url, range_header)
        client = self._http()
        try:
            request = client.build_request(method, url, headers=headers)
            upstream = await client.send(request, stream=True)
        except httpx.HTTPError as err:
            log.warning("Relay couldn't fetch %s: %s", url, err)
            return PlainTextResponse(f"Couldn't fetch the stream: {err}", status_code=502)

        if upstream.status_code >= 400:
            log.warning("Relay got HTTP %s for %s", upstream.status_code, url)

        content_type = upstream.headers.get("content-type", "").lower()
        is_media = content_type.startswith(_MEDIA_TYPE_PREFIXES) and "mpegurl" not in content_type
        if method == "HEAD":
            await upstream.aclose()
            return Response(status_code=upstream.status_code, headers=self._pass_headers(upstream))

        if any(t in content_type for t in _PLAYLIST_TYPES) or _looks_like_playlist_name(url):
            return await self._playlist_response(upstream, session_id, session)

        chunks = upstream.aiter_bytes()
        first = b""
        if not is_media:
            # Some servers label playlists text/plain or octet-stream: peek to find out.
            try:
                first = await chunks.__anext__()
            except StopAsyncIteration:
                first = b""
            if first.lstrip().startswith(b"#EXTM3U"):
                return await self._playlist_response(upstream, session_id, session, first, chunks)

        return StreamingResponse(
            _prepend(first, chunks),
            status_code=upstream.status_code,
            headers=self._pass_headers(upstream),
            background=BackgroundTask(upstream.aclose),
        )

    def _pass_headers(self, upstream: httpx.Response) -> dict[str, str]:
        headers = {k: upstream.headers[k] for k in _PASS_HEADERS if k in upstream.headers}
        # Bytes are passed on decoded, so a length is only right if nothing was encoded.
        if "content-length" in upstream.headers and "content-encoding" not in upstream.headers:
            headers["content-length"] = upstream.headers["content-length"]
        return headers

    async def _playlist_response(
        self,
        upstream: httpx.Response,
        session_id: str,
        session: RelaySession,
        first: bytes = b"",
        chunks: AsyncIterator[bytes] | None = None,
    ) -> Response:
        body = bytearray(first)
        try:
            async for chunk in chunks or upstream.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_PLAYLIST_BYTES:
                    return PlainTextResponse("Playlist too large", status_code=502)
        finally:
            await upstream.aclose()
        if upstream.status_code >= 400:
            return Response(bytes(body), status_code=upstream.status_code)
        text = prioritise_variants(
            bytes(body).decode(upstream.encoding or "utf-8", errors="replace"), session.audio_language
        )
        if session.direct_segments:
            # Addresses are made absolute (they'd otherwise resolve against the hub) but not relayed.
            rewritten = rewrite_playlist(text, str(upstream.url), lambda u: u)
        else:
            rewritten = rewrite_playlist(text, str(upstream.url), lambda u: self.path_for(session_id, u))
        return Response(
            rewritten,
            media_type="application/vnd.apple.mpegurl",
            headers={"cache-control": "no-cache"},
        )


async def _prepend(first: bytes, rest: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    if first:
        yield first
    async for chunk in rest:
        yield chunk
