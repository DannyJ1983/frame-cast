"""Bus times: the timetable index, timetabled departures, live estimates and the card's manager."""

import asyncio
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from dashboard_samples import (BUS_STOPS, TARGET, UK, FakeFetcher, bus_trip, gtfs_zip, siri, siri_vehicle,
                               working_routes)
from framecast.dashboard import DashboardError, DashboardService, DashboardStore, buses, buslive, gtfs
from framecast.dashboard.fetch import FetchError

DAY = date(2026, 10, 16)  # a Friday, in British Summer Time
NOW = datetime(2026, 10, 16, 10, 8, tzinfo=UK)
ORIGIN, LAST = BUS_STOPS[0][0], BUS_STOPS[-1][0]
PLACES = {s[0]: (s[3], s[4]) for s in BUS_STOPS}


def local(hhmm: str, day: date = DAY) -> datetime:
    hours, minutes = (int(x) for x in hhmm.split(":"))
    return datetime(day.year, day.month, day.day, tzinfo=UK) + timedelta(hours=hours, minutes=minutes)


TRIPS = [
    bus_trip("7-1000", "7", "10:00", headsign="Brighton Marina"),        # at the stop 10:10
    bus_trip("7-1010", "7", "10:10", headsign="Brighton Marina"),        # 10:20
    bus_trip("14-0958", "14", "09:58", headsign="Peacehaven"),           # 10:08
    bus_trip("49-1005", "49", "10:05", service="NOTTODAY"),               # cancelled today
    bus_trip("49-1015", "49", "10:15", service="EXTRA"),                  # runs today only
    bus_trip("5-1000", "5", "10:00", stops=[s[0] for s in BUS_STOPS[:3]]),  # ends at the stop
    bus_trip("N7-2450", "N7", "24:50", headsign="Night"),                 # 01:00 the next morning
    bus_trip("12-1000", "12", "10:00", stops=[ORIGIN, BUS_STOPS[1][0]]),  # never calls at the stop
]


@pytest.fixture
def timetable(tmp_path):
    path = tmp_path / "timetable.zip"
    path.write_bytes(gtfs_zip(TRIPS, exceptions=[("NOTTODAY", "20261016", 2), ("EXTRA", "20261016", 1)]))
    return path


@pytest.fixture
def index(timetable):
    return gtfs.build_index(timetable, [TARGET])


def test_index_keeps_only_journeys_calling_at_the_stop(index):
    ids = {t["id"] for t in index["trips"]}
    assert ids == {"7-1000", "7-1010", "14-0958", "49-1005", "49-1015", "5-1000", "N7-2450"}
    trip = next(t for t in index["trips"] if t["id"] == "7-1000")
    assert trip["route"] == "7" and trip["noc"] == "BHBC" and trip["headsign"] == "Brighton Marina"
    assert [s[0] for s in trip["stops"]] == [s[0] for s in BUS_STOPS]  # back in order
    assert trip["stops"][2] == [TARGET, 36600, 36600]
    assert index["target_names"] == {TARGET: "Churchill Square (Stop D)"}
    assert set(index["places"]) == {s[0] for s in BUS_STOPS}
    # A journey without a headsign is named after where it ends.
    assert next(t for t in index["trips"] if t["id"] == "5-1000")["headsign"] == "Churchill Square (Stop D)"


def test_stops_found_by_naptan_code_and_bad_codes_refused(timetable, tmp_path):
    assert gtfs.build_index(timetable, ["BRIMGPD"])["targets"] == {"BRIMGPD": TARGET}
    with pytest.raises(gtfs.GtfsError, match="Couldn't find bus stop 149099999999"):
        gtfs.build_index(timetable, ["149099999999"])
    broken = tmp_path / "broken.zip"
    broken.write_bytes(b"not a zip")
    with pytest.raises(gtfs.GtfsError, match="damaged"):
        gtfs.build_index(broken, [TARGET])


def test_trip_id_need_not_be_the_first_column(tmp_path):
    path = tmp_path / "t.zip"
    path.write_bytes(gtfs_zip(TRIPS[:2], trip_id_first=False))
    assert {t["id"] for t in gtfs.build_index(path, [TARGET])["trips"]} == {"7-1000", "7-1010"}


def test_timetabled_departures(index):
    found = gtfs.departures(index, local("10:07"), horizon=timedelta(minutes=30))
    assert [(d["trip"]["id"], d["scheduled"].astimezone(UK).strftime("%H:%M")) for d in found] == [
        ("14-0958", "10:08"), ("7-1000", "10:10"), ("7-1010", "10:20"), ("49-1015", "10:25")]
    only_14 = gtfs.departures(index, local("10:07"), lines={"14"})
    assert [d["trip"]["route"] for d in only_14] == ["14"]


def test_after_midnight_journeys_belong_to_the_day_before(index):
    found = gtfs.departures(index, local("00:55", date(2026, 10, 17)), horizon=timedelta(minutes=20))
    assert [d["trip"]["id"] for d in found] == ["N7-2450"]
    assert found[0]["day"] == DAY
    assert found[0]["scheduled"] == local("01:00", date(2026, 10, 17))


def test_service_day_starts_at_noon_minus_twelve_hours():
    assert gtfs.service_start(DAY) == datetime(2026, 10, 15, 23, 0, tzinfo=timezone.utc)
    # The clocks go back on 25 October: noon is in GMT, so times count from 01:00 BST.
    assert gtfs.service_start(date(2026, 10, 25)) == datetime(2026, 10, 25, 0, 0, tzinfo=timezone.utc)


def vehicle_for(trip_id: str, lat: float, lon: float, recorded: datetime = NOW, **changes) -> str:
    trip = next(t for t in TRIPS if t["id"] == trip_id)
    times = trip["times"]
    start = datetime(DAY.year, DAY.month, DAY.day, tzinfo=UK)
    args = dict(line=trip["route"], origin=times[0][0], destination=times[-1][0],
                origin_time=start + timedelta(seconds=times[0][1]),
                destination_time=start + timedelta(seconds=times[-1][1]), recorded=recorded, lat=lat, lon=lon)
    args.update(changes)
    return siri_vehicle(**args)


def test_parse_vehicles_skips_incomplete_ones():
    good = vehicle_for("7-1000", 50.83, -0.145)
    no_place = vehicle_for("7-1010", None, None)
    vehicles = buslive.parse_vehicles(siri([good, no_place], NOW))
    assert len(vehicles) == 1
    bus = vehicles[0]
    assert (bus.operator, bus.line, bus.origin, bus.destination) == ("BHBC", "7", ORIGIN, LAST)
    assert bus.origin_time == local("10:00") and bus.recorded == NOW
    assert buslive.parse_vehicles(siri([], NOW)) == []


def live(index, activities, now=NOW):
    found = gtfs.departures(index, now, horizon=timedelta(minutes=30))
    return buslive.apply_live(found, buslive.parse_vehicles(siri(activities, now)), index, now)


def test_late_bus_gets_a_later_expected_time(index):
    # The 10:00 number 7 is at Palmeira Square (due 10:05) at 10:08: three minutes late.
    result = live(index, [vehicle_for("7-1000", *PLACES[BUS_STOPS[1][0]])])
    seven = next(d for d in result if d["trip"]["id"] == "7-1000")
    assert round(seven["late"]) == 3
    assert seven["expected"] == local("10:13")
    others = [d for d in result if d["trip"]["id"] != "7-1000"]
    assert all(d["expected"] is None for d in others)  # not tracked: timetable only


def test_bus_that_has_passed_the_stop_is_dropped(index):
    # The 09:58 number 14 is already at Old Steine, past the stop.
    result = live(index, [vehicle_for("14-0958", *PLACES[BUS_STOPS[3][0]])])
    assert "14-0958" not in [d["trip"]["id"] for d in result]


def test_untrustworthy_positions_are_ignored(index):
    stale = vehicle_for("7-1000", *PLACES[BUS_STOPS[1][0]], recorded=NOW - timedelta(minutes=10))
    other_operator = vehicle_for("7-1000", *PLACES[BUS_STOPS[1][0]], operator="SCLK")
    wrong_journey = vehicle_for("7-1000", *PLACES[BUS_STOPS[1][0]], origin_time=local("09:30"),
                                destination_time=local("09:50"))
    for activity in (stale, other_operator, wrong_journey):
        assert all(d["expected"] is None for d in live(index, [activity]))


def test_two_identical_journeys_are_left_to_the_timetable(tmp_path):
    path = tmp_path / "t.zip"
    path.write_bytes(gtfs_zip([bus_trip("a", "7", "10:00"), bus_trip("b", "7", "10:00")]))
    index = gtfs.build_index(path, [TARGET])
    start = datetime(2026, 10, 16, tzinfo=UK)
    activity = siri_vehicle("7", ORIGIN, LAST, start + timedelta(hours=10), start + timedelta(hours=10, minutes=20),
                            NOW, *PLACES[BUS_STOPS[1][0]])
    assert all(d["expected"] is None for d in live(index, [activity]))


def test_early_bus_at_the_start_of_its_route_still_leaves_on_time(tmp_path):
    path = tmp_path / "t.zip"
    path.write_bytes(gtfs_zip([bus_trip("x", "7", "10:12", stops=[TARGET, BUS_STOPS[3][0], LAST])]))
    index = gtfs.build_index(path, [TARGET])
    start = datetime(2026, 10, 16, tzinfo=UK)
    activity = siri_vehicle("7", TARGET, LAST, start + timedelta(hours=10, minutes=12),
                            start + timedelta(hours=10, minutes=22), NOW, *PLACES[TARGET])
    [departure] = live(index, [activity])
    assert departure["expected"] == local("10:12")


def test_rows_for_the_page():
    trip = {"route": "7", "headsign": "Brighton Marina"}
    departures = [
        {"trip": trip, "scheduled": local("10:10"), "expected": local("10:13"), "late": 3.2},
        {"trip": trip, "scheduled": local("10:20"), "expected": None, "late": None},
        {"trip": trip, "scheduled": local("10:08"), "expected": local("10:07:30".rsplit(":", 1)[0]), "late": -1},
    ]
    shown = buses.rows(departures, NOW)
    assert shown[0] == {"route": "7", "destination": "Brighton Marina", "time": "10:10", "minutes": 5,
                        "live": True, "late": 3}
    assert shown[1]["minutes"] is None and shown[1]["time"] == "10:20" and not shown[1]["live"]
    assert shown[2]["minutes"] == 0  # due


def test_codes_regions_and_lines():
    assert buses.stop_codes("149000006934, brimgpd") == ["149000006934", "brimgpd"]
    with pytest.raises(DashboardError, match="doesn't look like a bus stop code"):
        buses.stop_codes("Churchill Square")
    with pytest.raises(DashboardError, match="more than 3"):
        buses.stop_codes("149000000001 149000000002 149000000003 149000000004")
    assert buses.line_names("7, n7 14") == ["7", "N7", "14"]
    assert buses.nearest_region(50.83, -0.14) == "south_east"  # Brighton
    assert buses.nearest_region(53.48, -2.24) == "north_west"  # Manchester
    assert buses.nearest_region(51.50, -0.12) == "london"


# The manager, with a fake internet -------------------------------------------------------------


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def manager(tmp_path, routes, now=NOW):
    clock = Clock()
    return buses.BusTimes(tmp_path, FakeFetcher(routes), lambda: now, clock), clock


def bus_settings(**changes):
    from framecast.dashboard.settings import DashboardSettings
    settings = DashboardSettings(bus_stops=TARGET, latitude=50.83, longitude=-0.14, place="BN1")
    for name, value in changes.items():
        setattr(settings, name, value)
    return settings


TIMETABLE = "https://data.bus-data.dft.gov.uk/timetable/"
FEED = "https://data.bus-data.dft.gov.uk/api/v1/datafeed/"


async def ready(times, settings):
    first = await times.departures(settings)
    if times._job is not None:
        await times._job
    return first, await times.departures(settings)


def test_manager_prepares_then_shows_live_and_timetabled_buses(tmp_path):
    routes = {TIMETABLE: gtfs_zip(TRIPS), FEED: siri([vehicle_for("7-1000", *PLACES[BUS_STOPS[1][0]])], NOW)}
    times, _ = manager(tmp_path, routes)
    first, second = asyncio.run(ready(times, bus_settings(bus_key="k")))
    assert first["preparing"] and first["message"].startswith("Getting the bus timetable ready")
    assert second["preparing"] is False and second["stop"] == "Churchill Square (Stop D)"
    seven = next(r for r in second["services"] if r["time"] == "10:10")
    assert seven["live"] and seven["minutes"] == 5 and seven["late"] == 3
    assert any(not r["live"] for r in second["services"])
    feed_call = next(c for c in times.fetcher.calls if c[0] == FEED)
    assert feed_call[1] == {"operatorRef": "BHBC", "api_key": "k"}
    assert (tmp_path / "buses" / "timetable-south_east.zip").exists()
    # A new manager (after a restart) uses the saved index straight away.
    again, _ = manager(tmp_path, routes)
    assert asyncio.run(again.departures(bus_settings()))["preparing"] is False


def test_without_a_key_buses_are_timetabled_and_a_bad_key_says_so(tmp_path):
    routes = {TIMETABLE: gtfs_zip(TRIPS), FEED: FetchError("no", 403)}
    times, _ = manager(tmp_path, routes)
    _, plain = asyncio.run(ready(times, bus_settings()))
    assert plain["services"] and not any(r["live"] for r in plain["services"])
    assert not any(c[0] == FEED for c in times.fetcher.calls)
    keyed = asyncio.run(times.departures(bus_settings(bus_key="bad")))
    assert "key wasn't accepted" in keyed["note"] and keyed["services"]


def test_a_missing_stop_is_reported_and_not_retried_at_once(tmp_path):
    times, clock = manager(tmp_path, {TIMETABLE: gtfs_zip(TRIPS)})
    settings = bus_settings(bus_stops="149099999999")

    async def go():
        await times.departures(settings)
        await times._job
        with pytest.raises(DashboardError, match="Couldn't find bus stop"):
            await times.departures(settings)
        assert times._job is None  # waiting before trying again
        clock.t += buses.RETRY_SECONDS + 1
        await times.departures(settings)
        assert times._job is not None
        await times._job

    asyncio.run(go())
    # Changing the stop starts afresh straight away.
    assert asyncio.run(times.departures(bus_settings()))["preparing"]


def test_download_failure_and_region_choice(tmp_path):
    times, _ = manager(tmp_path, {TIMETABLE: FetchError("down", 503)})

    async def go():
        await times.departures(bus_settings())
        await times._job
        with pytest.raises(DashboardError, match="Couldn't download the bus timetable"):
            await times.departures(bus_settings())

    asyncio.run(go())
    with pytest.raises(DashboardError, match="Add your postcode"):
        times.region(bus_settings(latitude=None, longitude=None))
    assert times.region(bus_settings(bus_region="london")) == "london"


def test_bus_card_through_the_service(tmp_path):
    service = DashboardService(DashboardStore(tmp_path), FakeFetcher(working_routes()))

    async def go():
        public = await service.update_settings({"place": "LS1 4AP", "bus_stops": "149000006934",
                                                "bus_lines": "7, 14", "bus_key": "secret"})
        assert public["has_bus_key"] and public["bus_lines"] == "7, 14" and "bus_key" not in public
        first = await service.snapshot()
        assert first["cards"]["buses"]["data"]["preparing"]
        await service.buses._job
        service._cards["buses"].fetched = -1e9  # due again
        await service.snapshot()
        for _ in range(50):
            if service._cards["buses"].task is None:
                break
            await asyncio.sleep(0)
        return (await service.snapshot())["cards"]["buses"]

    card = asyncio.run(go())
    assert card["error"] is None
    routes = {r["route"] for r in card["data"]["services"]}
    assert routes and routes <= {"7", "14"}
    with pytest.raises(DashboardError, match="bus stop code"):
        asyncio.run(service.update_settings({"bus_stops": "Churchill Square"}))
    with pytest.raises(DashboardError, match="region"):
        asyncio.run(service.update_settings({"bus_region": "mars"}))
