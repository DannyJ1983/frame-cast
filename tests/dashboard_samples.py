"""Sample answers shaped like the dashboard's real data sources, and a fake fetcher that serves them.

The shapes follow each service's documentation (Open-Meteo, postcodes.io, Darwin LDBWS through
the Rail Data Marketplace, TomTom Routing, RSS/Atom, and community notes on ESPN's scoreboards).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from framecast.dashboard.fetch import FetchError


def open_meteo() -> dict[str, Any]:
    hours = [f"2026-10-16T{h:02d}:00" for h in range(14, 27)]
    hours = [h if int(h[11:13]) < 24 else f"2026-10-17T{int(h[11:13]) - 24:02d}:00" for h in hours]
    return {
        "latitude": 53.8,
        "longitude": -1.55,
        "timezone": "Europe/London",
        "current": {"time": "2026-10-16T14:15", "interval": 900, "temperature_2m": 13.6,
                    "apparent_temperature": 11.2, "weather_code": 61, "is_day": 1, "wind_speed_10m": 9.4},
        "hourly": {
            "time": hours,
            "temperature_2m": [13.6, 13.9, 13.1, 12.0, 11.2, 10.4, 9.9, 9.5, 9.1, 8.8, 8.4, 8.0, 7.7],
            "weather_code": [61, 61, 3, 2, 2, 1, 0, 0, 0, 1, 2, 3, 45],
            "precipitation_probability": [80, 70, 40, 20, 10, 5, 0, 0, 0, 5, 10, 15, 20],
            "is_day": [1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        },
        "daily": {
            "time": ["2026-10-16", "2026-10-17"],
            "weather_code": [61, 3],
            "temperature_2m_max": [14.4, 12.1],
            "temperature_2m_min": [7.6, 6.2],
            "precipitation_probability_max": [80, 30],
            "sunrise": ["2026-10-16T07:31", "2026-10-17T07:33"],
            "sunset": ["2026-10-16T18:06", "2026-10-17T18:04"],
        },
    }


POSTCODE = {"status": 200, "result": {"postcode": "LS1 4AP", "latitude": 53.7965, "longitude": -1.5478,
                                      "admin_district": "Leeds", "country": "England"}}
OUTCODE = {"status": 200, "result": {"outcode": "WF1", "latitude": 53.683, "longitude": -1.499,
                                     "admin_district": ["Wakefield"]}}
GEOCODE = {"results": [{"id": 2644688, "name": "Leeds", "latitude": 53.79648, "longitude": -1.54785,
                        "country_code": "GB", "admin1": "England"}]}

DEPARTURES = {
    "generatedAt": "2026-10-16T14:20:31.123+01:00",
    "locationName": "Leeds",
    "crs": "LDS",
    "platformAvailable": True,
    "nrccMessages": [{"Value": "Disruption between <a href=\"x\">York &amp; Leeds</a>."}],
    "trainServices": [
        {"std": "14:32", "etd": "On time", "platform": "8", "operator": "LNER", "isCancelled": False,
         "destination": [{"locationName": "London Kings Cross", "crs": "KGX", "via": None}]},
        {"std": "14:25", "etd": "14:31", "platform": "12", "operator": "Northern",
         "delayReason": "This train has been delayed by a signalling fault",
         "destination": [{"locationName": "York", "crs": "YRK", "via": "via Garforth"}]},
        {"std": "14:40", "etd": "Cancelled", "isCancelled": True, "operator": "TransPennine Express",
         "cancelReason": "This train has been cancelled because of a shortage of train crew",
         "destination": [{"locationName": "Manchester Airport", "crs": "MIA"},
                         {"locationName": "Liverpool Lime Street", "crs": "LIV"}]},
        {"std": "14:45", "etd": "Delayed", "platform": None, "operator": "CrossCountry",
         "destination": [{"locationName": "Plymouth", "crs": "PLY"}]},
    ],
    "busServices": [
        {"std": "14:35", "etd": "On time", "operator": "Northern",
         "destination": [{"locationName": "Harrogate", "crs": "HGT"}]},
    ],
}

TOMTOM = {"formatVersion": "0.0.12", "routes": [{"summary": {
    "lengthInMeters": 15127, "travelTimeInSeconds": 1690, "trafficDelayInSeconds": 410,
    "trafficLengthInMeters": 2200, "departureTime": "2026-10-16T14:20:00+01:00",
    "arrivalTime": "2026-10-16T14:48:10+01:00", "noTrafficTravelTimeInSeconds": 1230,
    "historicTrafficTravelTimeInSeconds": 1400, "liveTrafficIncidentsTravelTimeInSeconds": 1690,
}}]}

BBC_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:content="http://purl.org/rss/1.0/modules/content/"
     xmlns:atom="http://www.w3.org/2005/Atom" version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
  <channel>
    <title><![CDATA[BBC News]]></title>
    <description><![CDATA[BBC News - News Front Page]]></description>
    <link>https://www.bbc.co.uk/news</link>
    <item>
      <title><![CDATA[Storm warning issued for northern England]]></title>
      <description><![CDATA[Gusts of up to 70mph are expected.]]></description>
      <link>https://www.bbc.co.uk/news/articles/c1</link>
      <guid isPermaLink="false">https://www.bbc.co.uk/news/articles/c1#0</guid>
      <pubDate>Fri, 16 Oct 2026 12:04:11 GMT</pubDate>
      <media:thumbnail width="240" height="135" url="https://ichef.bbci.co.uk/x.jpg"/>
    </item>
    <item>
      <title><![CDATA[Rail fares to rise &amp; services cut]]></title>
      <link>https://www.bbc.co.uk/news/articles/c2</link>
      <pubDate>Fri, 16 Oct 2026 11:30:00 GMT</pubDate>
    </item>
    <item>
      <title><![CDATA[Storm warning issued for northern England]]></title>
      <pubDate>Fri, 16 Oct 2026 10:00:00 GMT</pubDate>
    </item>
    <item><title></title></item>
  </channel>
</rss>
"""

ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Local Paper</title>
  <entry><title>Bridge reopens after repairs</title><updated>2026-10-16T09:15:00Z</updated></entry>
  <entry><title type="html">Council &lt;b&gt;votes&lt;/b&gt; on budget</title><published>2026-10-16T08:00:00+01:00</published></entry>
</feed>
"""


def _event(home: str, away: str, when: datetime, state: str, detail: str = "", scores=("", ""),
           completed: bool = True) -> dict[str, Any]:
    return {
        "id": f"{home}-{away}",
        "date": when.strftime("%Y-%m-%dT%H:%MZ"),
        "name": f"{away} at {home}",
        "status": {"clock": 0, "displayClock": "0'", "type": {
            "state": state, "completed": completed and state == "post", "detail": detail, "shortDetail": detail}},
        "competitions": [{"competitors": [
            {"homeAway": "home", "score": scores[0], "team": {"displayName": home, "shortDisplayName": home, "abbreviation": home[:3].upper()}},
            {"homeAway": "away", "score": scores[1], "team": {"displayName": away, "shortDisplayName": away, "abbreviation": away[:3].upper()}},
        ]}],
    }


def espn_scoreboard(now: datetime) -> dict[str, Any]:
    return {"leagues": [{"name": "English Premier League", "abbreviation": "Prem"}], "events": [
        _event("Arsenal", "Chelsea", now - timedelta(minutes=70), "in", "67'", ("2", "1")),
        _event("Leeds United", "Everton", now - timedelta(hours=20), "post", "FT", ("3", "0")),
        _event("Fulham", "Brentford", now - timedelta(days=3), "post", "FT", ("1", "1")),
        _event("Spurs", "Leeds United", now + timedelta(days=2), "pre", "Sat, October 18th at 10:00 AM EDT"),
        _event("Brighton", "Wolves", now + timedelta(days=1), "pre", "Sat"),
        _event("Burnley", "Villa", now + timedelta(days=20), "pre", "later"),
        _event("Newcastle", "Forest", now - timedelta(hours=2), "post", "Postponed", ("0", "0"), completed=False),
    ]}


class FakeFetcher:
    """Serves canned answers by address prefix. A value that's an exception is raised instead."""

    def __init__(self, routes: dict[str, Any] | None = None) -> None:
        self.routes = dict(routes or {})
        self.calls: list[tuple[str, Any, Any]] = []

    def _answer(self, url: str, params: Any, headers: Any) -> Any:
        self.calls.append((url, params, headers))
        for prefix in sorted(self.routes, key=len, reverse=True):
            if url.startswith(prefix):
                answer = self.routes[prefix]
                answer = answer() if callable(answer) else answer
                if isinstance(answer, Exception):
                    raise answer
                return answer
        raise FetchError(f"no fake answer for {url}", 404)

    async def json(self, url: str, params: Any = None, headers: Any = None) -> Any:
        return self._answer(url, params, headers)

    async def text(self, url: str, params: Any = None, headers: Any = None) -> str:
        return self._answer(url, params, headers)

    async def aclose(self) -> None:
        pass


def working_routes() -> dict[str, Any]:
    """A fake internet where every source answers."""
    return {
        "https://api.open-meteo.com/": open_meteo,
        "https://api.postcodes.io/postcodes/": POSTCODE,
        "https://api.postcodes.io/outcodes/": OUTCODE,
        "https://geocoding-api.open-meteo.com/": GEOCODE,
        "https://api1.raildata.org.uk/": DEPARTURES,
        "https://api.tomtom.com/": TOMTOM,
        "https://feeds.bbci.co.uk/news/": BBC_RSS,
        "https://feeds.bbci.co.uk/sport/": BBC_RSS,
        "https://site.api.espn.com/": lambda: espn_scoreboard(datetime.now(timezone.utc)),
    }
