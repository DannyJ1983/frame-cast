"""Bus times for the dashboard: the timetable from the Bus Open Data Service, plus live estimates with a key.

The regional timetable is a big download (hundreds of megabytes), so it's
fetched in the background, kept for a week, and boiled down to an index of
the journeys calling at your stops. Until that's ready the card says it's
getting the timetable. Live positions need a free BODS key; without one, or
if the live feed fails, the card shows timetabled times.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from . import buslive, gtfs
from .fetch import Fetcher, FetchError
from .settings import DashboardError, DashboardSettings

log = logging.getLogger(__name__)

TIMETABLE_URL = "https://data.bus-data.dft.gov.uk/timetable/download/gtfs-file/{}/"
TIMETABLE_MAX_BYTES = 2 * 1024 ** 3
TIMETABLE_DAYS = 7
RETRY_SECONDS = 1800.0  # after a failed download or index, wait this long before trying again
MAX_ROWS = 8
MAX_STOPS = 3
MAX_OPERATORS = 3
# BODS timetable regions, with rough centres for picking one from your postcode.
REGIONS: dict[str, tuple[str, float, float]] = {
    "south_east": ("South East", 51.20, 0.15),
    "london": ("London", 51.51, -0.12),
    "south_west": ("South West", 50.90, -3.00),
    "east_anglia": ("East Anglia", 52.30, 0.35),
    "east_midlands": ("East Midlands", 52.95, -1.10),
    "west_midlands": ("West Midlands", 52.50, -2.00),
    "north_west": ("North West", 53.65, -2.70),
    "north_east": ("North East", 54.95, -1.60),
    "yorkshire": ("Yorkshire", 53.80, -1.50),
}
# ATCO codes start with a three-digit area number (Brighton & Hove's is 149); NaPTAN codes are 7 or 8 characters.
_CODE = re.compile(r"^(\d{3}[0-9A-Za-z]{4,11}|[A-Za-z]{3}[A-Za-z0-9]{4,5})$")
_LINE = re.compile(r"^[A-Za-z0-9]{1,6}$")
PREPARING = "Getting the bus timetable ready. The first time takes a few minutes."


def nearest_region(latitude: float, longitude: float) -> str:
    """The BODS region whose centre is closest. Rough, but right for most places; it can be set by hand."""
    def distance(item: tuple[str, tuple[str, float, float]]) -> float:
        _, (_, lat, lon) = item
        return math.hypot(lat - latitude, (lon - longitude) * math.cos(math.radians(latitude)))

    return min(REGIONS.items(), key=distance)[0]


def split_codes(text: str, pattern: re.Pattern[str], limit: int, what: str) -> list[str]:
    """Split "a, b c" into codes, checking each against ``pattern``. Raises DashboardError on a bad one."""
    codes = [code for code in re.split(r"[\s,]+", text.strip()) if code]
    for code in codes:
        if not pattern.match(code):
            raise DashboardError(f"“{code}” doesn't look like {what}.")
    if len(codes) > limit:
        raise DashboardError(f"That's more than {limit}; pick the ones you use most.")
    return codes


def stop_codes(text: str) -> list[str]:
    """Bus stop codes from the settings: ATCO codes such as 149000006934, or NaPTAN codes."""
    return split_codes(text, _CODE, MAX_STOPS, "a bus stop code (the number in your stop's address on buses.co.uk)")


def line_names(text: str) -> list[str]:
    """Bus numbers from the settings, such as "7, 14, N7"."""
    return [line.upper() for line in split_codes(text, _LINE, 20, "a bus number")]


def rows(departures: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    """Departures as the page shows them: live ones in minutes, timetabled ones as clock times."""
    shown = []
    for departure in departures[:MAX_ROWS]:
        expected = departure["expected"]
        minutes = None if expected is None else max(0, math.floor((expected - now).total_seconds() / 60))
        shown.append({
            "route": departure["trip"]["route"],
            "destination": departure["trip"]["headsign"],
            "time": departure["scheduled"].astimezone(gtfs.UK).strftime("%H:%M"),
            "minutes": minutes,
            "live": expected is not None,
            "late": None if departure["late"] is None else round(departure["late"]),
        })
    return shown


class BusTimes:
    """Keeps the timetable and the stop index on disk, and answers the dashboard's bus card."""

    def __init__(
        self, folder: Path, fetcher: Fetcher, now: Callable[[], datetime], clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.folder = Path(folder) / "buses"
        self.fetcher = fetcher
        self._now = now
        self._clock = clock
        self._job: asyncio.Task[None] | None = None
        self._job_key: tuple[str, tuple[str, ...]] | None = None
        self._error: str | None = None
        self._failed_at: float | None = None
        self._index: dict[str, Any] | None = None
        self._index_key: tuple[str, tuple[str, ...], float] | None = None

    @property
    def busy(self) -> bool:
        """True while the timetable is being downloaded or indexed."""
        return self._job is not None

    def region(self, settings: DashboardSettings) -> str:
        """The timetable region to use."""
        if settings.bus_region in REGIONS:
            return settings.bus_region
        if settings.has_place:
            assert settings.latitude is not None and settings.longitude is not None
            return nearest_region(settings.latitude, settings.longitude)
        raise DashboardError("Add your postcode in the dashboard settings, or pick your region, so the Pi knows which bus timetable to get.")

    def _timetable(self, region: str) -> Path:
        return self.folder / f"timetable-{region}.zip"

    def _index_file(self, region: str) -> Path:
        return self.folder / f"stops-{region}.json"

    def _timetable_fresh(self, region: str) -> bool:
        path = self._timetable(region)
        return path.exists() and time.time() - path.stat().st_mtime < TIMETABLE_DAYS * 86400

    async def departures(self, settings: DashboardSettings) -> dict[str, Any]:
        """The bus card's data: {"preparing": True, ...} while the timetable is being got ready."""
        region = self.region(settings)
        codes = stop_codes(settings.bus_stops)
        key = (region, tuple(codes))
        if key != self._job_key:  # new stops or region: start afresh
            if self._job is not None:
                self._job.cancel()
            self._job, self._job_key, self._error, self._failed_at = None, key, None, None
        index = self._loaded(region, codes)
        needs_work = index is None or not self._timetable_fresh(region)
        may_try = self._failed_at is None or self._clock() - self._failed_at > RETRY_SECONDS
        if needs_work and self._job is None and may_try:
            self._error = None
            self._job = asyncio.create_task(self._prepare(region, codes))
        if index is None:
            if self._error and self._job is None:
                raise DashboardError(self._error)
            return {"preparing": True, "message": PREPARING, "services": []}

        now = self._now()
        lines = set(line_names(settings.bus_lines)) or None
        timetabled = gtfs.departures(index, now, lines=lines)
        found = [dict(d, expected=None, late=None) for d in timetabled]
        live_note = None
        if settings.bus_key and timetabled:
            try:
                vehicles = await self._vehicles(timetabled, settings.bus_key)
                found = buslive.apply_live(timetabled, vehicles, index, now)
            except FetchError as err:
                log.warning("Live bus positions failed: %s", err)
                live_note = (
                    "The bus data key wasn't accepted, so these are timetabled times."
                    if err.status in (401, 403)
                    else "Live times aren't available just now, so these are timetabled times."
                )
            except Exception as err:  # a malformed feed shouldn't lose the timetable
                log.warning("Live bus positions couldn't be read: %s", err)
                live_note = "Live times aren't available just now, so these are timetabled times."
        names = list(dict.fromkeys(index["target_names"].values()))
        return {
            "preparing": False,
            "stop": " & ".join(names),
            "services": rows(found, now),
            "live_enabled": bool(settings.bus_key),
            "note": live_note,
        }

    async def _vehicles(self, found: list[dict[str, Any]], key: str) -> list[buslive.Vehicle]:
        operators = list(dict.fromkeys(d["trip"]["noc"] for d in found if d["trip"]["noc"]))[:MAX_OPERATORS]
        answers = await asyncio.gather(
            *(self.fetcher.text(buslive.FEED_URL, {"operatorRef": noc, "api_key": key}) for noc in operators)
        )
        vehicles: list[buslive.Vehicle] = []
        for answer in answers:
            vehicles += buslive.parse_vehicles(answer)
        return vehicles

    def _loaded(self, region: str, codes: list[str]) -> dict[str, Any] | None:
        """The index for these stops, from memory or disk, if it matches the current timetable."""
        path = self._timetable(region)
        if not path.exists():
            return None
        key = (region, tuple(codes), path.stat().st_mtime)
        if self._index_key == key:
            return self._index
        try:
            index = json.loads(self._index_file(region).read_text())
        except (OSError, ValueError):
            return None
        if index.get("format") != gtfs.INDEX_FORMAT or index.get("codes") != codes or index.get("timetable_mtime") != key[2]:
            return None
        self._index, self._index_key = index, key
        return index

    async def _prepare(self, region: str, codes: list[str]) -> None:
        """Download the timetable if it's missing or old, then build the stop index."""
        try:
            path = self._timetable(region)
            if not self._timetable_fresh(region):
                log.info("Downloading the %s bus timetable", REGIONS[region][0])
                await self.fetcher.download(TIMETABLE_URL.format(region), path, TIMETABLE_MAX_BYTES)
            log.info("Indexing bus stops %s", ", ".join(codes))
            index = await asyncio.to_thread(gtfs.build_index, path, codes)
            index["timetable_mtime"] = path.stat().st_mtime
            self.folder.mkdir(parents=True, exist_ok=True)
            temp = self._index_file(region).with_suffix(".tmp")
            temp.write_text(json.dumps(index, separators=(",", ":")))
            os.replace(temp, self._index_file(region))
            self._index, self._index_key = None, None
            self._failed_at = None
            log.info("Bus index ready: %d journeys", len(index["trips"]))
        except gtfs.GtfsError as err:
            self._failed(str(err))
            if "damaged" in str(err) or "incomplete" in str(err):
                self._timetable(region).unlink(missing_ok=True)
        except FetchError as err:
            log.warning("Couldn't download the bus timetable: %s", err)
            self._failed("Couldn't download the bus timetable just now. The Pi will try again later.")
        except asyncio.CancelledError:
            raise
        except Exception:  # keep the card informative rather than stuck on "getting ready"
            log.exception("Preparing bus times failed")
            self._failed("Something went wrong getting the bus timetable ready. The Pi will try again later.")
        finally:
            self._job = None

    def _failed(self, message: str) -> None:
        self._error = message
        self._failed_at = self._clock()
