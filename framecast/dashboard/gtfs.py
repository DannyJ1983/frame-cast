"""Bus timetables from GTFS files: keep just the journeys that call at your stops, then list departures.

The Bus Open Data Service publishes every English operator's timetable as
GTFS, one file per region. Those files are large, so ``build_index`` reads
``stop_times.txt`` as a stream, twice: once to find the journeys calling at
your stops, and once to collect every stop on those journeys (live estimates
need the whole route). The result is small and saved as JSON.

Times in GTFS count from "noon minus twelve hours" on the service day, so
they can pass 24:00 and stay right on the days the clocks change.
"""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator
from zoneinfo import ZoneInfo

UK = ZoneInfo("Europe/London")
INDEX_FORMAT = 1
DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


class GtfsError(ValueError):
    """The timetable couldn't be read, or doesn't have the stop. The message is for the person reading it."""


def _rows(zf: zipfile.ZipFile, name: str) -> Iterator[dict[str, str]]:
    if name not in zf.namelist():
        return iter(())
    handle = io.TextIOWrapper(zf.open(name), encoding="utf-8-sig", newline="")
    return csv.DictReader(handle)


def _lines(zf: zipfile.ZipFile, name: str) -> tuple[list[str], Iterator[str]]:
    handle = io.TextIOWrapper(zf.open(name), encoding="utf-8-sig", newline="")
    header = next(csv.reader([handle.readline()]))
    return [h.strip() for h in header], handle


def seconds(text: str) -> int:
    """"25:10:00" -> 90600."""
    hours, minutes, secs = (int(part) for part in text.strip().split(":"))
    return hours * 3600 + minutes * 60 + secs


def find_stops(zf: zipfile.ZipFile, codes: list[str]) -> dict[str, str]:
    """Map each code (an ATCO code or a stop's NaPTAN code) to its GTFS stop id. Raises GtfsError if one is missing."""
    wanted = {code.upper(): code for code in codes}
    found: dict[str, str] = {}
    for row in _rows(zf, "stops.txt"):
        for column in ("stop_id", "stop_code"):
            value = (row.get(column) or "").strip().upper()
            if value in wanted and wanted[value] not in found:
                found[wanted[value]] = row["stop_id"].strip()
    missing = [code for code in codes if code not in found]
    if missing:
        raise GtfsError(
            f"Couldn't find bus stop {', '.join(missing)} in the timetable. Check the code, "
            "and the region in the dashboard settings."
        )
    return found


def build_index(path: Path, codes: list[str]) -> dict[str, Any]:
    """Read a GTFS file and keep what's needed for departures from the stops with these codes."""
    try:
        zf = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as err:
        raise GtfsError("The bus timetable file is damaged; it'll be downloaded again.") from err
    with zf:
        if "stop_times.txt" not in zf.namelist():
            raise GtfsError("The bus timetable file is incomplete; it'll be downloaded again.")
        stop_ids = find_stops(zf, codes)
        targets = set(stop_ids.values())

        # Pass 1: journeys that call at one of the stops.
        header, lines = _lines(zf, "stop_times.txt")
        trip_col, stop_col = header.index("trip_id"), header.index("stop_id")
        calling: set[str] = set()
        for line in lines:
            if not any(target in line for target in targets):
                continue
            row = next(csv.reader([line]))
            if len(row) > stop_col and row[stop_col].strip() in targets:
                calling.add(row[trip_col].strip())

        trips: dict[str, dict[str, Any]] = {}
        for row in _rows(zf, "trips.txt"):
            trip_id = row["trip_id"].strip()
            if trip_id in calling:
                trips[trip_id] = {
                    "id": trip_id,
                    "route_id": row.get("route_id", "").strip(),
                    "service": row.get("service_id", "").strip(),
                    "headsign": (row.get("trip_headsign") or "").strip(),
                    "stops": [],
                }

        # Pass 2: every stop on those journeys, in order.
        header, lines = _lines(zf, "stop_times.txt")
        columns = {name: header.index(name) for name in ("trip_id", "stop_id", "arrival_time", "departure_time", "stop_sequence")}
        simple_trip = columns["trip_id"] == 0
        for line in lines:
            if simple_trip and line.split(",", 1)[0].strip('"') not in trips:
                continue
            row = next(csv.reader([line]))
            trip = trips.get(row[columns["trip_id"]].strip())
            if trip is None:
                continue
            try:
                trip["stops"].append([
                    int(row[columns["stop_sequence"]]),
                    row[columns["stop_id"]].strip(),
                    seconds(row[columns["arrival_time"]] or row[columns["departure_time"]]),
                    seconds(row[columns["departure_time"]] or row[columns["arrival_time"]]),
                ])
            except (ValueError, IndexError):
                trip["bad"] = True

        routes: dict[str, tuple[str, str]] = {}
        agency_noc: dict[str, str] = {}
        for row in _rows(zf, "agency.txt"):
            agency_id = row.get("agency_id", "").strip()
            agency_noc[agency_id] = (row.get("agency_noc") or agency_id).strip()
        for row in _rows(zf, "routes.txt"):
            name = (row.get("route_short_name") or row.get("route_long_name") or "").strip()
            routes[row["route_id"].strip()] = (name, agency_noc.get(row.get("agency_id", "").strip(), ""))

        needed = {stop[1] for trip in trips.values() for stop in trip["stops"]}
        places: dict[str, list[float]] = {}
        names: dict[str, str] = {}
        for row in _rows(zf, "stops.txt"):
            stop_id = row["stop_id"].strip()
            if stop_id in needed:
                try:
                    places[stop_id] = [round(float(row["stop_lat"]), 6), round(float(row["stop_lon"]), 6)]
                except (KeyError, ValueError):
                    pass
                names[stop_id] = (row.get("stop_name") or stop_id).strip()

        services = {trip["service"] for trip in trips.values()}
        calendar: dict[str, dict[str, Any]] = {}
        for row in _rows(zf, "calendar.txt"):
            if row["service_id"].strip() in services:
                calendar[row["service_id"].strip()] = {
                    "start": row["start_date"].strip(),
                    "end": row["end_date"].strip(),
                    "days": [row.get(day, "0").strip() == "1" for day in DAYS],
                }
        exceptions: dict[str, dict[str, int]] = {}
        for row in _rows(zf, "calendar_dates.txt"):
            service = row["service_id"].strip()
            if service in services:
                exceptions.setdefault(service, {})[row["date"].strip()] = int(row["exception_type"])

    kept = []
    for trip in trips.values():
        if trip.pop("bad", False) or len(trip["stops"]) < 2:
            continue
        trip["stops"].sort(key=lambda stop: stop[0])
        trip["stops"] = [stop[1:] for stop in trip["stops"]]
        route, noc = routes.get(trip.pop("route_id"), ("", ""))
        last = trip["stops"][-1][0]
        trip.update(route=route, noc=noc, headsign=trip["headsign"] or names.get(last, last))
        kept.append(trip)
    return {
        "format": INDEX_FORMAT,
        "codes": codes,
        "targets": {code: stop_ids[code] for code in codes},
        "target_names": {stop_ids[code]: names.get(stop_ids[code], code) for code in codes},
        "trips": kept,
        "places": places,
        "calendar": calendar,
        "exceptions": exceptions,
    }


def runs_on(index: dict[str, Any], service: str, day: date) -> bool:
    """True if the timetable's service runs on ``day``, allowing for bank holidays and other exceptions."""
    stamp = day.strftime("%Y%m%d")
    exception = index["exceptions"].get(service, {}).get(stamp)
    if exception is not None:
        return exception == 1
    pattern = index["calendar"].get(service)
    return bool(pattern and pattern["start"] <= stamp <= pattern["end"] and pattern["days"][day.weekday()])


def service_start(day: date) -> datetime:
    """The moment GTFS times on ``day`` count from (noon minus twelve hours), in UTC."""
    return datetime.combine(day, time(12), tzinfo=UK).astimezone(timezone.utc) - timedelta(hours=12)


def departures(
    index: dict[str, Any], now: datetime, horizon: timedelta = timedelta(hours=2), lines: set[str] | None = None
) -> list[dict[str, Any]]:
    """Timetabled departures from the index's stops between a minute ago and ``horizon`` from ``now``.

    Journeys that end at the stop are left out, since nobody can board them.
    """
    targets = set(index["targets"].values())
    found = []
    local_today = now.astimezone(UK).date()
    for day in (local_today - timedelta(days=1), local_today):
        start = service_start(day)
        for trip in index["trips"]:
            if lines and trip["route"].upper() not in lines:
                continue
            if not runs_on(index, trip["service"], day):
                continue
            for position, (stop_id, _arrival, departure) in enumerate(trip["stops"][:-1]):
                if stop_id not in targets:
                    continue
                when = start + timedelta(seconds=departure)
                if now - timedelta(minutes=1) <= when <= now + horizon:
                    found.append({
                        "trip": trip,
                        "day": day,
                        "stop": stop_id,
                        "position": position,
                        "scheduled": when,
                    })
    found.sort(key=lambda d: d["scheduled"])
    return found
