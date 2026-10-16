"""The dashboard service: settings, caching, refreshing and failures."""

import asyncio
import json
import stat
from datetime import datetime, timezone

import pytest

from dashboard_samples import FakeFetcher, working_routes
from framecast.dashboard import DashboardError, DashboardService, DashboardStore
from framecast.dashboard.fetch import FetchError

NOW = datetime(2026, 10, 16, 14, 20, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make(tmp_path, routes=None):
    fetcher = FakeFetcher(working_routes() if routes is None else routes)
    clock = Clock()
    service = DashboardService(DashboardStore(tmp_path), fetcher, clock=clock, now=lambda: NOW)
    return service, fetcher, clock


def run(coro):
    return asyncio.run(coro)


async def settle(service):
    """Let background refreshes finish."""
    for _ in range(100):
        if not any(card.task for card in service._cards.values()):
            return
        await asyncio.sleep(0)
    raise AssertionError("refreshes didn't finish")


FULL = {
    "place": "LS1 4AP", "station": "lds", "station_to": "", "rail_key": "rail-secret",
    "traffic_to": "WF1", "traffic_label": "Work", "traffic_key": "tomtom-secret",
    "news": "bbc-uk", "leagues": ["eng.1", "nba", "made.up"], "teams": "Leeds, ",
}


def test_fresh_dashboard_has_news_and_sport_only(tmp_path):
    service, fetcher, _ = make(tmp_path)
    snap = run(service.snapshot())
    assert set(snap["cards"]) == {"news", "sport"}
    assert snap["setup"]["weather"] is False
    assert snap["cards"]["news"]["data"]["source"] == "BBC News"
    matches = snap["cards"]["sport"]["data"]["matches"]
    assert matches[0]["home"] == "Arsenal" and matches[0]["state"] == "in"


def test_settings_are_looked_up_saved_and_keys_kept_private(tmp_path):
    service, fetcher, _ = make(tmp_path)
    public = run(service.update_settings(FULL))
    assert public["place_name"] == "Leeds" and public["latitude"] == 53.7965
    assert public["traffic_to_name"] == "Wakefield" and public["traffic_label"] == "Work"
    assert public["station"] == "LDS" and public["leagues"] == ["eng.1", "nba"] and public["teams"] == "Leeds,"
    assert public["has_rail_key"] and public["has_traffic_key"]
    assert "rail_key" not in public and "traffic_key" not in public
    saved = tmp_path / "dashboard.json"
    assert json.loads(saved.read_text())["rail_key"] == "rail-secret"
    assert stat.S_IMODE(saved.stat().st_mode) == 0o600
    # A new service reads them back.
    again = DashboardStore(tmp_path).settings
    assert again.station == "LDS" and again.traffic_key == "tomtom-secret"
    # Leaving a key out keeps it; an empty one removes it; an unchanged place isn't looked up again.
    lookups = len(fetcher.calls)
    public = run(service.update_settings({"place": "LS1 4AP", "station_to": "KGX", "traffic_key": ""}))
    assert len(fetcher.calls) == lookups
    assert public["has_rail_key"] and not public["has_traffic_key"] and public["station_to"] == "KGX"


def test_full_snapshot(tmp_path):
    service, fetcher, _ = make(tmp_path)
    run(service.update_settings(FULL))
    snap = run(service.snapshot())
    assert set(snap["cards"]) == {"weather", "trains", "traffic", "news", "sport"}
    assert snap["place"] == "Leeds" and snap["traffic_label"] == "Work"
    assert snap["cards"]["weather"]["data"]["now"]["temp"] == 14
    assert snap["cards"]["trains"]["data"]["services"][0]["time"] == "14:25"
    assert snap["cards"]["traffic"]["data"]["minutes"] == 28
    rail = next(c for c in fetcher.calls if "raildata" in c[0])
    assert rail[2] == {"x-apikey": "rail-secret"} and rail[0].endswith("/LDS")
    news_call = next(c for c in fetcher.calls if "bbci" in c[0])
    assert news_call[0] == "https://feeds.bbci.co.uk/news/uk/rss.xml"
    favourite = [m for m in snap["cards"]["sport"]["data"]["matches"] if m["favourite"]]
    assert favourite and all("Leeds" in m["home"] + m["away"] for m in favourite)


def test_cards_are_cached_until_due(tmp_path):
    service, fetcher, clock = make(tmp_path)
    run(service.update_settings(FULL))

    async def twice():
        await service.snapshot()
        before = len(fetcher.calls)
        await service.snapshot()
        assert len(fetcher.calls) == before  # nothing due yet
        clock.t += 61  # trains (every minute) and live sport are due; weather and news aren't
        await service.snapshot()
        await settle(service)
        return [c[0] for c in fetcher.calls[before:]]

    refreshed = run(twice())
    assert any("raildata" in u for u in refreshed) and any("espn" in u for u in refreshed)
    assert not any("open-meteo" in u for u in refreshed) and not any("bbci" in u for u in refreshed)


def test_a_failing_card_says_so_and_keeps_old_data(tmp_path):
    routes = working_routes()
    service, fetcher, clock = make(tmp_path, routes)
    run(service.update_settings(FULL))

    async def go():
        first = await service.snapshot()
        assert first["cards"]["trains"]["error"] is None
        routes["https://api1.raildata.org.uk/"] = FetchError("down", 503)
        fetcher.routes = routes
        clock.t += 61
        await service.snapshot()
        await settle(service)
        return await service.snapshot()

    snap = run(go())
    trains = snap["cards"]["trains"]
    assert trains["error"] == "Couldn't get the train times just now."
    assert trains["data"]["station"] == "Leeds"  # the last good board stays up
    assert snap["cards"]["weather"]["error"] is None


def test_refused_keys_get_a_helpful_message(tmp_path):
    routes = working_routes()
    routes["https://api1.raildata.org.uk/"] = FetchError("no", 401)
    routes["https://api.tomtom.com/"] = FetchError("no", 403)
    service, _, _ = make(tmp_path, routes)
    run(service.update_settings(FULL))
    snap = run(service.snapshot())
    assert "train data key wasn't accepted" in snap["cards"]["trains"]["error"]
    assert snap["cards"]["trains"]["data"] is None
    assert "TomTom key wasn't accepted" in snap["cards"]["traffic"]["error"]


def test_sport_falls_back_to_headlines_and_survives_a_bad_league(tmp_path):
    routes = working_routes()
    routes["https://site.api.espn.com/"] = {"events": []}
    service, _, _ = make(tmp_path, routes)
    data = run(service.snapshot())["cards"]["sport"]["data"]
    assert data["matches"] == [] and data["headlines"][0]["title"].startswith("Storm warning")
    routes["https://site.api.espn.com/apis/site/v2/sports/soccer/eng.1/"] = FetchError("gone", 404)
    service, _, _ = make(tmp_path, routes)
    run(service.update_settings({"leagues": ["eng.1", "eng.2"]}))
    data = run(service.snapshot())["cards"]["sport"]
    assert data["error"] is None and data["data"]["headlines"]


def test_bad_settings_are_refused(tmp_path):
    routes = working_routes()
    routes["https://api.postcodes.io/postcodes/"] = FetchError("not found", 404)
    routes["https://geocoding-api.open-meteo.com/"] = {"generationtime_ms": 0.2}
    service, _, _ = make(tmp_path, routes)
    for data, message in [
        ({"place": "ZZ9 9ZZ"}, "Couldn't find “ZZ9 9ZZ”"),
        ({"place": "Nowhereville"}, "Couldn't find “Nowhereville”"),
        ({"station": "KINGS"}, "three letters"),
        ({"station": "K1X"}, "three letters"),
        ({"news": "tabloid"}, "Pick a news source"),
        ({"news": "custom"}, "address of the news feed"),
        ({"news": "custom", "news_url": "ftp://x"}, "should start with http"),
    ]:
        with pytest.raises(DashboardError, match=message):
            run(service.update_settings(data))
    assert not (tmp_path / "dashboard.json").exists()  # nothing half-saved
    public = run(service.update_settings({"news": "custom", "news_url": "https://paper.example/feed"}))
    assert public["news"] == "custom"


def test_clearing_the_place_turns_weather_off(tmp_path):
    service, _, _ = make(tmp_path)
    run(service.update_settings(FULL))
    public = run(service.update_settings({"place": ""}))
    assert public["latitude"] is None and public["place_name"] == ""
    assert service.enabled() == ["trains", "news", "sport"]


def test_broken_settings_file_is_set_aside(tmp_path):
    (tmp_path / "dashboard.json").write_text("{not json")
    store = DashboardStore(tmp_path)
    assert store.settings.leagues == ["eng.1"]
    assert (tmp_path / "dashboard.broken.json").exists()


def test_options_list_feeds_and_leagues(tmp_path):
    service, _, _ = make(tmp_path)
    options = service.options()
    assert {"id": "bbc-top", "name": "BBC News: top stories"} in options["news"]
    assert {"id": "eng.1", "name": "Premier League"} in options["leagues"]
