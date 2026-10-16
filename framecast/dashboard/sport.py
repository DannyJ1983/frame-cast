"""Scores and fixtures from ESPN's scoreboards, with BBC Sport headlines when nothing's on.

ESPN's scoreboard addresses are unofficial (they're what ESPN's own site uses)
and need no key, so they could change without notice. A league that fails is
skipped rather than breaking the ticker.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/{}/{}/scoreboard"
SPORT_HEADLINES_URL = "https://feeds.bbci.co.uk/sport/football/rss.xml"
# League choices on the phone page: ESPN code -> (ESPN sport, name shown).
LEAGUES: dict[str, tuple[str, str]] = {
    "eng.1": ("soccer", "Premier League"),
    "eng.2": ("soccer", "Championship"),
    "eng.3": ("soccer", "League One"),
    "eng.4": ("soccer", "League Two"),
    "sco.1": ("soccer", "Scottish Premiership"),
    "eng.fa": ("soccer", "FA Cup"),
    "eng.league_cup": ("soccer", "Carabao Cup"),
    "uefa.champions": ("soccer", "Champions League"),
    "uefa.europa": ("soccer", "Europa League"),
    "uefa.europa.conf": ("soccer", "Conference League"),
    "eng.w.1": ("soccer", "Women's Super League"),
    "nfl": ("football", "NFL"),
    "nba": ("basketball", "NBA"),
}
DEFAULT_LEAGUES = ["eng.1"]
MAX_LEAGUES = 8
MAX_MATCHES = 40
RESULTS_FOR = timedelta(hours=36)
FIXTURES_FOR = timedelta(days=7)
_STATE_ORDER = {"in": 0, "post": 1, "pre": 2}


def scoreboard_url(league: str) -> str:
    """The scoreboard address for one of LEAGUES."""
    sport, _ = LEAGUES[league]
    return SCOREBOARD_URL.format(sport, league)


def _when(text: Any) -> datetime | None:
    if not isinstance(text, str) or not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _team(competitor: dict[str, Any]) -> str:
    team = competitor.get("team") or {}
    return str(team.get("shortDisplayName") or team.get("displayName") or team.get("abbreviation") or "?")


def is_favourite(names: list[str], teams: list[str]) -> bool:
    """True if any of the viewer's teams is playing (matched loosely, ignoring case)."""
    lowered = [n.lower() for n in names]
    return any(t and any(t in n or n in t for n in lowered) for t in (t.lower() for t in teams))


def parse_scoreboard(data: dict[str, Any], league: str, now: datetime, teams: list[str] | None = None) -> list[dict[str, Any]]:
    """Matches from one scoreboard that are live, just finished or coming up this week."""
    matches = []
    for event in data.get("events") or []:
        competitions = event.get("competitions") or []
        competitors = (competitions[0].get("competitors") if competitions else None) or []
        home = next((c for c in competitors if c.get("homeAway") == "home"), None)
        away = next((c for c in competitors if c.get("homeAway") == "away"), None)
        if home is None or away is None:
            continue
        status = (event.get("status") or {}).get("type") or {}
        state = status.get("state") if status.get("state") in _STATE_ORDER else "pre"
        kickoff = _when(event.get("date"))
        if kickoff is not None:
            if state == "post" and now - kickoff > RESULTS_FOR:
                continue
            if state == "pre" and kickoff - now > FIXTURES_FOR:
                continue
        played = state == "in" or (state == "post" and status.get("completed", True))
        names = [_team(home), _team(away)]
        matches.append({
            "league": LEAGUES.get(league, ("", league))[1],
            "home": names[0],
            "away": names[1],
            "home_score": str(home.get("score", "")) if played else "",
            "away_score": str(away.get("score", "")) if played else "",
            "state": state,
            "detail": str(status.get("shortDetail") or status.get("detail") or "") if state != "pre" else "",
            "kickoff": kickoff.astimezone(timezone.utc).isoformat(timespec="minutes") if kickoff else None,
            "favourite": is_favourite(names, teams or []),
        })
    return matches


def order_matches(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Live first, then results (latest first), then fixtures (soonest first); the viewer's teams lead each group."""

    def key(match: dict[str, Any]) -> tuple[int, int, float]:
        moment = _when(match.get("kickoff"))
        stamp = moment.timestamp() if moment else 0.0
        return (_STATE_ORDER[match["state"]], 0 if match["favourite"] else 1, -stamp if match["state"] == "post" else stamp)

    return sorted(matches, key=key)[:MAX_MATCHES]
