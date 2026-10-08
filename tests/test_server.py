import json
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from framecast import server as server_module
from framecast.relay import Relay
from framecast.server import create_app


@pytest.fixture(autouse=True)
def short_waits(monkeypatch):
    monkeypatch.setattr(server_module, "ACK_TIMEOUT", 0.2)
    monkeypatch.setattr(server_module, "LAUNCH_WAIT", 1.0)


@pytest.fixture
def client(settings, fake_resolver):
    with TestClient(create_app(settings, resolver=fake_resolver)) as c:
        yield c


def test_phone_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Frame Cast" in response.text
    assert client.get("/static/phone.js").status_code == 200


def test_send_with_tv_closed_keeps_link_pending(client):
    response = client.post("/api/send", json={"url": "https://site.example/video/1"})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert "Open Frame Cast on the TV" in body["message"]
    hub = client.app.state.hub
    assert hub.pending.title == "Video at 1"
    assert hub.pending.url == "https://cdn.example/v/master.m3u8"
    assert hub.pending.user_agent == "TestUA"
    assert hub.pending.relayed is False


@pytest.mark.parametrize(
    "kwargs",
    [
        {"json": {"text": "Look at this https://site.example/video/2 !"}},
        {"content": "Shared title\nhttps://site.example/video/2", "headers": {"content-type": "text/plain"}},
        {"data": {"url": "https://site.example/video/2"}},
        {"params": {"url": "https://site.example/video/2"}},
        {"content": json.dumps("https://site.example/video/2"), "headers": {"content-type": "application/json"}},
    ],
)
def test_send_accepts_many_shapes(client, kwargs):
    response = client.post("/api/send", **kwargs)
    assert response.status_code == 200, response.text
    assert client.app.state.hub.pending.title == "Video at 2"


def test_send_without_link(client):
    response = client.post("/api/send", json={"text": "no link here"})
    assert response.status_code == 400
    assert response.json()["ok"] is False


def test_send_reports_resolve_error(client):
    response = client.post("/api/send", json={"url": "https://site.example/novideo"})
    assert response.status_code == 422
    assert response.json()["message"] == "Couldn't find a video on that page."
    assert client.app.state.hub.last_message["level"] == "error"


def test_plain_text_reply(client):
    response = client.post("/api/send?reply=text", content="https://site.example/novideo")
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == "Couldn't find a video on that page."


def test_stream_needing_referer_is_relayed(client):
    client.post("/api/send", json={"url": "https://site.example/protected/3"})
    pending = client.app.state.hub.pending
    assert pending.relayed is True
    assert pending.url.startswith("/p/")
    assert pending.url.endswith("/master.m3u8")
    assert pending.user_agent is None


def test_relay_always(settings, fake_resolver):
    settings.relay = "always"
    with TestClient(create_app(settings, resolver=fake_resolver)) as c:
        c.post("/api/send", json={"url": "https://site.example/video/4"})
        assert c.app.state.hub.pending.relayed is True


def test_relay_endpoint_serves_through_app(settings, fake_resolver):
    def upstream(request):
        assert request.headers["referer"] == "https://site.example/"
        return httpx.Response(200, headers={"content-type": "application/vnd.apple.mpegurl"}, text="#EXTM3U\nseg.ts\n")

    relay = Relay(transport=httpx.MockTransport(upstream))
    with TestClient(create_app(settings, resolver=fake_resolver, relay=relay)) as c:
        c.post("/api/send", json={"url": "https://site.example/protected/5"})
        path = c.app.state.hub.pending.url
        response = c.get(path)
        assert response.status_code == 200
        assert response.text.splitlines()[1].startswith("/p/")
        assert c.get("/p/nope/nope/nope/x.ts").status_code == 404


def test_test_video(client):
    response = client.post("/api/test")
    assert response.status_code == 200
    assert client.app.state.hub.pending.url == server_module.TEST_STREAM_URL


def test_control_needs_tv(client):
    assert client.post("/api/control", json={"action": "toggle"}).status_code == 409
    assert client.post("/api/control", json={"action": "dance"}).status_code == 400


def test_tv_status_updates_hub(client):
    response = client.post(
        "/api/tv/status",
        content=json.dumps({"state": "playing", "position": 5000, "duration": 60000}),
        headers={"content-type": "text/plain"},
    )
    assert response.status_code == 204
    state = client.get("/api/state").json()
    assert state["tv"]["state"] == "playing"
    assert state["tv"]["position"] == 5000
    assert client.post("/api/tv/status", content="nonsense").status_code == 400


def test_cors_for_tv_app(client):
    response = client.get("/api/state", headers={"origin": "null"})
    assert response.headers["access-control-allow-origin"] == "*"


def test_tv_app_served_for_browser_testing(client):
    assert client.get("/tv/").status_code == 200


class FakeLauncher:
    """Pretends to open the app on the TV; the 'app' then acknowledges the pending link."""

    def __init__(self, hub_getter, works=True, tv_on=True):
        self.hub_getter = hub_getter
        self.works = works
        self.tv_on = tv_on
        self.calls = []

    async def device_info(self):
        return {"device": {"name": "Frame"}} if self.tv_on else None

    def attempts(self):
        async def rest():
            self.calls.append("REST")
            if self.works:
                hub = self.hub_getter()
                hub.report_status({"command_id": hub.pending.id, "state": "loading"})
            return self.works

        async def ws():
            self.calls.append("WebSocket")
            return False

        return [("REST", rest), ("WebSocket", ws)]


def wait_for(predicate, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def _launcher_client(settings, fake_resolver, **kw):
    holder = {}
    launcher = FakeLauncher(lambda: holder["app"].state.hub, **kw)
    app = create_app(settings, resolver=fake_resolver, launcher=launcher)
    holder["app"] = app
    return app, launcher


def test_launcher_opens_app_when_tv_closed(settings, fake_resolver):
    app, launcher = _launcher_client(settings, fake_resolver)
    with TestClient(app) as c:
        body = c.post("/api/send", json={"url": "https://site.example/video/6"}).json()
        assert "Opening Frame Cast" in body["message"]
        hub = app.state.hub
        assert wait_for(lambda: hub.last_message and hub.last_message["text"].startswith("Sent to the TV"))
        assert launcher.calls == ["REST"]
        assert hub.pending is None


def test_launcher_gives_up_politely(settings, fake_resolver):
    app, launcher = _launcher_client(settings, fake_resolver, works=False)
    with TestClient(app) as c:
        c.post("/api/send", json={"url": "https://site.example/video/7"})
        hub = app.state.hub
        assert wait_for(lambda: hub.last_message and "Couldn't open Frame Cast" in hub.last_message["text"])
        assert launcher.calls == ["REST", "WebSocket"]
        assert hub.pending is not None  # still plays if the app is opened by hand


def test_launcher_reports_tv_off(settings, fake_resolver):
    app, launcher = _launcher_client(settings, fake_resolver, tv_on=False)
    with TestClient(app) as c:
        c.post("/api/send", json={"url": "https://site.example/video/8"})
        hub = app.state.hub
        assert wait_for(lambda: hub.last_message and "didn't answer" in hub.last_message["text"])
        assert launcher.calls == []


def _read_events(response, wanted, out):
    event = None
    for line in response.iter_lines():
        if line.startswith("event: "):
            event = line[7:]
        elif line.startswith("data: ") and event:
            out.append((event, json.loads(line[6:])))
            if len(out) >= wanted:
                return


def test_connected_tv_gets_play_and_acks(live_server):
    """A real server: the 'TV' listens on the event stream and confirms the play command."""
    received = []

    def tv():
        with httpx.Client(timeout=10) as http:
            with http.stream("GET", f"{live_server.url}/api/tv/events") as response:
                assert response.headers["content-type"].startswith("text/event-stream")
                _read_events(response, 1, received)
            play = received[0][1]
            http.post(
                f"{live_server.url}/api/tv/status",
                content=json.dumps({"command_id": play["id"], "state": "loading"}),
            )

    thread = threading.Thread(target=tv, daemon=True)
    thread.start()
    assert wait_for(lambda: live_server.app.state.hub.tv_count == 1)
    response = httpx.post(f"{live_server.url}/api/send", json={"url": "https://site.example/video/9"}, timeout=10)
    thread.join(5)
    assert received and received[0][0] == "play"
    assert received[0][1]["title"] == "Video at 9"
    assert response.json()["message"] == "Sent to the TV: Video at 9"


def test_phone_event_stream(live_server):
    received = []
    with httpx.Client(timeout=10) as http:
        with http.stream("GET", f"{live_server.url}/api/events") as response:
            _read_events(response, 1, received)
    assert received[0][0] == "state"
    assert received[0][1]["tv_connected"] is False
