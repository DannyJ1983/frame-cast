"""The hidden-browser fallback for pages whose player is built by JavaScript.

The unit tests need nothing special. The browser tests load small local pages that behave
like live TV sites (a player that fetches its manifest after the page loads, one that waits
for a play button, an ad before the programme, a YouTube embed) in a real headless Chromium.
"""

import os
from pathlib import Path

import httpx
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse, Response
from starlette.routing import Route

from conftest import LiveServer
from framecast.resolver import NO_VIDEO, ResolveError, Resolver
from framecast.sniffer import (
    Captured,
    PageSniffer,
    SniffResult,
    can_fetch_directly,
    channel_hint,
    embed_url,
    find_stream_urls,
    is_ad,
    media_kind,
    mentions_stream,
    pick,
    to_stream,
)

MANIFEST = "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=800000\nlow/index.m3u8\n"


# Unit tests -------------------------------------------------------------------


@pytest.mark.parametrize(
    "url, content_type, expected",
    [
        ("https://cdn/live/master.m3u8?token=1", "", "hls"),
        ("https://cdn/live/playlist", "application/vnd.apple.mpegurl", "hls"),
        ("https://cdn/v/manifest.mpd", "", "dash"),
        ("https://cdn/v/clip.mp4", "", "file"),
        ("https://cdn/v/seg-001.ts", "", None),
        ("https://cdn/v/chunk.m4s", "video/iso.segment", None),
        ("https://cdn/v/seg", "video/mp2t", None),
        ("https://cdn/app.js", "application/javascript", None),
    ],
)
def test_media_kind(url, content_type, expected):
    assert media_kind(url, content_type) == expected


def test_is_ad():
    assert is_ad("https://pubads.g.doubleclick.net/gampad/ads?x=1")
    assert is_ad("https://imasdk.googleapis.com/js/sdkloader/ima3.js")
    assert not is_ad("https://cdn.example.com/live.m3u8")
    assert not is_ad("https://notdoubleclick.net.example.com/x")


def test_mentions_stream():
    assert mentions_stream("https://site/proxy?url=https%3A%2F%2Fcdn%2Flive.m3u8")
    assert not mentions_stream("https://site/app.js")


def test_channel_hint():
    assert channel_hint("https://famelack.com/tv/us/iWHPk6Fp0OGiq7") == "iWHPk6Fp0OGiq7"
    assert channel_hint("https://site/watch-live/") == "watch-live"
    assert channel_hint("https://site/live") is None


def test_find_stream_urls_matches_channel_id():
    data = (
        '[{"id":"aaaaaaa1","url":"https:\\/\\/one.example\\/a\\/index.m3u8"},'
        '{"id":"bbbbbbb2","url":"https://two.example/b/master.m3u8?t=1"},'
        '{"id":"ccccccc3","url":"https://three.example/c.mpd"}]'
    )
    assert find_stream_urls(data, "bbbbbbb2")[0] == "https://two.example/b/master.m3u8?t=1"
    assert find_stream_urls(data, "aaaaaaa1")[0] == "https://one.example/a/index.m3u8"
    # A list of many channels with nothing to say which one: don't guess.
    assert find_stream_urls(data) == []
    assert find_stream_urls('{"stream":"https://one.example/live.m3u8"}') == ["https://one.example/live.m3u8"]


def test_pick_falls_back_to_mentioned():
    result = SniffResult(mentioned=["https://cdn/live/index.m3u8"])
    assert pick(result).url == "https://cdn/live/index.m3u8"
    assert pick(result).kind == "hls"
    result.media.append(Captured("https://cdn/other.m3u8", "hls"))
    assert pick(result).url == "https://cdn/other.m3u8"


def test_youtube_video_files_ignored():
    result = SniffResult(media=[Captured("https://rr1---sn.googlevideo.com/videoplayback?x=1", "file")])
    assert pick(result) is None


def test_embed_url():
    assert embed_url("https://www.youtube.com/embed/abc123XYZ?autoplay=1") == "https://www.youtube.com/watch?v=abc123XYZ"
    assert embed_url("https://www.youtube-nocookie.com/embed/abc123XYZ") == "https://www.youtube.com/watch?v=abc123XYZ"
    assert embed_url("https://player.vimeo.com/video/12345") == "https://player.vimeo.com/video/12345"
    assert embed_url("https://example.com/embed/thing") is None


def test_pick_prefers_hls_then_dash_then_file_and_skips_ads():
    result = SniffResult(
        media=[
            Captured("https://cdn/promo.mp4", "file"),
            Captured("https://ads.adnxs.com/ad.m3u8", "hls"),
            Captured("https://cdn/v/manifest.mpd", "dash"),
            Captured("https://cdn/live/master.m3u8", "hls"),
            Captured("https://cdn/live/low/index.m3u8", "hls"),
        ]
    )
    assert pick(result).url == "https://cdn/live/master.m3u8"
    assert pick(SniffResult(media=[Captured("https://cdn/a.mp4", "file")])).kind == "file"
    assert pick(SniffResult()) is None


def _transport(status: int, body: bytes, needs_referer: bool = False):
    def handler(request: httpx.Request) -> httpx.Response:
        if needs_referer and "referer" not in request.headers:
            return httpx.Response(403)
        return httpx.Response(status, content=body)

    return httpx.MockTransport(handler)


def test_can_fetch_directly():
    assert can_fetch_directly("https://cdn/a.m3u8", "hls", "UA", _transport(200, MANIFEST.encode()))
    assert not can_fetch_directly("https://cdn/a.m3u8", "hls", "UA", _transport(403, b""))
    assert not can_fetch_directly("https://cdn/a.m3u8", "hls", "UA", _transport(200, b"<html>blocked</html>"))
    assert can_fetch_directly("https://cdn/a.mp4", "file", None, _transport(200, b"\x00\x00"))


def test_to_stream_drops_page_headers_when_not_needed():
    captured = Captured(
        "https://cdn/live/master.m3u8",
        "hls",
        {"user-agent": "UA", "referer": "https://site/page", "accept": "*/*"},
    )
    stream = to_stream(captured, SniffResult(title="News 24"), "https://site/page", _transport(200, MANIFEST.encode()))
    assert stream.headers == {"User-Agent": "UA"}
    assert not stream.needs_relay
    assert stream.title == "News 24"
    assert stream.kind == "hls"


def test_to_stream_keeps_page_headers_when_needed():
    captured = Captured("https://cdn/live/master.m3u8", "hls", {"user-agent": "UA"})
    result = SniffResult(title="", cookies={"https://cdn/live/master.m3u8": "session=1"})
    stream = to_stream(captured, result, "https://site/page", _transport(200, MANIFEST.encode(), needs_referer=True))
    assert stream.headers["Referer"] == "https://site/page"
    assert stream.headers["Cookie"] == "session=1"
    assert stream.needs_relay
    assert stream.title == "site"


class FakeSniffer:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def sniff(self, url):
        self.calls.append(url)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _no_video(url):
    raise ResolveError(NO_VIDEO)


def test_resolver_falls_back_to_browser():
    sniffer = FakeSniffer(SniffResult(title="Live", media=[Captured("https://cdn/x.mp4", "file")]))
    stream = Resolver(_no_video, sniffer).resolve("https://site/page")
    assert sniffer.calls == ["https://site/page"]
    assert stream.url == "https://cdn/x.mp4"


def test_resolver_tries_embeds_with_ytdlp():
    seen = []

    def extract(url):
        seen.append(url)
        if "youtube" in url:
            return {"title": "Embedded", "url": "https://cdn/y.mp4", "ext": "mp4"}, None
        raise ResolveError(NO_VIDEO)

    sniffer = FakeSniffer(SniffResult(embeds=["https://www.youtube.com/watch?v=abc123"]))
    stream = Resolver(extract, sniffer).resolve("https://site/page")
    assert seen == ["https://site/page", "https://www.youtube.com/watch?v=abc123"]
    assert stream.title == "Embedded"
    assert stream.page_url == "https://site/page"


def test_resolver_tries_browser_after_yt_dlp_errors():
    def ssl_error(url):
        raise ResolveError("Couldn't connect to that site from the home server. It may be down, or blocked on your broadband.")

    sniffer = FakeSniffer(SniffResult(media=[Captured("https://cdn/live.m3u8", "hls")]))
    assert Resolver(ssl_error, sniffer).resolve("https://site/page").url == "https://cdn/live.m3u8"

    # The browser opened the page but found nothing: say so, rather than repeat yt-dlp's complaint.
    loaded = FakeSniffer(SniffResult(log=["200 document  text/html  https://site/page"]))
    with pytest.raises(ResolveError, match="Couldn't find a video"):
        Resolver(ssl_error, loaded).resolve("https://site/page")
    # The browser couldn't open it either: keep the connection message.
    failed = FakeSniffer(SniffResult(log=["FAILED document  net::ERR_SSL_PROTOCOL_ERROR https://site/page"]))
    with pytest.raises(ResolveError, match="Couldn't connect"):
        Resolver(ssl_error, failed).resolve("https://site/page")


def test_resolver_skips_browser_when_it_cannot_help():
    def signed_in(url):
        raise ResolveError("That video needs you to be signed in, which Frame Cast can't do.")

    sniffer = FakeSniffer(SniffResult(media=[Captured("https://cdn/x.mp4", "file")]))
    with pytest.raises(ResolveError, match="signed in"):
        Resolver(signed_in, sniffer).resolve("https://site/page")
    assert sniffer.calls == []


def test_resolver_keeps_other_errors_and_browser_failures():
    def drm(url):
        raise ResolveError("That video is copy-protected, so it can't be played on the TV.")

    sniffer = FakeSniffer(SniffResult(media=[Captured("https://cdn/x.mp4", "file")]))
    with pytest.raises(ResolveError, match="copy-protected"):
        Resolver(drm, sniffer).resolve("https://site/page")
    assert sniffer.calls == []

    with pytest.raises(ResolveError, match="Couldn't find a video"):
        Resolver(_no_video, FakeSniffer(RuntimeError("browser crashed"))).resolve("https://site/page")
    with pytest.raises(ResolveError, match="Couldn't find a video"):
        Resolver(_no_video, FakeSniffer(SniffResult())).resolve("https://site/page")


def test_from_setting(monkeypatch, tmp_path):
    assert PageSniffer.from_setting("off") is None
    assert PageSniffer.from_setting(str(tmp_path / "missing-chromium")) is None
    fake = tmp_path / "chromium"
    fake.write_text("")
    assert PageSniffer.from_setting(str(fake)).browser_path == str(fake)
    monkeypatch.setattr(PageSniffer, "find_browser", staticmethod(lambda: None))
    assert PageSniffer.from_setting("auto") is None


# Browser tests ----------------------------------------------------------------


def _chromium():
    configured = os.environ.get("PLAYWRIGHT_CHROMIUM")
    if configured:
        return configured
    bundled = Path("/opt/pw-browsers/chromium")
    if bundled.exists():
        return str(bundled)
    return PageSniffer.find_browser()


PAGES = {
    # A player that fetches its manifest once the page's script runs, like hls.js.
    "player": """<title>News 24 Live</title><video id=v></video>
        <script>setTimeout(() => fetch('/media/live/master.m3u8'), 300)</script>""",
    # A player that waits for its play button.
    "click": """<title>Press play</title><button class="vjs-big-play-button">Play</button>
        <script>document.querySelector('button').onclick = () => fetch('/media/vod/index.m3u8')</script>""",
    # An ad request first (to a host that won't even resolve), then the programme.
    "ad": """<title>With ads</title><script>
        fetch('https://pubads.g.doubleclick.net/ad.m3u8').catch(() => {});
        setTimeout(() => fetch('/media/real/master.m3u8'), 400)</script>""",
    # A stream that only loads with the page's Referer.
    "protected": """<title>Protected</title><script>setTimeout(() => fetch('/media/protected/master.m3u8'), 200)</script>""",
    # Another site's player embedded in the page.
    "youtube": """<title>Embedded</title><iframe src="https://www.youtube.com/embed/abc123XYZ"></iframe>""",
    "nothing": """<title>No video here</title><p>Just words.</p>""",
    # A "Display" button comes first and must not be mistaken for play.
    "display": """<title>Display first</title>
        <button aria-label="Display settings" onclick="document.title='wrong button'">D</button>
        <button aria-label="Play live" onclick="fetch('/media/display/master.m3u8')">P</button>""",
    # A playlist served under an address with no .m3u8 and as text/plain.
    "oddname": """<title>Odd name</title><script>setTimeout(() => fetch('/odd/playlist?id=7'), 200)</script>""",
    # The player never starts (blocked, say), but the page's channel list names the stream.
    "listed": """<title>Listed</title><script>fetch('/api/channels.json')</script>""",
}


async def _page(request: Request) -> Response:
    return HTMLResponse(f"<!doctype html>{PAGES[request.path_params['name']]}")


async def _odd(request: Request) -> Response:
    return PlainTextResponse(MANIFEST)


async def _channels(request: Request) -> Response:
    data = [
        {"id": "aaaaaaa1", "name": "One", "url": "https://one.example/a/index.m3u8"},
        {"id": "chan12345", "name": "Two", "url": "https://two.example/b/master.m3u8"},
    ]
    import json

    return Response(json.dumps(data), media_type="application/json")


async def _media(request: Request) -> Response:
    path = request.path_params["path"]
    if path.startswith("protected/") and not request.headers.get("referer", "").endswith("/page/protected"):
        return PlainTextResponse("no", status_code=403)
    return Response(MANIFEST, media_type="application/vnd.apple.mpegurl")


async def _page_by_id(request: Request) -> Response:
    # Like famelack: /tv/<country>/<channel id>, with the list of channels fetched by script.
    return HTMLResponse(f"<!doctype html>{PAGES['listed']}")


@pytest.fixture(scope="module")
def site():
    app = Starlette(
        routes=[
            Route("/page/{name}", _page),
            Route("/tv/{country}/{name}", _page_by_id),
            Route("/media/{path:path}", _media),
            Route("/odd/playlist", _odd),
            Route("/api/channels.json", _channels),
        ]
    )
    server = LiveServer(app)
    server.start()
    yield server
    server.stop()


@pytest.fixture(scope="module")
def sniffer():
    pytest.importorskip("playwright.sync_api")
    path = _chromium()
    if not path:
        pytest.skip("No Chromium available")
    return PageSniffer(path, wait_seconds=8)


def test_browser_catches_manifest_fetched_by_script(site, sniffer):
    result = sniffer.sniff(f"{site.url}/page/player")
    assert result.title == "News 24 Live"
    assert pick(result).url == f"{site.url}/media/live/master.m3u8"


def test_browser_presses_play(site, sniffer):
    result = sniffer.sniff(f"{site.url}/page/click")
    assert pick(result).url == f"{site.url}/media/vod/index.m3u8"


def test_browser_ignores_ads(site, sniffer):
    result = sniffer.sniff(f"{site.url}/page/ad")
    assert [m.url for m in result.media] == [f"{site.url}/media/real/master.m3u8"]


def test_browser_finds_embeds(site, sniffer):
    result = sniffer.sniff(f"{site.url}/page/youtube")
    assert result.embeds == ["https://www.youtube.com/watch?v=abc123XYZ"]
    assert pick(result) is None


def test_browser_page_without_video(site, sniffer):
    sniffer_fast = PageSniffer(sniffer.browser_path, wait_seconds=4)
    assert pick(sniffer_fast.sniff(f"{site.url}/page/nothing")) is None


def test_browser_skips_display_button(site, sniffer):
    result = sniffer.sniff(f"{site.url}/page/display")
    assert pick(result).url == f"{site.url}/media/display/master.m3u8"
    assert result.title == "Display first"


def test_browser_finds_playlist_under_odd_name(site, sniffer):
    result = sniffer.sniff(f"{site.url}/page/oddname")
    assert pick(result).url == f"{site.url}/odd/playlist?id=7"
    assert pick(result).kind == "hls"


def test_browser_uses_channel_list_when_player_never_starts(site):
    quick = PageSniffer(_chromium(), wait_seconds=2)
    result = quick.sniff(f"{site.url}/tv/uk/chan12345")
    assert result.media == []
    assert pick(result).url == "https://two.example/b/master.m3u8"
    assert any("/api/channels.json" in line for line in result.log)


def test_resolver_end_to_end_with_relay_decision(site, sniffer):
    resolver = Resolver(_no_video, sniffer)
    open_stream = resolver.resolve(f"{site.url}/page/player")
    assert open_stream.url == f"{site.url}/media/live/master.m3u8"
    assert not open_stream.needs_relay

    protected = resolver.resolve(f"{site.url}/page/protected")
    assert protected.url == f"{site.url}/media/protected/master.m3u8"
    assert protected.headers["referer"].endswith("/page/protected")
    assert protected.needs_relay
