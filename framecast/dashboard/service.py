"""Keeps each dashboard card fresh: fetches on demand, caches, and tolerates failures.

Nothing is fetched while nobody's looking: a card is refreshed when the page
asks for it and its data is older than the card's refresh interval. A card
that fails keeps showing its last good data, marked as out of date.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from . import buses, news, places, sport, traffic, trains, weather
from .fetch import Fetcher, FetchError
from .settings import DashboardError, DashboardSettings, DashboardStore

log = logging.getLogger(__name__)

CARDS = ("weather", "trains", "buses", "traffic", "news", "sport")
REFRESH_SECONDS = {"weather": 900.0, "trains": 60.0, "buses": 30.0, "traffic": 300.0, "news": 600.0, "sport": 600.0}
PREPARING_REFRESH = 15.0  # check back soon while the bus timetable is being got ready
SPORT_LIVE_REFRESH = 60.0  # Scores update every minute while a match is on.
RETRY_SECONDS = 60.0  # How soon a card that failed is tried again.
FIRST_LOAD_WAIT = 8.0  # How long the page waits for a card it has never had.
CARD_TIMEOUT = 20.0
FAILED = {
    "weather": "Couldn't get the weather just now.",
    "trains": "Couldn't get the train times just now.",
    "buses": "Couldn't get the bus times just now.",
    "traffic": "Couldn't get the traffic just now.",
    "news": "Couldn't get the headlines just now.",
    "sport": "Couldn't get the scores just now.",
}
KEY_REFUSED = {
    "trains": "The train data key wasn't accepted. Check it on the phone page, and that you've "
              "subscribed to the Live Departure Board on the Rail Data Marketplace.",
    "traffic": "The TomTom key wasn't accepted. Check it on the phone page.",
}


@dataclass
class Card:
    """One card's latest data, or why it has none."""

    data: Any = None
    error: str | None = None
    fetched: float | None = None
    refresh: float = 0.0
    task: asyncio.Task[None] | None = None


def _clean(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


class DashboardService:
    """Answers the dashboard page and the phone page's settings form."""

    def __init__(
        self,
        store: DashboardStore,
        fetcher: Fetcher | None = None,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.store = store
        self.fetcher = fetcher or Fetcher()
        self._clock = clock
        self._now = now
        self.buses = buses.BusTimes(store.folder, self.fetcher, now)
        self._cards: dict[str, Card] = {}
        self._generation = 0

    # The page --------------------------------------------------------------------

    def enabled(self) -> list[str]:
        """The cards that are set up, in display order."""
        setup = self.store.settings.setup()
        return [name for name in CARDS if setup[name]]

    async def snapshot(self, only: list[str] | None = None) -> dict[str, Any]:
        """Everything the page shows, or just the cards named in ``only``.

        Waits briefly for cards it has never had; refreshes stale ones in the background.
        """
        names = [name for name in self.enabled() if only is None or name in only]
        waiting = []
        for name in names:
            card = self._cards.setdefault(name, Card())
            due = card.fetched is None or self._clock() - card.fetched >= card.refresh
            if name == "buses" and isinstance(card.data, dict) and card.data.get("preparing") and not self.buses.busy:
                due = True  # the timetable has just finished getting ready
            if due and card.task is None:
                card.task = asyncio.create_task(self._refresh(name, card, self._generation))
            if card.data is None and card.error is None and card.task is not None:
                waiting.append(card.task)
        if waiting:
            await asyncio.wait(waiting, timeout=FIRST_LOAD_WAIT)
        cards = {}
        for name in names:
            card = self._cards[name]
            cards[name] = {"data": card.data, "error": card.error}
        settings = self.store.settings
        return {
            "updated": self._now().isoformat(timespec="seconds"),
            "setup": settings.setup(),
            "place": settings.place_name,
            "traffic_label": settings.traffic_label or settings.traffic_to_name,
            "cards": cards,
        }

    async def _refresh(self, name: str, card: Card, generation: int) -> None:
        try:
            data = await asyncio.wait_for(self._load(name), CARD_TIMEOUT)
        except DashboardError as err:
            self._fail(name, card, generation, str(err))
        except asyncio.TimeoutError:
            self._fail(name, card, generation, FAILED[name])
        except Exception as err:  # a source can fail in many ways; the card says so and the rest carry on
            log.warning("Dashboard %s failed: %s", name, err, exc_info=not isinstance(err, FetchError))
            self._fail(name, card, generation, FAILED[name])
        else:
            if generation == self._generation:
                card.data, card.error = data, None
                card.fetched = self._clock()
                card.refresh = self._refresh_after(name, data)
        finally:
            card.task = None

    def _fail(self, name: str, card: Card, generation: int, message: str) -> None:
        if generation != self._generation:
            return
        card.error = message
        card.fetched = self._clock()
        card.refresh = min(RETRY_SECONDS, REFRESH_SECONDS[name])

    @staticmethod
    def _refresh_after(name: str, data: Any) -> float:
        if name == "sport" and any(m["state"] == "in" for m in data.get("matches", [])):
            return SPORT_LIVE_REFRESH
        if name == "buses" and data.get("preparing"):
            return PREPARING_REFRESH
        return REFRESH_SECONDS[name]

    async def _load(self, name: str) -> Any:
        settings = self.store.settings
        if name == "weather":
            assert settings.latitude is not None and settings.longitude is not None
            data = await self.fetcher.json(weather.FORECAST_URL, weather.forecast_params(settings.latitude, settings.longitude))
            return weather.parse_forecast(data)
        if name == "trains":
            url, params, headers = trains.departures_request(settings.station, settings.station_to, settings.rail_key)
            return trains.parse_departures(await self._keyed_json(name, url, params, headers))
        if name == "buses":
            return await self.buses.departures(settings)
        if name == "traffic":
            assert settings.latitude is not None and settings.longitude is not None
            assert settings.traffic_to_latitude is not None and settings.traffic_to_longitude is not None
            url, params = traffic.route_request(
                (settings.latitude, settings.longitude),
                (settings.traffic_to_latitude, settings.traffic_to_longitude),
                settings.traffic_key,
            )
            return traffic.parse_route(await self._keyed_json(name, url, params, None))
        if name == "news":
            return news.parse_feed(await self.fetcher.text(self._news_url(settings)))
        if name == "sport":
            return await self._load_sport(settings)
        raise ValueError(name)

    async def _keyed_json(self, name: str, url: str, params: dict[str, Any], headers: dict[str, str] | None) -> Any:
        try:
            return await self.fetcher.json(url, params, headers)
        except FetchError as err:
            if err.status in (401, 403):
                raise DashboardError(KEY_REFUSED[name]) from err
            raise

    @staticmethod
    def _news_url(settings: DashboardSettings) -> str:
        if settings.news == "custom" and settings.news_url:
            return settings.news_url
        return news.NEWS_FEEDS.get(settings.news, news.NEWS_FEEDS[news.DEFAULT_FEED])[1]

    async def _load_sport(self, settings: DashboardSettings) -> dict[str, Any]:
        leagues = [code for code in settings.leagues if code in sport.LEAGUES]
        answers = await asyncio.gather(
            *(self.fetcher.json(sport.scoreboard_url(code)) for code in leagues), return_exceptions=True
        )
        matches: list[dict[str, Any]] = []
        failures = 0
        now = self._now()
        for code, answer in zip(leagues, answers):
            if isinstance(answer, BaseException):
                log.warning("Scores for %s failed: %s", code, answer)
                failures += 1
                continue
            matches += sport.parse_scoreboard(answer, code, now, settings.team_list)
        headlines: list[dict[str, Any]] = []
        if not matches:
            try:
                headlines = news.parse_feed(await self.fetcher.text(sport.SPORT_HEADLINES_URL))["headlines"]
            except (FetchError, ValueError) as err:
                log.warning("Sport headlines failed: %s", err)
                if leagues and failures == len(leagues):
                    raise
        return {"matches": sport.order_matches(matches), "headlines": headlines}

    # Settings --------------------------------------------------------------------

    def options(self) -> dict[str, Any]:
        """The choices the phone page offers."""
        return {
            "news": [{"id": key, "name": name} for key, (name, _) in news.NEWS_FEEDS.items()],
            "leagues": [{"id": key, "name": name} for key, (_, name) in sport.LEAGUES.items()],
            "bus_regions": [{"id": key, "name": name} for key, (name, _, _) in buses.REGIONS.items()],
        }

    async def find_place(self, text: str) -> places.Place:
        """Look up a postcode or town; raises DashboardError if it can't be found."""
        url, params, parser = places.place_request(text)
        try:
            data = await self.fetcher.json(url, params)
        except FetchError as err:
            if err.status == 404:
                raise DashboardError(f"Couldn't find “{text}”. Check the postcode, or try a town name.") from err
            raise DashboardError("Couldn't look that place up just now. Try again in a minute.") from err
        place = places.parse_postcode(data) if parser == "postcode" else places.parse_geocode(data)
        if place is None:
            raise DashboardError(f"Couldn't find “{text}”. Try a postcode, or a nearby town.")
        return place

    async def update_settings(self, data: dict[str, Any]) -> dict[str, Any]:
        """Apply changes from the phone page, looking places up as needed. Returns the public settings."""
        new = dataclasses.replace(self.store.settings, leagues=list(self.store.settings.leagues))
        if "place" in data:
            text = _clean(data["place"], 80)
            if not text:
                new.place, new.place_name, new.latitude, new.longitude = "", "", None, None
            elif text != new.place or not new.has_place:
                found = await self.find_place(text)
                new.place, new.place_name, new.latitude, new.longitude = text, found.name, found.latitude, found.longitude
        for name in ("station", "station_to"):
            if name in data:
                code = _clean(data[name], 10).upper()
                if code and not trains.valid_crs(code):
                    raise DashboardError("Station codes are three letters, like KGX for London King's Cross.")
                setattr(new, name, code)
        if "traffic_to" in data:
            text = _clean(data["traffic_to"], 80)
            if not text:
                new.traffic_to, new.traffic_to_name, new.traffic_to_latitude, new.traffic_to_longitude = "", "", None, None
            elif text != new.traffic_to or new.traffic_to_latitude is None:
                found = await self.find_place(text)
                new.traffic_to, new.traffic_to_name = text, found.name
                new.traffic_to_latitude, new.traffic_to_longitude = found.latitude, found.longitude
        if "bus_stops" in data:
            new.bus_stops = " ".join(buses.stop_codes(_clean(data["bus_stops"], 100)))
        if "bus_lines" in data:
            new.bus_lines = ", ".join(buses.line_names(_clean(data["bus_lines"], 100)))
        if "bus_region" in data:
            region = str(data["bus_region"])
            if region != "auto" and region not in buses.REGIONS:
                raise DashboardError("Pick a region from the list.")
            new.bus_region = region
        if "traffic_label" in data:
            new.traffic_label = _clean(data["traffic_label"], 30)
        for name in ("rail_key", "traffic_key", "bus_key"):
            if name in data and data[name] is not None:
                setattr(new, name, str(data[name]).strip()[:200])
        if "news" in data:
            choice = str(data["news"])
            if choice != "custom" and choice not in news.NEWS_FEEDS:
                raise DashboardError("Pick a news source from the list.")
            new.news = choice
        if "news_url" in data:
            url = _clean(data["news_url"], 500)
            if url and not url.lower().startswith(("http://", "https://")):
                raise DashboardError("The news feed address should start with http:// or https://.")
            new.news_url = url
        if new.news == "custom" and not new.news_url:
            raise DashboardError("Give the address of the news feed, or pick one from the list.")
        if "leagues" in data:
            chosen = data["leagues"] if isinstance(data["leagues"], list) else []
            new.leagues = [code for code in sport.LEAGUES if code in chosen][: sport.MAX_LEAGUES]
        if "teams" in data:
            new.teams = _clean(data["teams"], 200)
        self.store.save(new)
        self._cards.clear()
        self._generation += 1
        log.info("Dashboard settings changed")
        return new.public()

    async def aclose(self) -> None:
        """Stop refreshing and close connections."""
        for card in self._cards.values():
            if card.task is not None:
                card.task.cancel()
        await self.fetcher.aclose()
