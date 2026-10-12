"""Turn a webpage address into a video stream the TV's player can open.

yt-dlp does the finding. This module picks, from everything yt-dlp found, the
one stream that suits Samsung's AVPlay player best, and notes any headers or
cookies the stream needs so the hub can decide whether to relay it.
"""

from __future__ import annotations

import http.cookiejar
import logging
import re
import urllib.request
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from .sniffer import PageSniffer

log = logging.getLogger(__name__)

HLS_PROTOCOLS = {"m3u8", "m3u8_native"}
DASH_PROTOCOLS = {"http_dash_segments", "http_dash_segments_generator"}
FILE_PROTOCOLS = {"http", "https"}
# Containers AVPlay opens, best first.
FILE_EXTS = ["mp4", "m4v", "mov", "ts", "mkv", "webm"]
MAX_HEIGHT = 2160

# Headers yt-dlp adds to every request that the TV doesn't need to copy.
_GENERIC_HEADERS = {"accept", "accept-language", "sec-fetch-mode", "accept-encoding"}
# Headers the TV's player can't send itself, so the hub has to relay the stream.
_RELAY_HEADERS = {"referer", "origin", "cookie", "authorization"}

COPY_PROTECTED = "That video is copy-protected, so it can't be played on the TV."
NO_VIDEO = "Couldn't find a video on that page."
SIGNED_IN = "That video needs you to be signed in, which Frame Cast can't do."
NOT_HERE = "That video isn't available from here."
NOT_FOUND = "That page couldn't be found."
CANT_CONNECT = "Couldn't connect to that site from the home server. It may be down, or blocked on your broadband."
# Answers a hidden browser on the same connection can't change, so it isn't tried after them.
FINAL_ERRORS = {COPY_PROTECTED, SIGNED_IN, NOT_HERE}


class ResolveError(Exception):
    """A stream couldn't be found. The message is written for the person sharing."""


@dataclass
class Stream:
    """A stream picked for the TV.

    ``kind`` is "hls", "dash" or "file". ``headers`` are the request headers the
    stream needs, minus the generic ones. ``cookies`` is the jar yt-dlp filled
    while looking, kept so the relay can send the same cookies.
    """

    url: str
    title: str
    kind: str
    page_url: str
    is_live: bool = False
    headers: dict[str, str] = field(default_factory=dict)
    cookies: http.cookiejar.CookieJar | None = field(default=None, repr=False, compare=False)

    @property
    def user_agent(self) -> str | None:
        """The User-Agent the stream expects, if yt-dlp named one."""
        return _get_header(self.headers, "user-agent")

    def cookie_header(self, url: str | None = None) -> str:
        """Return the Cookie header the jar would send for ``url`` (default: the stream)."""
        if self.cookies is None:
            return ""
        request = urllib.request.Request(url or self.url)
        self.cookies.add_cookie_header(request)
        return request.get_header("Cookie") or ""

    @property
    def needs_relay(self) -> bool:
        """True if the TV can't fetch this stream directly.

        The TV's player can set a User-Agent but not a Referer, Origin, cookies
        or other custom headers. Streams that need those go through the hub.
        """
        for name in self.headers:
            lower = name.lower()
            if lower in _RELAY_HEADERS or lower.startswith("x-"):
                return True
        return bool(self.cookie_header())


def _get_header(headers: dict[str, str], name: str) -> str | None:
    for key, value in headers.items():
        if key.lower() == name:
            return value
    return None


def _has_drm(fmt: dict[str, Any]) -> bool:
    return bool(fmt.get("has_drm")) and fmt.get("has_drm") != "maybe"


def _height(fmt: dict[str, Any]) -> int:
    height = fmt.get("height") or 0
    return height if height <= MAX_HEIGHT else 0


def _has_audio_and_video(fmt: dict[str, Any]) -> bool:
    # yt-dlp says "none" when a stream definitely lacks a track; missing means unknown.
    return fmt.get("vcodec") != "none" and fmt.get("acodec") != "none"


def _file_rank(fmt: dict[str, Any]) -> tuple[int, int, float]:
    ext = fmt.get("ext") or ""
    ext_rank = len(FILE_EXTS) - FILE_EXTS.index(ext) if ext in FILE_EXTS else 0
    return (ext_rank, _height(fmt), float(fmt.get("tbr") or 0))


def _relevant_headers(headers: dict[str, str] | None) -> dict[str, str]:
    return {k: v for k, v in (headers or {}).items() if k.lower() not in _GENERIC_HEADERS}


def choose_stream(
    info: dict[str, Any],
    page_url: str,
    cookies: http.cookiejar.CookieJar | None = None,
) -> Stream:
    """Pick the stream from a yt-dlp info dict that the TV is most likely to play.

    Order of preference: an HLS manifest (adaptive, and how most live streams
    arrive), then a single file with both sound and picture, then a DASH
    manifest. Copy-protected formats are skipped.

    Raises ResolveError if nothing suitable is found.
    """
    if info.get("_type") in ("playlist", "multi_video"):
        entries = [e for e in info.get("entries") or [] if e]
        if not entries:
            raise ResolveError(NO_VIDEO)
        info = entries[0]

    formats = info.get("formats") or ([info] if info.get("url") else [])
    usable = [f for f in formats if f.get("url") and not _has_drm(f)]
    if not usable:
        if formats and all(_has_drm(f) for f in formats):
            raise ResolveError(COPY_PROTECTED)
        raise ResolveError(NO_VIDEO)

    title = info.get("title") or info.get("webpage_url_basename") or "Video"
    is_live = bool(info.get("is_live")) or info.get("live_status") == "is_live"

    def make(fmt: dict[str, Any], url: str, kind: str) -> Stream:
        stream = Stream(
            url=url,
            title=title,
            kind=kind,
            page_url=page_url,
            is_live=is_live,
            headers=_relevant_headers(fmt.get("http_headers")),
            cookies=cookies,
        )
        log.info("Picked %s stream (format %s) for %s", kind, fmt.get("format_id"), page_url)
        return stream

    hls = [f for f in usable if f.get("protocol") in HLS_PROTOCOLS]
    if hls:
        best = max(hls, key=lambda f: (bool(f.get("manifest_url")), _height(f), float(f.get("tbr") or 0)))
        return make(best, best.get("manifest_url") or best["url"], "hls")

    files = [
        f
        for f in usable
        if (f.get("protocol") or "https") in FILE_PROTOCOLS and _has_audio_and_video(f)
    ]
    if files:
        best = max(files, key=_file_rank)
        return make(best, best["url"], "file")

    dash = [f for f in usable if f.get("protocol") in DASH_PROTOCOLS and f.get("manifest_url")]
    if dash:
        best = max(dash, key=_height)
        return make(best, best["manifest_url"], "dash")

    raise ResolveError("Found a video on that page, but not in a form the TV can play.")


_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def explain_error(message: str) -> str:
    """Turn a yt-dlp error into a short message for the person sharing."""
    text = _ANSI.sub("", message or "").strip()
    text = re.sub(r"^ERROR:\s*", "", text)
    lower = text.lower()
    if "drm" in lower:
        return COPY_PROTECTED
    if "unsupported url" in lower or "no video formats" in lower or "no video could be found" in lower:
        return NO_VIDEO
    if "sign in" in lower or "login" in lower or "log in" in lower or "private video" in lower:
        return SIGNED_IN
    if ("geo" in lower and "restrict" in lower) or "in your country" in lower:
        return NOT_HERE
    if "http error 404" in lower:
        return NOT_FOUND
    if any(s in lower for s in ("ssl", "unable to download webpage", "connection", "timed out", "name or service not known", "getaddrinfo")):
        return CANT_CONNECT
    first_line = text.splitlines()[0] if text else "unknown error"
    return f"Couldn't get the video: {first_line[:200]}"


Extractor = Callable[[str], "tuple[dict[str, Any], http.cookiejar.CookieJar | None]"]


def ytdlp_extract(url: str) -> tuple[dict[str, Any], http.cookiejar.CookieJar | None]:
    """Run yt-dlp on ``url`` without downloading, returning its info dict and cookie jar."""
    import yt_dlp

    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "socket_timeout": 15,
        "logger": logging.getLogger("yt_dlp"),
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
        except yt_dlp.utils.DownloadError as err:
            raise ResolveError(explain_error(str(err))) from err
        return info or {}, ydl.cookiejar


class Resolver:
    """Finds the stream on a page. Blocking: call it from a worker thread.

    yt-dlp goes first. If it finds nothing and a ``sniffer`` is given, the page
    is opened in a hidden browser to catch the stream its player asks for.
    """

    def __init__(self, extractor: Extractor = ytdlp_extract, sniffer: "PageSniffer | None" = None) -> None:
        self._extract = extractor
        self._sniffer = sniffer

    def resolve(self, page_url: str) -> Stream:
        """Return the best stream on ``page_url``, or raise ResolveError."""
        log.info("Looking for a video on %s", page_url)
        try:
            return self._with_ytdlp(page_url, page_url)
        except ResolveError as err:
            # Sites often turn yt-dlp away (or confuse it) but still play in a real browser.
            if self._sniffer is None or str(err) in FINAL_ERRORS:
                raise
            return self._with_browser(page_url, err)

    def _with_ytdlp(self, url: str, page_url: str) -> Stream:
        try:
            info, cookies = self._extract(url)
        except ResolveError:
            raise
        except Exception as err:  # yt-dlp can raise almost anything on odd pages
            log.exception("yt-dlp failed on %s", url)
            raise ResolveError(explain_error(str(err))) from err
        return choose_stream(info, page_url, cookies)

    def _with_browser(self, page_url: str, original: ResolveError) -> Stream:
        from .sniffer import pick, to_stream

        assert self._sniffer is not None
        log.info("yt-dlp couldn't help (%s); opening %s in a hidden browser", original, page_url)
        try:
            result = self._sniffer.sniff(page_url)
        except Exception:  # a browser that won't start shouldn't hide yt-dlp's answer
            log.exception("The hidden browser failed on %s", page_url)
            raise original
        captured = pick(result)
        if captured is not None:
            return to_stream(captured, result, page_url)
        error = original
        for embed in result.embeds:
            log.info("Page embeds %s; trying yt-dlp on it", embed)
            try:
                return self._with_ytdlp(embed, page_url)
            except ResolveError as err:
                error = err
        if error is original and _page_loaded(result.log):
            raise ResolveError(NO_VIDEO)  # the page opened fine, so yt-dlp's complaint was beside the point
        raise error


def _page_loaded(browser_log: list[str]) -> bool:
    """True if the hidden browser's log shows a page that loaded (status 2xx or 3xx)."""
    return any(" document " in line and line[:1] in ("2", "3") for line in browser_log)
