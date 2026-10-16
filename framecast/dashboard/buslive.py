"""Live bus estimates: match each bus's reported position to its timetabled journey and work out how late it is.

The Bus Open Data Service's SIRI-VM feed says where each bus is and which
journey it's running (its line, first and last stops, and their timetabled
times), but not when it'll reach your stop. So, like the Home Assistant
BODS Bus Tracker (github.com/IainPHay/home-assistant-bods-bus-tracker, MIT),
which this follows: match the bus to a journey in the timetable, find where
it is along that journey's stops, compare with where the timetable says it
should be by now, and carry that delay on to your stop.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .gtfs import service_start

FEED_URL = "https://data.bus-data.dft.gov.uk/api/v1/datafeed/"
MAX_AGE = timedelta(minutes=3)  # older positions are ignored
EXACT = timedelta(seconds=60)
FUZZY = timedelta(minutes=3)
_NS = {"s": "http://www.siri.org.uk/siri"}
EARTH_METRES = 6_371_000.0


@dataclass
class Vehicle:
    """One bus as the live feed reports it."""

    operator: str
    line: str
    origin: str
    destination: str
    origin_time: datetime
    destination_time: datetime
    recorded: datetime
    latitude: float
    longitude: float


def _text(node: ET.Element, path: str) -> str:
    found = node.find(path, _NS)
    return (found.text or "").strip() if found is not None and found.text else ""


def _when(text: str) -> datetime | None:
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else None


def parse_vehicles(xml_text: str) -> list[Vehicle]:
    """Read the buses in a SIRI-VM answer, skipping any without a position or timetable times."""
    root = ET.fromstring(xml_text)
    vehicles = []
    for activity in root.iter(f"{{{_NS['s']}}}VehicleActivity"):
        journey = activity.find("s:MonitoredVehicleJourney", _NS)
        if journey is None:
            continue
        origin_time = _when(_text(journey, "s:OriginAimedDepartureTime"))
        destination_time = _when(_text(journey, "s:DestinationAimedArrivalTime"))
        recorded = _when(_text(activity, "s:RecordedAtTime"))
        try:
            latitude = float(_text(journey, "s:VehicleLocation/s:Latitude"))
            longitude = float(_text(journey, "s:VehicleLocation/s:Longitude"))
        except ValueError:
            continue
        if origin_time is None or destination_time is None or recorded is None:
            continue
        vehicles.append(Vehicle(
            operator=_text(journey, "s:OperatorRef"),
            line=_text(journey, "s:LineRef"),
            origin=_text(journey, "s:OriginRef"),
            destination=_text(journey, "s:DestinationRef"),
            origin_time=origin_time,
            destination_time=destination_time,
            recorded=recorded,
            latitude=latitude,
            longitude=longitude,
        ))
    return vehicles


def _journey_ends(trip: dict[str, Any], start: datetime) -> tuple[datetime, datetime]:
    first, last = trip["stops"][0], trip["stops"][-1]
    return start + timedelta(seconds=first[2]), start + timedelta(seconds=last[1])


def match(vehicle: Vehicle, candidates: list[tuple[dict[str, Any], datetime]]) -> tuple[dict[str, Any], datetime] | None:
    """The one timetabled journey (with its service day's start) this bus is running, or None if unsure.

    Line, operator, first and last stops must agree, and the first and last
    timetabled times must be within a minute (or, failing that, three minutes
    with a clear winner).
    """
    scored = []
    for trip, start in candidates:
        if trip["route"] != vehicle.line or (trip["noc"] and vehicle.operator and trip["noc"] != vehicle.operator):
            continue
        if trip["stops"][0][0] != vehicle.origin or trip["stops"][-1][0] != vehicle.destination:
            continue
        leaves, arrives = _journey_ends(trip, start)
        gap = abs(leaves - vehicle.origin_time) + abs(arrives - vehicle.destination_time)
        if gap <= 2 * FUZZY:
            scored.append((gap, trip, start))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0])
    best = scored[0]
    exact = [item for item in scored if item[0] <= 2 * EXACT]
    if len(exact) > 1 or (len(scored) > 1 and scored[1][0] - best[0] < timedelta(seconds=1)):
        return None  # two journeys look the same; better to show the timetable than guess
    return best[1], best[2]


def _project(latitude: float, longitude: float, a: list[float], b: list[float]) -> tuple[float, float]:
    """Distance in metres from a point to the segment a-b, and how far along the segment (0 to 1) it falls."""
    scale = math.cos(math.radians(latitude))

    def xy(point: list[float]) -> tuple[float, float]:
        return (math.radians(point[1] - longitude) * EARTH_METRES * scale, math.radians(point[0] - latitude) * EARTH_METRES)

    ax, ay = xy(a)
    bx, by = xy(b)
    vx, vy = bx - ax, by - ay
    length = vx * vx + vy * vy
    fraction = 0.0 if length == 0 else max(0.0, min(1.0, -(ax * vx + ay * vy) / length))
    return math.hypot(ax + fraction * vx, ay + fraction * vy), fraction


def progress(vehicle: Vehicle, trip: dict[str, Any], start: datetime, places: dict[str, list[float]]) -> tuple[float, float] | None:
    """(minutes late, position along the journey's stops) for a bus, or None if it can't be placed.

    The position counts stops: 2.5 is halfway between the third and fourth.
    Negative minutes mean early.
    """
    options = []
    stops = trip["stops"]
    for index in range(len(stops) - 1):
        a, b = places.get(stops[index][0]), places.get(stops[index + 1][0])
        if a is None or b is None:
            continue
        distance, fraction = _project(vehicle.latitude, vehicle.longitude, a, b)
        due = stops[index][2] + fraction * (stops[index + 1][1] - stops[index][2])
        late = (vehicle.recorded - (start + timedelta(seconds=due))).total_seconds() / 60
        if -20 <= late <= 180:
            options.append((distance, late, index + fraction))
    if not options:
        return None
    _distance, late, where = min(options)
    return late, where


def apply_live(departures: list[dict[str, Any]], vehicles: list[Vehicle], index: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
    """Add live estimates to timetabled departures; drop journeys whose bus has already passed the stop."""
    candidates = {}
    for departure in departures:
        start = service_start(departure["day"])
        candidates[(departure["trip"]["id"], departure["day"])] = (departure["trip"], start)
    pool = list(candidates.values())
    live: dict[tuple[str, datetime], tuple[float, float]] = {}
    for vehicle in vehicles:
        if now - vehicle.recorded > MAX_AGE:
            continue
        found = match(vehicle, pool)
        if found is None:
            continue
        trip, start = found
        placed = progress(vehicle, trip, start, index["places"])
        if placed is not None:
            live[(trip["id"], start)] = placed

    result = []
    for departure in departures:
        start = service_start(departure["day"])
        estimate = live.get((departure["trip"]["id"], start))
        departure = dict(departure, expected=None, late=None)
        if estimate is not None:
            late, where = estimate
            if where >= departure["position"] + 0.05:
                continue  # the bus has gone
            expected = departure["scheduled"] + timedelta(minutes=late)
            if departure["position"] == 0 and expected < departure["scheduled"]:
                expected = departure["scheduled"]  # a bus waiting at the start of its route leaves on time
            if expected < now - timedelta(seconds=45):
                continue
            departure.update(expected=expected, late=late)
        result.append(departure)
    result.sort(key=lambda d: d["expected"] or d["scheduled"])
    return result
