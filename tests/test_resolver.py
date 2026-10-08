import http.cookiejar

import pytest

from framecast.resolver import (
    COPY_PROTECTED,
    NO_VIDEO,
    ResolveError,
    Resolver,
    choose_stream,
    explain_error,
)

PAGE = "https://example.com/page"


def fmt(**kw):
    base = {"format_id": kw.pop("format_id", "f"), "http_headers": {"User-Agent": "UA/1", "Accept": "*/*"}}
    base.update(kw)
    return base


def test_prefers_hls_master_manifest():
    info = {
        "title": "Live match",
        "is_live": True,
        "formats": [
            fmt(url="https://cdn/v.mp4", protocol="https", ext="mp4", height=720, vcodec="avc1", acodec="mp4a"),
            fmt(url="https://cdn/720.m3u8", manifest_url="https://cdn/master.m3u8", protocol="m3u8_native", height=720),
            fmt(url="https://cdn/1080.m3u8", manifest_url="https://cdn/master.m3u8", protocol="m3u8_native", height=1080),
        ],
    }
    stream = choose_stream(info, PAGE)
    assert stream.kind == "hls"
    assert stream.url == "https://cdn/master.m3u8"
    assert stream.title == "Live match"
    assert stream.is_live
    assert stream.user_agent == "UA/1"
    assert "Accept" not in stream.headers


def test_hls_without_manifest_url_uses_variant():
    info = {"formats": [fmt(url="https://cdn/only.m3u8", protocol="m3u8")]}
    assert choose_stream(info, PAGE).url == "https://cdn/only.m3u8"


def test_file_needs_sound_and_picture():
    info = {
        "formats": [
            fmt(url="https://cdn/video-only.mp4", protocol="https", ext="mp4", height=2160, vcodec="avc1", acodec="none"),
            fmt(url="https://cdn/audio-only.m4a", protocol="https", ext="m4a", vcodec="none", acodec="mp4a"),
            fmt(url="https://cdn/both-480.mp4", protocol="https", ext="mp4", height=480, vcodec="avc1", acodec="mp4a"),
            fmt(url="https://cdn/both-720.webm", protocol="https", ext="webm", height=720, vcodec="vp9", acodec="opus"),
        ]
    }
    stream = choose_stream(info, PAGE)
    assert stream.kind == "file"
    # mp4 beats webm even at a lower resolution: it's the safer bet on the TV.
    assert stream.url == "https://cdn/both-480.mp4"


def test_file_with_unknown_codecs_accepted():
    info = {"title": "clip", "url": "https://cdn/clip.mp4", "ext": "mp4", "protocol": "https"}
    stream = choose_stream(info, PAGE)
    assert stream.url == "https://cdn/clip.mp4"
    assert stream.kind == "file"


def test_dash_used_when_nothing_else():
    info = {
        "formats": [
            fmt(url="https://cdn/v.m4s", manifest_url="https://cdn/manifest.mpd", protocol="http_dash_segments", height=1080, acodec="none"),
            fmt(url="https://cdn/a.m4s", manifest_url="https://cdn/manifest.mpd", protocol="http_dash_segments", vcodec="none"),
        ]
    }
    stream = choose_stream(info, PAGE)
    assert stream.kind == "dash"
    assert stream.url == "https://cdn/manifest.mpd"


def test_over_4k_not_preferred():
    info = {
        "formats": [
            fmt(url="https://cdn/8k.mp4", protocol="https", ext="mp4", height=4320),
            fmt(url="https://cdn/4k.mp4", protocol="https", ext="mp4", height=2160),
        ]
    }
    assert choose_stream(info, PAGE).url == "https://cdn/4k.mp4"


def test_playlist_takes_first_entry():
    info = {"_type": "playlist", "entries": [None, {"title": "first", "url": "https://cdn/1.mp4", "ext": "mp4"}]}
    assert choose_stream(info, PAGE).title == "first"


def test_empty_playlist():
    with pytest.raises(ResolveError, match=NO_VIDEO):
        choose_stream({"_type": "playlist", "entries": []}, PAGE)


def test_all_drm_is_copy_protected():
    info = {"formats": [fmt(url="https://cdn/x.mpd", protocol="http_dash_segments", has_drm=True)]}
    with pytest.raises(ResolveError, match="copy-protected"):
        choose_stream(info, PAGE)


def test_drm_skipped_when_clear_stream_exists():
    info = {
        "formats": [
            fmt(url="https://cdn/drm.m3u8", protocol="m3u8_native", has_drm=True),
            fmt(url="https://cdn/clear.mp4", protocol="https", ext="mp4"),
        ]
    }
    assert choose_stream(info, PAGE).url == "https://cdn/clear.mp4"


def test_maybe_drm_still_tried():
    info = {"formats": [fmt(url="https://cdn/m.m3u8", protocol="m3u8_native", has_drm="maybe")]}
    assert choose_stream(info, PAGE).kind == "hls"


def test_nothing_playable():
    info = {"formats": [fmt(url="rtmp://cdn/live", protocol="rtmp")]}
    with pytest.raises(ResolveError, match="not in a form the TV can play"):
        choose_stream(info, PAGE)


def test_ua_alone_does_not_need_relay():
    stream = choose_stream({"url": "https://cdn/a.mp4", "ext": "mp4", "http_headers": {"User-Agent": "UA"}}, PAGE)
    assert not stream.needs_relay


@pytest.mark.parametrize("header", ["Referer", "Origin", "X-Token", "Authorization"])
def test_special_headers_need_relay(header):
    stream = choose_stream({"url": "https://cdn/a.mp4", "ext": "mp4", "http_headers": {header: "v"}}, PAGE)
    assert stream.needs_relay


def _jar_with(domain: str) -> http.cookiejar.CookieJar:
    jar = http.cookiejar.CookieJar()
    jar.set_cookie(
        http.cookiejar.Cookie(
            0, "session", "abc", None, False, domain, True, domain.startswith("."), "/", True,
            False, None, False, None, None, {},
        )
    )
    return jar


def test_cookies_for_stream_host_need_relay():
    stream = choose_stream({"url": "https://cdn.example.com/a.mp4", "ext": "mp4"}, PAGE, _jar_with(".example.com"))
    assert stream.cookie_header() == "session=abc"
    assert stream.needs_relay


def test_cookies_for_other_host_ignored():
    stream = choose_stream({"url": "https://cdn.other.net/a.mp4", "ext": "mp4"}, PAGE, _jar_with(".example.com"))
    assert stream.cookie_header() == ""
    assert not stream.needs_relay


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("ERROR: [generic] Unsupported URL: https://x", NO_VIDEO),
        ("\x1b[0;31mERROR:\x1b[0m This video is DRM protected", COPY_PROTECTED),
        ("ERROR: Private video. Sign in if you've been granted access", "signed in"),
        ("ERROR: The uploader has not made this video available in your country", "isn't available"),
        ("ERROR: Something odd\nmore detail", "Couldn't get the video: Something odd"),
    ],
)
def test_explain_error(raw, expected):
    assert expected in explain_error(raw)


def test_resolver_wraps_unexpected_errors():
    def boom(url):
        raise ValueError("ERROR: weird failure")

    with pytest.raises(ResolveError, match="weird failure"):
        Resolver(boom).resolve(PAGE)


def test_resolver_uses_extractor():
    resolver = Resolver(lambda url: ({"title": url, "url": "https://cdn/a.mp4", "ext": "mp4"}, None))
    assert resolver.resolve(PAGE).title == PAGE
