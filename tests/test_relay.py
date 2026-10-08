import asyncio
import http.cookiejar

import httpx

from framecast.relay import Relay, rewrite_playlist, split_url


def collect(response) -> bytes:
    async def run():
        if hasattr(response, "body_iterator"):
            out = b""
            async for chunk in response.body_iterator:
                out += chunk if isinstance(chunk, bytes) else chunk.encode()
            if response.background:
                await response.background()
            return out
        return response.body

    return asyncio.run(run())


def serve(relay: Relay, path: str, method: str = "GET", range_header: str | None = None):
    raw, _, query = path.partition("?")
    return asyncio.run(relay.serve(raw, query, method, range_header))


def test_split_url():
    assert split_url("https://cdn.example.com/a/b/master.m3u8?t=1") == (
        "https://cdn.example.com/a/b/",
        "master.m3u8",
        "t=1",
    )
    assert split_url("https://cdn.example.com") == ("https://cdn.example.com/", "", "")


def test_path_round_trip():
    relay = Relay(secret=b"k")
    sid = relay.open_session({"Referer": "https://site/"})
    path = relay.path_for(sid, "https://cdn/x/y/master.m3u8?token=abc")
    assert path.startswith("/p/" + sid + "/")
    assert path.endswith("/master.m3u8?token=abc")
    raw, _, query = path.partition("?")
    url, session = relay.target_for(raw, query)
    assert url == "https://cdn/x/y/master.m3u8?token=abc"
    assert session.headers == {"Referer": "https://site/"}


def test_relative_paths_under_signed_folder_allowed():
    relay = Relay(secret=b"k")
    sid = relay.open_session({})
    path = relay.path_for(sid, "https://cdn/x/manifest.mpd")
    sibling = path.rsplit("/", 1)[0] + "/video/1080/seg-12.m4s"
    url, _ = relay.target_for(sibling, "")
    assert url == "https://cdn/x/video/1080/seg-12.m4s"


def test_tampered_folder_rejected():
    relay = Relay(secret=b"k")
    sid = relay.open_session({})
    good = relay.path_for(sid, "https://cdn/x/a.ts")
    other = relay.path_for(sid, "https://evil/internal/a.ts")
    # Swap in another folder while keeping the first signature.
    parts = good.split("/")
    parts[4] = other.split("/")[4]
    assert relay.target_for("/".join(parts), "") is None


def test_unknown_session_rejected():
    relay = Relay(secret=b"k")
    sid = relay.open_session({})
    path = relay.path_for(sid, "https://cdn/x/a.ts")
    assert Relay(secret=b"k").target_for(path, "") is None
    assert relay.target_for("/p/garbage", "") is None


def test_old_sessions_dropped():
    relay = Relay(max_sessions=2)
    first = relay.open_session({})
    relay.open_session({})
    relay.open_session({})
    assert relay.session(first) is None


def test_rewrite_playlist():
    playlist = "\n".join(
        [
            "#EXTM3U",
            '#EXT-X-KEY:METHOD=AES-128,URI="key.bin",IV=0x1',
            '#EXT-X-MAP:URI="/init.mp4"',
            '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="a",URI="https://audio.cdn/a.m3u8"',
            '#EXT-X-KEY:METHOD=SAMPLE-AES,URI="skd://some-key"',
            "#EXTINF:6.0,",
            "seg1.ts?x=1",
            "",
            "#EXTINF:6.0,",
            "https://other.cdn/seg2.ts",
        ]
    )
    out = rewrite_playlist(playlist, "https://cdn/live/index.m3u8", lambda u: f"R[{u}]")
    assert 'URI="R[https://cdn/live/key.bin]"' in out
    assert 'URI="R[https://cdn/init.mp4]"' in out
    assert 'URI="R[https://audio.cdn/a.m3u8]"' in out
    assert 'URI="skd://some-key"' in out
    assert "R[https://cdn/live/seg1.ts?x=1]" in out.splitlines()
    assert "R[https://other.cdn/seg2.ts]" in out.splitlines()
    assert out.startswith("#EXTM3U\n")


class Upstream:
    """A fake CDN that records the requests the relay makes."""

    def __init__(self):
        self.requests = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path.endswith("master.m3u8"):
            return httpx.Response(
                200,
                headers={"content-type": "application/vnd.apple.mpegurl"},
                text="#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\nhi/index.m3u8\n",
            )
        if path.endswith("sneaky"):
            return httpx.Response(200, headers={"content-type": "text/plain"}, text="#EXTM3U\nseg.ts\n")
        if path.endswith("seg.ts"):
            body = b"0123456789"
            if request.headers.get("range") == "bytes=2-5":
                return httpx.Response(
                    206,
                    headers={"content-type": "video/mp2t", "content-range": "bytes 2-5/10", "content-length": "4"},
                    content=body[2:6],
                )
            return httpx.Response(200, headers={"content-type": "video/mp2t", "content-length": "10"}, content=body)
        if path.endswith("blob"):
            return httpx.Response(200, headers={"content-type": "application/octet-stream"}, content=b"\x00\x01binary")
        return httpx.Response(404, text="nope")


def make_relay(headers=None, cookies=None):
    upstream = Upstream()
    relay = Relay(secret=b"k", transport=httpx.MockTransport(upstream))
    sid = relay.open_session(headers or {"Referer": "https://site/", "User-Agent": "UA"}, cookies)
    return relay, sid, upstream


def test_serve_rewrites_playlist_and_sends_headers():
    relay, sid, upstream = make_relay()
    response = serve(relay, relay.path_for(sid, "https://cdn/v/master.m3u8"))
    body = collect(response).decode()
    assert response.media_type == "application/vnd.apple.mpegurl"
    variant = body.splitlines()[2]
    assert variant == relay.path_for(sid, "https://cdn/v/hi/index.m3u8")
    sent = upstream.requests[0]
    assert sent.headers["referer"] == "https://site/"
    assert sent.headers["user-agent"] == "UA"


def test_serve_sniffs_mislabelled_playlist():
    relay, sid, _ = make_relay()
    body = collect(serve(relay, relay.path_for(sid, "https://cdn/v/sneaky"))).decode()
    assert body.splitlines()[1] == relay.path_for(sid, "https://cdn/v/seg.ts")


def test_serve_streams_segment_with_range():
    relay, sid, upstream = make_relay()
    response = serve(relay, relay.path_for(sid, "https://cdn/v/seg.ts"), range_header="bytes=2-5")
    assert response.status_code == 206
    assert response.headers["content-range"] == "bytes 2-5/10"
    assert collect(response) == b"2345"
    assert upstream.requests[0].headers["range"] == "bytes=2-5"


def test_serve_binary_not_mistaken_for_playlist():
    relay, sid, _ = make_relay()
    assert collect(serve(relay, relay.path_for(sid, "https://cdn/v/blob"))) == b"\x00\x01binary"


def test_serve_passes_upstream_errors():
    relay, sid, _ = make_relay()
    assert serve(relay, relay.path_for(sid, "https://cdn/v/missing.mp4")).status_code == 404


def test_serve_rejects_bad_path():
    relay, _, _ = make_relay()
    assert serve(relay, "/p/x/y/z/w").status_code == 404


def test_serve_head():
    relay, sid, _ = make_relay()
    response = serve(relay, relay.path_for(sid, "https://cdn/v/seg.ts"), method="HEAD")
    assert response.status_code == 200
    assert response.headers["content-length"] == "10"


def test_serve_sends_cookies_for_matching_host():
    jar = http.cookiejar.CookieJar()
    jar.set_cookie(
        http.cookiejar.Cookie(
            0, "s", "1", None, False, ".cdn.example", True, True, "/", True,
            False, None, False, None, None, {},
        )
    )
    relay, sid, upstream = make_relay(headers={}, cookies=jar)
    collect(serve(relay, relay.path_for(sid, "https://a.cdn.example/v/seg.ts")))
    assert upstream.requests[0].headers["cookie"] == "s=1"
