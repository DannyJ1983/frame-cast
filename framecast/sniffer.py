"""Find the video on pages whose player is built by JavaScript.

yt-dlp only understands sites it has been taught about. Many live TV pages load
their player with JavaScript after the page arrives, so the stream address never
appears in the page itself. For those, the hub opens the page in a hidden
Chromium, lets the player start, and notes the stream it asks for: an HLS or
DASH manifest, or failing that a video file. Requests to ad servers are ignored,
and embedded players from other sites (YouTube and the like) are passed back to
yt-dlp.

On the Pi this uses the system Chromium (``apt install chromium``) through
Playwright. Without either, the hub still works; it just can't read these pages.
"""

from __future__ import annotations

import importlib.util
import logging
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import httpx

from .resolver import Stream

log = logging.getLogger(__name__)

BROWSER_NAMES = ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable")
WAIT_SECONDS = 25.0  # How long to wait, once the page has loaded, for the player to ask for a stream.
CLICK_AFTER_SECONDS = 3.0  # If nothing has started by then, try pressing play.
CLICK_AGAIN_AFTER_SECONDS = 10.0  # Then try clicking the middle of the page, where players sit.
LOAD_TIMEOUT_MS = 20000
MAX_PEEKS = 60  # Responses whose content is checked for a playlist or stream addresses.
MAX_PEEK_BYTES = 2_000_000
MAX_LOG_LINES = 400

# Requests to these hosts (and their subdomains) are ads or tracking, never the programme.
AD_HOSTS = (
    "doubleclick.net", "googlesyndication.com", "googleadservices.com", "imasdk.googleapis.com",
    "google-analytics.com", "googletagmanager.com", "adnxs.com", "adsrvr.org", "amazon-adsystem.com",
    "springserve.com", "spotxchange.com", "freewheel.tv", "fwmrm.net", "innovid.com", "moatads.com",
    "pubmatic.com", "rubiconproject.com", "teads.tv", "taboola.com", "outbrain.com", "scorecardresearch.com",
)
# Video hosts whose files can't be played on their own (YouTube's are split and signed).
# Embedded YouTube players are handed to yt-dlp instead.
SKIP_HOSTS = ("googlevideo.com", "gvt1.com")
# Common play buttons, tried in order when a player waits for a press. Labels must start
# with "play": a plain "contains" match would also hit buttons like "Display settings".
PLAY_SELECTORS = (
    ".vjs-big-play-button", ".jw-icon-display", ".plyr__control--overlaid", ".fp-play",
    "button[aria-label^='play' i]", "[role='button'][aria-label^='play' i]", "button[title^='play' i]",
    "[class*='play-button' i]", "[class*='playbutton' i]", "[class*='play_button' i]",
    "[class*='play-icon' i]", "video",
)
_STREAM_URL = re.compile(r"""https?://[^\s"'<>\\]+?\.(?:m3u8|mpd)(?:\?[^\s"'<>\\]*)?""", re.IGNORECASE)
_PEEK_TYPES = ("text/", "json", "octet-stream", "javascript", "xml")
_LOGGED_TYPES_SKIPPED = {"image", "font", "stylesheet"}
_YOUTUBE_EMBED = re.compile(r"^https?://(?:www\.)?youtube(?:-nocookie)?\.com/embed/([\w-]{6,})")
_OTHER_EMBEDS = (
    re.compile(r"^https?://player\.vimeo\.com/video/\d+"),
    re.compile(r"^https?://(?:www\.)?dailymotion\.com/embed/video/\w+"),
    re.compile(r"^https?://player\.twitch\.tv/"),
)
# Request headers worth copying when the TV (or the relay) fetches the stream.
_KEPT_HEADERS = ("user-agent", "referer", "origin", "authorization")


@dataclass
class Captured:
    """A stream request the page's player made, with the headers it sent."""

    url: str
    kind: str
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class SniffResult:
    """What a page asked for while it loaded.

    ``media`` are streams the player actually requested. ``mentioned`` are stream
    addresses found in the page's own data (a channel list, say) that the player
    didn't get round to requesting. ``log`` lists the page's requests, for
    working out why a page didn't give up its video.
    """

    title: str = ""
    media: list[Captured] = field(default_factory=list)
    mentioned: list[str] = field(default_factory=list)
    embeds: list[str] = field(default_factory=list)
    cookies: dict[str, str] = field(default_factory=dict)  # url -> Cookie header for that url
    log: list[str] = field(default_factory=list)


def media_kind(url: str, content_type: str = "") -> str | None:
    """Say whether a request looks like a stream: "hls", "dash", "file" or None."""
    path = urlsplit(url).path.lower()
    ctype = content_type.lower()
    if path.endswith((".m3u8", ".m3u")) or "mpegurl" in ctype:
        return "hls"
    if path.endswith(".mpd") or "dash+xml" in ctype:
        return "dash"
    if path.endswith((".ts", ".m4s", ".aac", ".m4a")) or "mp2t" in ctype:
        return None  # pieces of a stream, not something to play on its own
    if path.endswith((".mp4", ".m4v", ".mov", ".webm")) or ctype.startswith("video/"):
        return "file"
    return None


def _host_in(url: str, hosts: tuple[str, ...]) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in hosts)


def is_ad(url: str) -> bool:
    """True if the request goes to a known ad or tracking host."""
    return _host_in(url, AD_HOSTS)


def _ignored(url: str) -> bool:
    return is_ad(url) or _host_in(url, SKIP_HOSTS)


def mentions_stream(url: str) -> bool:
    """True if a stream address appears anywhere in ``url``, such as a proxy's query string."""
    lowered = unquote(url).lower()
    return ".m3u8" in lowered or ".mpd" in lowered


def channel_hint(page_url: str) -> str | None:
    """The last part of a page address if it looks like an ID, to match up with a channel list."""
    segment = urlsplit(page_url).path.rstrip("/").rsplit("/", 1)[-1]
    return segment if len(segment) >= 6 and re.fullmatch(r"[\w-]+", segment) else None


def find_stream_urls(text: str, hint: str | None = None) -> list[str]:
    """Stream addresses written in ``text`` (JSON or HTML), best match first.

    With a ``hint`` (a channel ID from the page address) only addresses near a
    mention of it count, nearest first. Without one, an address is only trusted
    if it's the only one, since a list of many channels says nothing about which.
    """
    text = text.replace("\\/", "/").replace("\\u002F", "/").replace("\\u002f", "/")
    found = [(m.start(), m.group(0)) for m in _STREAM_URL.finditer(text)]
    if not found:
        return []
    if hint and hint in text:
        ranked: dict[str, int] = {}
        for spot in (m.start() for m in re.finditer(re.escape(hint), text)):
            for position, url in found:
                distance = abs(position - spot)
                if distance <= 3000 and distance < ranked.get(url, 10**9):
                    ranked[url] = distance
        return sorted(ranked, key=ranked.get)
    distinct = list(dict.fromkeys(url for _, url in found))
    return distinct if len(distinct) == 1 else []


def embed_url(url: str) -> str | None:
    """If ``url`` is another site's embedded player, return an address yt-dlp understands."""
    match = _YOUTUBE_EMBED.match(url)
    if match:
        return f"https://www.youtube.com/watch?v={match.group(1)}"
    if any(pattern.match(url) for pattern in _OTHER_EMBEDS):
        return url
    return None


def pick(result: SniffResult) -> Captured | None:
    """Choose the stream to play.

    The player's own requests come first: a manifest, preferring HLS, else a video
    file. Failing those, a stream address found in the page's data.
    """
    for kind in ("hls", "dash", "file"):
        for captured in result.media:
            if captured.kind == kind and not _ignored(captured.url):
                return captured
    for url in result.mentioned:
        kind = media_kind(url) or ("dash" if ".mpd" in url.lower() else "hls")
        if not _ignored(url):
            return Captured(url, kind)
    return None


def can_fetch_directly(
    url: str, kind: str, user_agent: str | None, transport: httpx.BaseTransport | None = None
) -> bool:
    """Check whether the stream loads without the page's Referer, Origin or cookies.

    If it does, the TV can fetch it itself; if not, the hub relays it.
    """
    headers = {"User-Agent": user_agent} if user_agent else {}
    try:
        with httpx.Client(follow_redirects=True, timeout=8.0, transport=transport) as client:
            with client.stream("GET", url, headers=headers) as response:
                if response.status_code >= 400:
                    return False
                if kind == "hls":
                    first = next(response.iter_bytes(), b"")
                    return first.lstrip().startswith(b"#EXTM3U")
                return True
    except httpx.HTTPError as err:
        log.info("Direct check of %s failed: %s", url, err)
        return False


def to_stream(
    captured: Captured,
    result: SniffResult,
    page_url: str,
    transport: httpx.BaseTransport | None = None,
) -> Stream:
    """Turn a captured request into a Stream, keeping the page's headers only if they're needed."""
    headers = {name: value for name, value in captured.headers.items() if name.lower() in _KEPT_HEADERS}
    if not any(name.lower() == "referer" for name in headers):
        headers["Referer"] = page_url
    cookie = result.cookies.get(captured.url, "")
    if cookie:
        headers["Cookie"] = cookie
    user_agent = next((v for k, v in headers.items() if k.lower() == "user-agent"), None)
    if can_fetch_directly(captured.url, captured.kind, user_agent, transport):
        headers = {"User-Agent": user_agent} if user_agent else {}
    else:
        log.info("Stream needs the page's headers, so it will be relayed")
    title = result.title.strip() or urlsplit(page_url).hostname or "Video"
    return Stream(url=captured.url, title=title, kind=captured.kind, page_url=page_url, headers=headers)


def _chrome_user_agent(version: str) -> str:
    """A normal desktop Chrome user agent: some sites turn away "HeadlessChrome"."""
    major = version.split(".", 1)[0] or "140"
    return f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36"


class PageSniffer:
    """Loads pages in a hidden Chromium and records the streams their players request."""

    def __init__(self, browser_path: str, wait_seconds: float = WAIT_SECONDS) -> None:
        self.browser_path = browser_path
        self.wait_seconds = wait_seconds

    @staticmethod
    def find_browser() -> str | None:
        """Return the path of an installed Chromium, if there is one."""
        for name in BROWSER_NAMES:
            path = shutil.which(name)
            if path:
                return path
        return None

    @classmethod
    def from_setting(cls, browser: str) -> "PageSniffer | None":
        """Build a sniffer from the FRAMECAST_BROWSER setting: "auto", "off" or a path."""
        if browser == "off":
            return None
        if importlib.util.find_spec("playwright") is None:
            log.info("Playwright isn't installed, so pages built by JavaScript can't be read")
            return None
        path = cls.find_browser() if browser == "auto" else browser
        if not path or not Path(path).exists():
            log.info("No Chromium found, so pages built by JavaScript can't be read")
            return None
        return cls(path)

    def sniff(self, page_url: str) -> SniffResult:
        """Open ``page_url``, wait for its player, and return what it asked for. Blocking."""
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright

        result = SniffResult()
        seen: set[str] = set()
        peeks: list[Any] = []  # responses whose content is worth a look afterwards

        def note(url: str, kind: str | None, headers: dict[str, str]) -> None:
            if kind and url not in seen and not _ignored(url):
                seen.add(url)
                result.media.append(Captured(url, kind, dict(headers)))
                log.info("Page asked for a %s stream: %s", kind, url)

        def note_embed(url: str) -> None:
            embed = embed_url(url)
            if embed and embed not in result.embeds:
                result.embeds.append(embed)
                log.info("Page embeds another site's player: %s", embed)

        def record(line: str) -> None:
            if len(result.log) < MAX_LOG_LINES:
                result.log.append(line)
            log.debug("Browser: %s", line)

        def on_request(request: Any) -> None:
            note(request.url, media_kind(request.url), request.headers)
            if request.resource_type == "document":
                note_embed(request.url)

        def on_response(response: Any) -> None:
            request = response.request
            ctype = response.headers.get("content-type", "").split(";")[0].strip().lower()
            kind = media_kind(response.url, ctype)
            note(response.url, kind, request.headers)
            if request.resource_type not in _LOGGED_TYPES_SKIPPED:
                record(f"{response.status} {request.resource_type:<9} {ctype or '-':<32} {response.url[:200]}")
            worth_a_look = (
                kind is None
                and not _ignored(response.url)
                and request.resource_type in ("xhr", "fetch", "document", "script", "other")
                and (mentions_stream(response.url) or not ctype or any(t in ctype for t in _PEEK_TYPES))
            )
            if worth_a_look and len(peeks) < MAX_PEEKS:
                peeks.append(response)

        def on_failed(request: Any) -> None:
            if request.resource_type not in _LOGGED_TYPES_SKIPPED:
                record(f"FAILED {request.resource_type:<9} {request.failure or ''} {request.url[:200]}")

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                executable_path=self.browser_path,
                headless=True,
                args=["--autoplay-policy=no-user-gesture-required", "--mute-audio"],
            )
            try:
                context = browser.new_context(
                    user_agent=_chrome_user_agent(browser.version),
                    viewport={"width": 1280, "height": 720},
                )
                # Listen on the whole context so requests from popups and workers count too.
                context.on("request", on_request)
                context.on("response", on_response)
                context.on("requestfailed", on_failed)
                page = context.new_page()
                try:
                    page.goto(page_url, wait_until="domcontentloaded", timeout=LOAD_TIMEOUT_MS)
                except PlaywrightError as err:
                    log.info("Page didn't finish loading (%s); carrying on", err.message.splitlines()[0])
                self._wait_for_player(page, result)
                result.title = self._title(page)
                for frame in page.frames:
                    note_embed(frame.url)
                try:
                    for src in page.eval_on_selector_all("iframe[src]", "els => els.map(e => e.src)"):
                        note_embed(src)
                except PlaywrightError:
                    pass
                if not any(m.kind in ("hls", "dash") for m in result.media):
                    self._look_inside(peeks, result, note, channel_hint(page_url))
                for captured in result.media:
                    cookies = context.cookies([captured.url])
                    if cookies:
                        result.cookies[captured.url] = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
            finally:
                browser.close()
        return result

    def _wait_for_player(self, page: Any, result: SniffResult) -> None:
        """Wait for a manifest request, pressing play along the way if nothing starts."""
        started = time.monotonic()
        pressed = clicked_middle = False
        while time.monotonic() - started < self.wait_seconds:
            elapsed = time.monotonic() - started
            if any(m.kind in ("hls", "dash") for m in result.media):
                return
            if result.embeds and elapsed > CLICK_AFTER_SECONDS + 2:
                return  # an embedded player from a site yt-dlp knows; no need to wait longer
            if not pressed and elapsed > CLICK_AFTER_SECONDS:
                self._press_play(page)
                pressed = True
            if not clicked_middle and elapsed > CLICK_AGAIN_AFTER_SECONDS:
                try:
                    page.mouse.click(640, 300)
                    log.info("Clicked the middle of the page")
                except Exception:
                    pass
                clicked_middle = True
            page.wait_for_timeout(250)

    @staticmethod
    def _look_inside(peeks: list[Any], result: SniffResult, note: Any, hint: str | None) -> None:
        """Check downloaded files for a playlist served under an odd name, or stream addresses in data."""
        order = {"xhr": 0, "fetch": 0, "document": 1, "other": 2, "script": 3}
        for response in sorted(peeks, key=lambda r: order.get(r.request.resource_type, 4)):
            try:
                body = response.body()
            except Exception:  # redirects and cancelled requests have no body
                continue
            if not body or len(body) > MAX_PEEK_BYTES:
                continue
            head = body[:300].lstrip()
            if head.startswith(b"#EXTM3U"):
                note(response.url, "hls", response.request.headers)
                continue
            if b"<MPD" in head:
                note(response.url, "dash", response.request.headers)
                continue
            for url in find_stream_urls(body.decode("utf-8", errors="replace"), hint):
                if url not in result.mentioned:
                    result.mentioned.append(url)
                    log.info("Page's data mentions a stream: %s", url)

    @staticmethod
    def _title(page: Any) -> str:
        try:
            og = page.query_selector("meta[property='og:title']")
            if og and og.get_attribute("content"):
                return str(og.get_attribute("content"))
            return str(page.title())
        except Exception:  # the page may have navigated away or crashed
            return ""

    @staticmethod
    def _press_play(page: Any) -> None:
        """Try the usual play buttons, then ask any video elements to play (muted)."""
        for selector in PLAY_SELECTORS:
            try:
                element = page.query_selector(selector)
                if element and element.is_visible():
                    element.click(timeout=1500)
                    log.info("Pressed play (%s)", selector)
                    break
            except Exception:  # hidden, covered or detached; try the next one
                continue
        try:
            page.evaluate(
                "document.querySelectorAll('video').forEach(v => { v.muted = true; const p = v.play && v.play(); if (p) p.catch(() => {}); })"
            )
        except Exception:
            pass
