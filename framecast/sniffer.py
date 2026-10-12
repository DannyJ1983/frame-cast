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
from urllib.parse import urlsplit

import httpx

from .resolver import Stream

log = logging.getLogger(__name__)

BROWSER_NAMES = ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable")
WAIT_SECONDS = 15.0  # How long to wait for the player to ask for a stream.
CLICK_AFTER_SECONDS = 3.0  # If nothing has started by then, try pressing play.
LOAD_TIMEOUT_MS = 20000

# Requests to these hosts (and their subdomains) are ads or tracking, never the programme.
AD_HOSTS = (
    "doubleclick.net", "googlesyndication.com", "googleadservices.com", "imasdk.googleapis.com",
    "google-analytics.com", "googletagmanager.com", "adnxs.com", "adsrvr.org", "amazon-adsystem.com",
    "springserve.com", "spotxchange.com", "freewheel.tv", "fwmrm.net", "innovid.com", "moatads.com",
    "pubmatic.com", "rubiconproject.com", "teads.tv", "taboola.com", "outbrain.com", "scorecardresearch.com",
)
# Common play buttons, tried in order when a player waits for a press.
PLAY_SELECTORS = (
    ".vjs-big-play-button", ".jw-icon-display", ".plyr__control--overlaid", ".fp-play",
    "button[aria-label*='play' i]", "[class*='play-button' i]", "[class*='playbutton' i]",
    "[class*='play_button' i]", "video",
)
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
    """What a page asked for while it loaded."""

    title: str = ""
    media: list[Captured] = field(default_factory=list)
    embeds: list[str] = field(default_factory=list)
    cookies: dict[str, str] = field(default_factory=dict)  # url -> Cookie header for that url


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


def is_ad(url: str) -> bool:
    """True if the request goes to a known ad or tracking host."""
    host = (urlsplit(url).hostname or "").lower()
    return any(host == ad or host.endswith("." + ad) for ad in AD_HOSTS)


def embed_url(url: str) -> str | None:
    """If ``url`` is another site's embedded player, return an address yt-dlp understands."""
    match = _YOUTUBE_EMBED.match(url)
    if match:
        return f"https://www.youtube.com/watch?v={match.group(1)}"
    if any(pattern.match(url) for pattern in _OTHER_EMBEDS):
        return url
    return None


def pick(result: SniffResult) -> Captured | None:
    """Choose the stream to play: the first manifest, preferring HLS, else the first video file."""
    for kind in ("hls", "dash", "file"):
        for captured in result.media:
            if captured.kind == kind and not is_ad(captured.url):
                return captured
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

        def note(url: str, kind: str | None, headers: dict[str, str]) -> None:
            if kind and url not in seen and not is_ad(url):
                seen.add(url)
                result.media.append(Captured(url, kind, dict(headers)))
                log.info("Page asked for a %s stream: %s", kind, url)

        def note_embed(url: str) -> None:
            embed = embed_url(url)
            if embed and embed not in result.embeds:
                result.embeds.append(embed)
                log.info("Page embeds another site's player: %s", embed)

        def on_request(request: Any) -> None:
            note(request.url, media_kind(request.url), request.headers)
            if request.resource_type == "document":
                note_embed(request.url)

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
                page = context.new_page()
                page.on("request", on_request)
                page.on(
                    "response",
                    lambda r: note(r.url, media_kind(r.url, r.headers.get("content-type", "")), r.request.headers),
                )
                started = time.monotonic()
                try:
                    page.goto(page_url, wait_until="domcontentloaded", timeout=LOAD_TIMEOUT_MS)
                except PlaywrightError as err:
                    log.info("Page didn't finish loading (%s); carrying on", err.message.splitlines()[0])
                clicked = False
                while time.monotonic() - started < self.wait_seconds:
                    elapsed = time.monotonic() - started
                    if any(m.kind in ("hls", "dash") for m in result.media):
                        break
                    if result.embeds and elapsed > CLICK_AFTER_SECONDS + 2:
                        break  # an embedded player from a site yt-dlp knows; no need to wait longer
                    if not clicked and elapsed > CLICK_AFTER_SECONDS:
                        self._press_play(page)
                        clicked = True
                    page.wait_for_timeout(250)
                result.title = self._title(page)
                for frame in page.frames:
                    note_embed(frame.url)
                try:
                    for src in page.eval_on_selector_all("iframe[src]", "els => els.map(e => e.src)"):
                        note_embed(src)
                except PlaywrightError:
                    pass
                for captured in result.media:
                    cookies = context.cookies([captured.url])
                    if cookies:
                        result.cookies[captured.url] = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
            finally:
                browser.close()
        return result

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
