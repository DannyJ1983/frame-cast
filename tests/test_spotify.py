"""Spotify Now Playing: signing in, reading the player and queue, caching, and the routes."""

import asyncio
import stat

import pytest
from fastapi.testclient import TestClient

from spotify_samples import CLIENT_ID, EPISODE, NEXT, NOW, FakeSpotify, player_state
from framecast.server import create_app
from framecast.spotify import NowPlaying, SpotifyStore
from framecast.spotify import auth, player
from framecast.spotify.auth import SpotifyError
from framecast.spotify.service import REFUSED


def test_pkce_challenge_matches_the_rfc_example():
    # RFC 7636, appendix B.
    assert auth.code_challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk") == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    verifier = auth.code_verifier()
    assert 43 <= len(verifier) <= 128


def test_authorize_url_and_redirect():
    assert auth.redirect_uri(8090) == "http://127.0.0.1:8090/spotify/callback"
    url = auth.authorize_url(CLIENT_ID, auth.redirect_uri(8090), "abc", "st")
    assert url.startswith("https://accounts.spotify.com/authorize?")
    for part in (f"client_id={CLIENT_ID}", "response_type=code", "code_challenge_method=S256", "code_challenge=abc",
                 "state=st", "scope=user-read-playback-state+user-read-currently-playing",
                 "redirect_uri=http%3A%2F%2F127.0.0.1%3A8090%2Fspotify%2Fcallback"):
        assert part in url


def test_code_from_the_pasted_address():
    pasted = "http://127.0.0.1:8090/spotify/callback?code=AQB123&state=st"
    assert auth.code_from_redirect(pasted, "st") == "AQB123"
    assert auth.code_from_redirect("code=AQB123&state=st", "st") == "AQB123"
    for text, expected in [
        ("http://127.0.0.1:8090/spotify/callback?error=access_denied&state=st", "wasn't allowed"),
        ("http://127.0.0.1:8090/spotify/callback?code=AQB123&state=old", "older attempt"),
        ("http://127.0.0.1:8090/spotify/callback", "doesn't have a code"),
    ]:
        with pytest.raises(SpotifyError, match=expected):
            auth.code_from_redirect(text, "st")


def test_playback_parsing():
    now = player.playback(player_state(), "office")
    assert now["state"] == "playing" and now["device"] == "Office" and now["progress_ms"] == 61000
    assert now["track"] == {"id": "t1", "title": "Blue Monday", "artists": "New Order", "album": "Power, Corruption & Lies",
                            "art": "https://i.scdn.co/image/t1-640", "thumb": "https://i.scdn.co/image/t1-64",
                            "duration_ms": 449000, "kind": "track"}
    assert player.playback(player_state(playing=False), "Office")["state"] == "paused"
    assert player.playback(player_state(name="Kitchen"), "Office") == {"state": "elsewhere", "device": "Office", "active_device": "Kitchen"}
    assert player.playback(None, "Office") == {"state": "idle", "device": "Office"}
    assert player.playback(player_state(item=None, kind="ad"), "Office")["state"] == "advert"
    episode = player.playback(player_state(item=EPISODE, kind="episode"), "Office")["track"]
    assert episode["kind"] == "episode" and episode["artists"] == "Sussex Audio" and episode["album"] == "Seaside Stories"
    assert player.pick_image([{"url": "a", "width": 64}, {"url": "b", "width": 300}], 200) == "b"
    assert player.pick_image([{"url": "a", "width": 64}], 600) == "a"
    assert player.pick_image([], 600) == ""
    queue = player.up_next({"currently_playing": NOW, "queue": NEXT + NEXT})
    assert [t["title"] for t in queue] == ["Age of Consent", "Ceremony", "Temptation", "Age of Consent", "Ceremony"]
    assert queue[1]["artists"] == "New Order, Joy Division"
    assert player.up_next(None) == []


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def make(tmp_path, connected=True):
    fake = FakeSpotify()
    store = SpotifyStore(tmp_path)
    store.settings.client_id = CLIENT_ID
    if connected:
        store.settings.refresh_token = "refresh-0"
    clock = Clock()
    return NowPlaying(store, port=8090, clock=clock, http=fake.client()), fake, clock


def run(coro):
    return asyncio.run(coro)


def test_signing_in(tmp_path):
    service, fake, _ = make(tmp_path, connected=False)

    url = service.start_connect()
    state = url.split("state=")[1].split("&")[0]
    challenge = url.split("code_challenge=")[1].split("&")[0]
    status = run(service.finish_connect(f"http://127.0.0.1:8090/spotify/callback?code=CODE&state={state}"))
    assert status["settings"]["connected"] and status["settings"]["account"] == "Danny"
    exchange = fake.form(fake.requests[0])
    assert exchange["grant_type"] == "authorization_code" and exchange["code"] == "CODE"
    assert exchange["client_id"] == CLIENT_ID and exchange["redirect_uri"] == "http://127.0.0.1:8090/spotify/callback"
    assert auth.code_challenge(exchange["code_verifier"]) == challenge  # the verifier matches the challenge sent
    saved = tmp_path / "spotify.json"
    assert stat.S_IMODE(saved.stat().st_mode) == 0o600
    assert '"refresh_token": "refresh-1"' in saved.read_text()
    with pytest.raises(SpotifyError, match="Press Connect first"):
        run(service.finish_connect("code=x&state=y"))


def test_now_playing_with_queue_and_caching(tmp_path):
    service, fake, clock = make(tmp_path)

    async def go():
        first = await service.snapshot()
        clock.t += 2
        second = await service.snapshot()  # cached, with progress moved on two seconds
        clock.t += 5
        fake.player = player_state(item=NEXT[0], progress=1000)
        third = await service.snapshot()  # new track: fetches the queue again
        return first, second, third

    first, second, third = run(go())
    assert first["state"] == "playing" and first["track"]["title"] == "Blue Monday"
    assert [t["title"] for t in first["queue"]] == ["Age of Consent", "Ceremony", "Temptation"]
    assert second["progress_ms"] == 63000
    assert fake.calls("/me/player") == 2 and fake.calls("/me/player/queue") == 2
    assert third["track"]["title"] == "Age of Consent"
    # The refresh token was used, and the new one Spotify handed out was kept.
    refresh = fake.form(fake.requests[0])
    assert refresh == {"grant_type": "refresh_token", "refresh_token": "refresh-0", "client_id": CLIENT_ID}
    assert service.store.settings.refresh_token == "refresh-1"
    assert fake.requests[1].headers["authorization"] == "Bearer access-1"


def test_paused_elsewhere_and_nothing_playing(tmp_path):
    service, fake, clock = make(tmp_path)
    fake.player = player_state(playing=False)
    paused = run(service.snapshot())
    assert paused["state"] == "paused" and paused["progress_ms"] == 61000
    clock.t += 10
    fake.player = player_state(name="Kitchen")
    elsewhere = run(service.snapshot())
    assert elsewhere["state"] == "elsewhere" and elsewhere["active_device"] == "Kitchen" and elsewhere["queue"] == []
    clock.t += 10
    fake.player = None
    assert run(service.snapshot())["state"] == "idle"


def test_expired_token_is_refreshed_and_the_request_retried(tmp_path):
    service, fake, clock = make(tmp_path)
    run(service.snapshot())
    clock.t += 10
    fake.expire_next = True
    result = run(service.snapshot())
    assert result["state"] == "playing" and fake.token_count == 2


def test_slow_down_and_refusals(tmp_path):
    service, fake, clock = make(tmp_path)
    fake.status["/me/player"] = 429
    run(service.snapshot())
    clock.t += 10
    run(service.snapshot())
    assert fake.calls("/me/player") == 1  # still waiting out the 30 seconds Spotify asked for
    clock.t += 30
    fake.status["/me/player"] = 403
    assert run(service.snapshot())["note"] == REFUSED


def test_revoked_sign_in_asks_to_connect_again(tmp_path):
    service, fake, _ = make(tmp_path)
    fake.refresh_ok = False
    result = run(service.snapshot())
    assert result["state"] == "not_connected" and "sign in again" in result["note"]
    assert not service.store.settings.connected


def test_settings_and_devices(tmp_path):
    service, fake, _ = make(tmp_path)
    assert run(service.devices()) == ["Office", "Kitchen"]
    status = service.update_settings({"device_name": "  Kitchen  ", "auto_show": True})
    assert status["settings"]["device_name"] == "Kitchen" and status["settings"]["auto_show"]
    with pytest.raises(SpotifyError, match="Client ID"):
        service.update_settings({"client_id": "not-an-id"})
    with pytest.raises(SpotifyError, match="name of the speaker"):
        service.update_settings({"device_name": "  "})
    service.update_settings({"client_id": "f" * 32})
    assert not service.store.settings.connected  # a new app needs a new sign-in
    assert SpotifyStore(tmp_path).settings.device_name == "Kitchen"


def test_routes(settings, fake_resolver, tmp_path):
    fake = FakeSpotify()
    service = NowPlaying(SpotifyStore(settings.state_dir), port=8090, http=fake.client())
    with TestClient(create_app(settings, resolver=fake_resolver, spotify=service)) as c:
        assert c.get("/api/nowplaying").json()["state"] == "not_set_up"
        assert c.post("/api/spotify/connect").status_code == 400
        assert c.put("/api/spotify/settings", json={"client_id": CLIENT_ID}).status_code == 200
        assert c.get("/api/nowplaying").json()["state"] == "not_connected"
        url = c.post("/api/spotify/connect").json()["url"]
        assert "code_challenge=" in url
        state = url.split("state=")[1].split("&")[0]
        bad = c.post("/api/spotify/finish", json={"address": "code=x&state=wrong"})
        assert bad.status_code == 400 and "older attempt" in bad.json()["message"]
        done = c.post("/api/spotify/finish", json={"address": f"http://127.0.0.1:8090/spotify/callback?code=C&state={state}"})
        assert done.json()["message"] == "Connected to Spotify as Danny."
        now = c.get("/api/nowplaying")
        assert now.headers["cache-control"] == "no-store" and now.json()["track"]["title"] == "Blue Monday"
        assert c.get("/api/spotify/devices").json()["devices"] == ["Office", "Kitchen"]
        assert "refresh" not in c.get("/api/spotify").text
        assert c.get("/nowplaying", follow_redirects=False).headers["location"] == "/dashboard/nowplaying.html"
        assert c.post("/api/nowplaying/show").status_code == 409
        queue = c.app.state.hub.subscribe_tv()
        assert c.post("/api/nowplaying/show").status_code == 200
        assert ("show", {"screen": "nowplaying"}) in [queue.get_nowait() for _ in range(queue.qsize())]
        # The callback route finishes a sign-in when the browser can reach it directly.
        url = c.post("/api/spotify/connect").json()["url"]
        state = url.split("state=")[1].split("&")[0]
        page = c.get(f"/spotify/callback?code=C2&state={state}")
        assert page.status_code == 200 and "connected" in page.text
        assert c.post("/api/spotify/disconnect").json()["settings"]["connected"] is False
