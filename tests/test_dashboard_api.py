"""The dashboard's web routes."""

import json

from fastapi.testclient import TestClient

from framecast.server import create_app


def client(settings, fake_resolver, fake_dashboard):
    return TestClient(create_app(settings, resolver=fake_resolver, dashboard=fake_dashboard))


def test_dashboard_data(settings, fake_resolver, fake_dashboard):
    with client(settings, fake_resolver, fake_dashboard) as c:
        response = c.get("/api/dashboard")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        data = response.json()
        assert set(data["cards"]) == {"news", "sport"}
        assert len(data["page_version"]) == 10


def test_settings_round_trip(settings, fake_resolver, fake_dashboard):
    with client(settings, fake_resolver, fake_dashboard) as c:
        first = c.get("/api/dashboard/settings").json()
        assert first["settings"]["news"] == "bbc-top" and first["options"]["leagues"]
        reply = c.put("/api/dashboard/settings", json={"place": "LS1 4AP", "station": "LDS", "rail_key": "abc"})
        assert reply.status_code == 200 and reply.json()["settings"]["place_name"] == "Leeds"
        assert "abc" not in json.dumps(reply.json())  # the key never comes back
        assert set(c.get("/api/dashboard").json()["cards"]) == {"weather", "trains", "news", "sport"}
        bad = c.put("/api/dashboard/settings", json={"station": "nope"})
        assert bad.status_code == 400 and "three letters" in bad.json()["message"]
        assert c.put("/api/dashboard/settings", content=b"[1, 2]").status_code == 400


def test_show_on_tv(settings, fake_resolver, fake_dashboard):
    with client(settings, fake_resolver, fake_dashboard) as c:
        assert c.post("/api/dashboard/show").status_code == 409
        hub = c.app.state.hub
        queue = hub.subscribe_tv()
        assert c.post("/api/dashboard/show").status_code == 200
        events = []
        while not queue.empty():
            events.append(queue.get_nowait())
        assert ("show", {"screen": "dashboard"}) in events


def test_page_is_served(settings, fake_resolver, fake_dashboard):
    with client(settings, fake_resolver, fake_dashboard) as c:
        assert c.get("/dashboard/").status_code == 200
        assert c.get("/dashboard", follow_redirects=True).status_code == 200
