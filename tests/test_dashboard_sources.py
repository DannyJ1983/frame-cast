"""The dashboard's parsers, against answers shaped like the real services'."""

from datetime import datetime, timezone

import pytest

from dashboard_samples import ATOM, BBC_RSS, DEPARTURES, GEOCODE, OUTCODE, POSTCODE, TOMTOM, espn_scoreboard, open_meteo
from framecast.dashboard import news, places, sport, traffic, trains, weather

NOW = datetime(2026, 10, 16, 14, 20, tzinfo=timezone.utc)


def test_weather_forecast():
    result = weather.parse_forecast(open_meteo())
    assert result["now"] == {"temp": 14, "feels": 11, "wind_mph": 9, "text": "Light rain", "icon": "rain"}
    assert result["today"] == {"text": "Light rain", "icon": "rain", "high": 14, "low": 8, "rain_chance": 80,
                               "sunrise": "07:31", "sunset": "18:06"}
    assert result["tomorrow"]["text"] == "Cloudy" and result["tomorrow"]["high"] == 12
    # Every two hours for the next twelve, with night icons after dark.
    assert [h["time"] for h in result["hours"]] == ["16:00", "18:00", "20:00", "22:00", "00:00", "02:00"]
    assert [h["icon"] for h in result["hours"]] == ["cloud", "partly-night", "clear-night", "clear-night", "partly-night", "fog"]
    assert result["hours"][0]["rain_chance"] == 40


def test_weather_codes_and_odd_data():
    assert weather.describe(95) == ("Thunderstorms", "thunder")
    assert weather.describe(0, 0) == ("Clear", "clear-night")
    assert weather.describe(None) == ("", "cloud")
    minimal = weather.parse_forecast({"current": {"temperature_2m": 3}})
    assert minimal["now"]["temp"] == 3 and minimal["hours"] == [] and minimal["today"] is None
    with pytest.raises(KeyError):
        weather.parse_forecast({"error": True, "reason": "bad"})
    params = weather.forecast_params(53.79648, -1.54785)
    assert params["latitude"] == 53.796 and params["wind_speed_unit"] == "mph" and params["timezone"] == "auto"


def test_places():
    assert places.postcode_kind("ls1 4ap") == "full"
    assert places.postcode_kind("SW1A1AA") == "full"
    assert places.postcode_kind("WF1") == "outcode"
    assert places.postcode_kind("Leeds") is None
    assert places.place_request("ls1 4ap")[0] == "https://api.postcodes.io/postcodes/LS14AP"
    assert places.place_request("wf1")[0] == "https://api.postcodes.io/outcodes/WF1"
    url, params, parser = places.place_request(" Hebden Bridge ")
    assert parser == "geocode" and params["name"] == "Hebden Bridge" and params["countryCode"] == "GB"
    assert places.parse_postcode(POSTCODE) == places.Place("Leeds", 53.7965, -1.5478)
    assert places.parse_postcode(OUTCODE).name == "Wakefield"
    assert places.parse_geocode(GEOCODE).name == "Leeds"
    assert places.parse_geocode({"generationtime_ms": 0.1}) is None
    assert places.parse_postcode({"status": 404, "error": "Postcode not found"}) is None


def test_departures():
    board = trains.parse_departures(DEPARTURES)
    assert board["station"] == "Leeds"
    rows = board["services"]
    assert [r["time"] for r in rows] == ["14:25", "14:32", "14:35", "14:40", "14:45"]
    york, london, bus, manchester, plymouth = rows
    assert london == {"time": "14:32", "destination": "London Kings Cross", "via": "", "platform": "8",
                      "status": "On time", "state": "ok", "operator": "LNER", "reason": ""}
    assert york["status"] == "Exp 14:31" and york["state"] == "late" and york["via"] == "via Garforth"
    assert york["reason"].startswith("This train has been delayed")
    assert bus["platform"] == "Bus"
    assert manchester["destination"] == "Manchester Airport & Liverpool Lime Street"
    assert manchester["status"] == "Cancelled" and manchester["state"] == "cancelled"
    assert plymouth["status"] == "Delayed" and plymouth["state"] == "late" and plymouth["platform"] == ""
    assert board["messages"] == ["Disruption between York & Leeds."]


def test_departures_request_and_empty_board():
    url, params, headers = trains.departures_request("LDS", "KGX", "secret")
    assert url.endswith("/LDBWS/api/20220120/GetDepBoardWithDetails/LDS")
    assert params == {"numRows": 8, "filterCrs": "KGX", "filterType": "to"}
    assert headers == {"x-apikey": "secret"}
    assert trains.departures_request("LDS", "", "k")[1] == {"numRows": 8}
    # A quiet station at night has a board with no services.
    assert trains.parse_departures({"locationName": "Garforth"})["services"] == []
    with pytest.raises(KeyError):
        trains.parse_departures({"Message": "Unauthorized"})
    assert trains.valid_crs("KGX") and not trains.valid_crs("KG") and not trains.valid_crs("kgx")


def test_traffic_route():
    result = traffic.parse_route(TOMTOM)
    assert result == {"minutes": 28, "usual_minutes": 20, "delay_minutes": 7, "miles": 9.4, "state": "slow"}
    clear = {"routes": [{"summary": {"travelTimeInSeconds": 600, "trafficDelayInSeconds": 0, "lengthInMeters": 1000}}]}
    assert traffic.parse_route(clear)["state"] == "ok" and traffic.parse_route(clear)["usual_minutes"] == 10
    bad = {"routes": [{"summary": {"travelTimeInSeconds": 3000, "trafficDelayInSeconds": 1500}}]}
    assert traffic.parse_route(bad)["state"] == "bad"
    with pytest.raises((KeyError, IndexError)):
        traffic.parse_route({"routes": []})
    url, params = traffic.route_request((53.8, -1.55), (53.68, -1.5), "k")
    assert url.endswith("/calculateRoute/53.80000,-1.55000:53.68000,-1.50000/json")
    assert params["traffic"] == "true" and params["computeTravelTimeFor"] == "all" and params["key"] == "k"


def test_rss_and_atom_feeds():
    feed = news.parse_feed(BBC_RSS)
    assert feed["source"] == "BBC News"
    assert feed["headlines"] == [
        {"title": "Storm warning issued for northern England", "published": "2026-10-16T12:04:11+00:00"},
        {"title": "Rail fares to rise & services cut", "published": "2026-10-16T11:30:00+00:00"},
    ]
    atom = news.parse_feed(ATOM)
    assert atom["source"] == "Local Paper"
    assert atom["headlines"][1] == {"title": "Council votes on budget", "published": "2026-10-16T07:00:00+00:00"}
    assert len(news.parse_feed(BBC_RSS, limit=1)["headlines"]) == 1
    for broken in ("<html><body>Not a feed</body></html>", "not xml at all"):
        with pytest.raises(ValueError):
            news.parse_feed(broken)


def test_scoreboard():
    matches = sport.parse_scoreboard(espn_scoreboard(NOW), "eng.1", NOW, ["leeds"])
    by_home = {m["home"]: m for m in matches}
    assert "Fulham" not in by_home  # finished three days ago
    assert "Burnley" not in by_home  # more than a week away
    live = by_home["Arsenal"]
    assert live == {"league": "Premier League", "home": "Arsenal", "away": "Chelsea", "home_score": "2",
                    "away_score": "1", "state": "in", "detail": "67'", "kickoff": "2026-10-16T13:10+00:00",
                    "favourite": False}
    assert by_home["Leeds United"]["favourite"] and by_home["Spurs"]["favourite"]
    assert by_home["Spurs"]["detail"] == "" and by_home["Spurs"]["home_score"] == ""
    postponed = by_home["Newcastle"]
    assert postponed["detail"] == "Postponed" and postponed["home_score"] == ""
    ordered = [m["home"] for m in sport.order_matches(matches)]
    assert ordered == ["Arsenal", "Leeds United", "Newcastle", "Spurs", "Brighton"]


def test_scoreboard_copes_with_missing_parts():
    data = {"events": [{"id": "1"}, {"competitions": [{"competitors": [{"homeAway": "home"}]}]},
                       {"date": "nonsense", "competitions": [{"competitors": [
                           {"homeAway": "home", "team": {"abbreviation": "AAA"}}, {"homeAway": "away", "team": {}}]}]}]}
    matches = sport.parse_scoreboard(data, "eng.1", NOW)
    assert len(matches) == 1 and matches[0]["home"] == "AAA" and matches[0]["away"] == "?"
    assert sport.parse_scoreboard({}, "eng.1", NOW) == []
    assert sport.scoreboard_url("eng.1") == "https://site.api.espn.com/apis/site/v2/sports/soccer/eng.1/scoreboard"
    assert sport.scoreboard_url("nba").endswith("/basketball/nba/scoreboard")
    assert not sport.is_favourite(["Arsenal"], [])
