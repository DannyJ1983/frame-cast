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
            "time": ["2026-10-16", "2026-10-17", "2026-10-18", "2026-10-19"],
            "weather_code": [61, 3, 80, 1],
            "temperature_2m_max": [14.4, 12.1, 13.0, 15.2],
            "temperature_2m_min": [7.6, 6.2, 8.1, 9.0],
            "precipitation_probability_max": [80, 30, 65, 5],
            "sunrise": ["2026-10-16T07:31", "2026-10-17T07:33", "2026-10-18T07:34", "2026-10-19T07:36"],
            "sunset": ["2026-10-16T18:06", "2026-10-17T18:04", "2026-10-18T18:02", "2026-10-19T18:00"],
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

    async def download(self, url: str, path: Any, max_bytes: int) -> None:
        data = self._answer(url, None, None)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

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
        "https://data.bus-data.dft.gov.uk/timetable/": lambda: gtfs_zip(all_day_trips()),
        "https://data.bus-data.dft.gov.uk/api/v1/datafeed/":
            lambda: live_buses_for(all_day_trips(), datetime.now(timezone.utc)),
    }


# Buses ----------------------------------------------------------------------------------------
# A small GTFS timetable shaped like the Bus Open Data Service's (stop ids are ATCO codes, and
# agency.txt carries each operator's national code in agency_noc), and SIRI-VM answers to match.

import csv as _csv
import io as _io
import zipfile as _zipfile
from zoneinfo import ZoneInfo as _ZoneInfo

UK = _ZoneInfo("Europe/London")
BUS_STOPS = [
    # stop_id, stop_code, name, lat, lon
    ("149000000001", "brimaaa", "Hove Town Hall", 50.8300, -0.1500),
    ("149000000002", "brimaab", "Palmeira Square", 50.8300, -0.1450),
    ("149000006934", "brimgpd", "Churchill Square (Stop D)", 50.8300, -0.1400),
    ("149000000004", "brimaad", "Old Steine", 50.8300, -0.1350),
    ("149000000005", "brimaae", "Brighton Marina", 50.8300, -0.1300),
]
TARGET = "149000006934"


def _hms(total_seconds: int) -> str:
    return f"{total_seconds // 3600:02d}:{total_seconds % 3600 // 60:02d}:{total_seconds % 60:02d}"


def bus_trip(trip_id: str, route: str, start: str, service: str = "ALL", headsign: str = "",
             stops: list[str] | None = None, gap_minutes: int = 5) -> dict[str, Any]:
    """A journey leaving its first stop at ``start`` ("HH:MM", may pass 24:00), calling every ``gap_minutes``."""
    hours, minutes = (int(x) for x in start.split(":"))
    first = hours * 3600 + minutes * 60
    stop_ids = stops or [s[0] for s in BUS_STOPS]
    return {"id": trip_id, "route": route, "service": service, "headsign": headsign,
            "times": [(stop, first + i * gap_minutes * 60) for i, stop in enumerate(stop_ids)]}


def gtfs_zip(trips: list[dict[str, Any]], exceptions: list[tuple[str, str, int]] = (),
             trip_id_first: bool = True) -> bytes:
    """Build a GTFS file. ``exceptions`` are (service_id, YYYYMMDD, 1 added / 2 removed)."""
    def table(header: list[str], rows: list[list[Any]]) -> str:
        out = _io.StringIO()
        writer = _csv.writer(out, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
        return out.getvalue()

    stop_time_header = ["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence", "timepoint"]
    if not trip_id_first:
        stop_time_header = ["stop_sequence", "arrival_time", "departure_time", "stop_id", "trip_id", "timepoint"]
    stop_rows = []
    for trip in trips:
        for sequence, (stop, when) in enumerate(trip["times"], 1):
            values = {"trip_id": trip["id"], "arrival_time": _hms(when), "departure_time": _hms(when),
                      "stop_id": stop, "stop_sequence": sequence * 10, "timepoint": 1}
            stop_rows.append([values[h] for h in stop_time_header])
    stop_rows.reverse()  # the order in the file mustn't matter
    routes = sorted({t["route"] for t in trips})
    services = sorted({t["service"] for t in trips} - {"EXTRA"})
    files = {
        "agency.txt": table(["agency_id", "agency_name", "agency_url", "agency_timezone", "agency_noc"],
                            [["OP1", "Brighton & Hove Buses", "https://www.buses.co.uk", "Europe/London", "BHBC"]]),
        "routes.txt": table(["route_id", "agency_id", "route_short_name", "route_long_name", "route_type"],
                            [[f"R{r}", "OP1", r, "", 3] for r in routes]),
        "trips.txt": table(["route_id", "service_id", "trip_id", "trip_headsign", "vehicle_journey_code"],
                           [[f"R{t['route']}", t["service"], t["id"], t["headsign"], "VJ" + t["id"]] for t in trips]),
        "stops.txt": table(["stop_id", "stop_code", "stop_name", "stop_lat", "stop_lon", "wheelchair_boarding"],
                           [list(s) + [0] for s in BUS_STOPS]),
        "stop_times.txt": table(stop_time_header, stop_rows),
        "calendar.txt": table(["service_id", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
                               "sunday", "start_date", "end_date"],
                              [[s, 1, 1, 1, 1, 1, 1, 1, "20260101", "20271231"] for s in services]),
        "calendar_dates.txt": table(["service_id", "date", "exception_type"], [list(e) for e in exceptions]),
    }
    buffer = _io.BytesIO()
    with _zipfile.ZipFile(buffer, "w", _zipfile.ZIP_DEFLATED) as zf:
        for name, text in files.items():
            zf.writestr(name, "﻿" + text if name == "stops.txt" else text)
    return buffer.getvalue()


def all_day_trips() -> list[dict[str, Any]]:
    """Buses all day, so the sample shows departures whatever the time: the 7 every 10 minutes,
    the 14 every 15 and the 49 every 20."""
    trips = []
    for route, every, offset, headsign in (("7", 10, 0, "Brighton Marina"), ("14", 15, 3, "Peacehaven"),
                                           ("49", 20, 7, "East Moulsecoomb")):
        for start in range(offset, 24 * 60 + 30, every):
            trips.append(bus_trip(f"{route}-{start}", route, f"{start // 60}:{start % 60:02d}", headsign=headsign))
    return trips


def siri_vehicle(line: str, origin: str, destination: str, origin_time: datetime, destination_time: datetime,
                 recorded: datetime, lat: float | None, lon: float | None, operator: str = "BHBC") -> str:
    location = "" if lat is None else (
        f"<VehicleLocation><Longitude>{lon}</Longitude><Latitude>{lat}</Latitude></VehicleLocation>")
    return f"""
  <VehicleActivity>
    <RecordedAtTime>{recorded.isoformat()}</RecordedAtTime>
    <ItemIdentifier>{line}-{origin_time:%H%M}</ItemIdentifier>
    <MonitoredVehicleJourney>
      <LineRef>{line}</LineRef>
      <DirectionRef>outbound</DirectionRef>
      <FramedVehicleJourneyRef><DataFrameRef>{origin_time:%Y-%m-%d}</DataFrameRef><DatedVehicleJourneyRef>1</DatedVehicleJourneyRef></FramedVehicleJourneyRef>
      <PublishedLineName>{line}</PublishedLineName>
      <OperatorRef>{operator}</OperatorRef>
      <OriginRef>{origin}</OriginRef>
      <DestinationRef>{destination}</DestinationRef>
      <OriginAimedDepartureTime>{origin_time.isoformat()}</OriginAimedDepartureTime>
      <DestinationAimedArrivalTime>{destination_time.isoformat()}</DestinationAimedArrivalTime>
      {location}
      <Bearing>90.0</Bearing>
      <VehicleRef>{operator}-{line}{origin_time:%H%M}</VehicleRef>
    </MonitoredVehicleJourney>
  </VehicleActivity>"""


def siri(activities: list[str], when: datetime) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Siri xmlns="http://www.siri.org.uk/siri" version="2.0">
 <ServiceDelivery>
  <ResponseTimestamp>{when.isoformat()}</ResponseTimestamp>
  <ProducerRef>DepartmentForTransport</ProducerRef>
  <VehicleMonitoringDelivery>
   <ResponseTimestamp>{when.isoformat()}</ResponseTimestamp>
   {''.join(activities)}
  </VehicleMonitoringDelivery>
 </ServiceDelivery>
</Siri>"""


def live_buses_for(trips: list[dict[str, Any]], now: datetime, late_minutes: float = 2.0) -> str:
    """A live feed where every bus due at the target stop in the next quarter of an hour is running late."""
    places = {s[0]: (s[3], s[4]) for s in BUS_STOPS}
    local = now.astimezone(UK)
    midnight = datetime.combine(local.date(), datetime.min.time(), tzinfo=UK)
    activities = []
    for trip in trips:
        times = trip["times"]
        target = next(when for stop, when in times if stop == TARGET)
        due = midnight + timedelta(seconds=target)
        if not timedelta(minutes=0) < due - now < timedelta(minutes=15):
            continue
        should_be = (now - timedelta(minutes=late_minutes) - midnight).total_seconds()
        for (stop_a, at_a), (stop_b, at_b) in zip(times, times[1:]):
            if at_a <= should_be <= at_b:
                fraction = (should_be - at_a) / (at_b - at_a)
                lat = places[stop_a][0] + fraction * (places[stop_b][0] - places[stop_a][0])
                lon = places[stop_a][1] + fraction * (places[stop_b][1] - places[stop_a][1])
                activities.append(siri_vehicle(trip["route"], times[0][0], times[-1][0],
                                               midnight + timedelta(seconds=times[0][1]),
                                               midnight + timedelta(seconds=times[-1][1]), now, lat, lon))
                break
    return siri(activities, now)
