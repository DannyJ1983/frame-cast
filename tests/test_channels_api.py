"""The saved-channel endpoints on the hub."""

import json

import pytest
from fastapi.testclient import TestClient

from framecast import server as server_module
from framecast.resolver import Resolver
from framecast.server import create_app

from conftest import fake_extract

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20


@pytest.fixture(autouse=True)
def short_waits(monkeypatch):
    monkeypatch.setattr(server_module, "ACK_TIMEOUT", 0.2)


class CountingExtract:
    def __init__(self):
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        return fake_extract(url)


@pytest.fixture
def extract():
    return CountingExtract()


@pytest.fixture
def client(settings, extract):
    with TestClient(create_app(settings, resolver=Resolver(extract))) as c:
        yield c


def add(client, name="News 24", url="https://site.example/video/news"):
    response = client.post("/api/channels", json={"name": name, "url": url})
    assert response.status_code == 201, response.text
    return response.json()


def test_add_list_edit_delete(client):
    news = add(client)
    assert news["name"] == "News 24" and news["has_logo"] is False
    sport = add(client, "Sport", "https://site.example/video/sport")
    assert [c["name"] for c in client.get("/api/channels").json()["channels"]] == ["News 24", "Sport"]

    edited = client.patch(f"/api/channels/{sport['id']}", json={"name": "Sport HD"}).json()
    assert edited["name"] == "Sport HD" and edited["url"] == "https://site.example/video/sport"

    assert client.post(f"/api/channels/{sport['id']}/move", json={"step": -1}).status_code == 204
    assert [c["name"] for c in client.get("/api/channels").json()["channels"]] == ["Sport HD", "News 24"]

    assert client.delete(f"/api/channels/{news['id']}").status_code == 204
    assert [c["name"] for c in client.get("/api/channels").json()["channels"]] == ["Sport HD"]
    assert client.delete(f"/api/channels/{news['id']}").status_code == 404


def test_bad_input(client):
    assert client.post("/api/channels", json={"name": "", "url": "https://x.example/a"}).status_code == 400
    response = client.post("/api/channels", json={"name": "A", "url": "nope"})
    assert response.status_code == 400
    assert "web address" in response.json()["message"]


def test_channels_survive_a_restart(settings, extract):
    with TestClient(create_app(settings, resolver=Resolver(extract))) as c:
        add(c)
    with TestClient(create_app(settings, resolver=Resolver(extract))) as c:
        assert [x["name"] for x in c.get("/api/channels").json()["channels"]] == ["News 24"]


def test_logo_upload_fetch_and_remove(client):
    news = add(client)
    response = client.put(f"/api/channels/{news['id']}/logo", content=PNG, headers={"content-type": "image/png"})
    assert response.status_code == 200
    assert response.json()["has_logo"] is True and response.json()["logo_version"] == 1
    logo = client.get(f"/api/channels/{news['id']}/logo?v=1")
    assert logo.status_code == 200 and logo.content == PNG
    assert logo.headers["content-type"] == "image/png"
    bad = client.put(f"/api/channels/{news['id']}/logo", content=b"<svg/>")
    assert bad.status_code == 400 and "PNG, JPEG" in bad.json()["message"]
    assert client.delete(f"/api/channels/{news['id']}/logo").json()["has_logo"] is False
    assert client.get(f"/api/channels/{news['id']}/logo").status_code == 404


def test_play_channel_uses_its_name_and_marks_the_command(client):
    news = add(client)
    response = client.post(f"/api/channels/{news['id']}/play")
    assert response.status_code == 200
    pending = client.app.state.hub.pending
    assert pending.title == "News 24"
    assert pending.channel_id == news["id"]
    assert pending.page_url == "https://site.example/video/news"
    assert client.post("/api/channels/nope/play").status_code == 404


def test_stream_reused_for_quick_channel_changes(client, extract):
    news = add(client)
    client.post(f"/api/channels/{news['id']}/play")
    client.post(f"/api/channels/{news['id']}/play")
    assert extract.calls == ["https://site.example/video/news"]


def test_stream_looked_up_again_after_the_tv_reports_an_error(client, extract):
    news = add(client)
    client.post(f"/api/channels/{news['id']}/play")
    pending = client.app.state.hub.pending
    client.post(
        "/api/tv/status",
        content=json.dumps({"command_id": pending.id, "state": "error", "message": "expired"}),
    )
    client.post(f"/api/channels/{news['id']}/play")
    assert len(extract.calls) == 2


def test_stream_cache_expires(client, extract, monkeypatch):
    news = add(client)
    client.post(f"/api/channels/{news['id']}/play")
    monkeypatch.setattr(server_module, "STREAM_CACHE_SECONDS", -1)
    client.post(f"/api/channels/{news['id']}/play")
    assert len(extract.calls) == 2


def test_changes_reach_the_hub_for_tvs_and_phones(client):
    news = add(client)
    assert client.app.state.hub.channels[0]["id"] == news["id"]
    client.delete(f"/api/channels/{news['id']}")
    assert client.app.state.hub.channels == []
