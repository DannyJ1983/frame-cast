"""Drive time with live traffic from TomTom's Routing API.

Needs a free key from developer.tomtom.com (the free tier allows thousands of
requests a day; the dashboard asks every five minutes while it's on screen).
"""

from __future__ import annotations

from typing import Any

ROUTE_URL = "https://api.tomtom.com/routing/1/calculateRoute/{:.5f},{:.5f}:{:.5f},{:.5f}/json"
METRES_PER_MILE = 1609.344


def route_request(start: tuple[float, float], end: tuple[float, float], key: str) -> tuple[str, dict[str, Any]]:
    """(url, query parameters) for the fastest drive from ``start`` to ``end`` now."""
    url = ROUTE_URL.format(start[0], start[1], end[0], end[1])
    params = {
        "key": key,
        "traffic": "true",
        "travelMode": "car",
        "routeType": "fastest",
        "computeTravelTimeFor": "all",
    }
    return url, params


def parse_route(data: dict[str, Any]) -> dict[str, Any]:
    """Drive time, usual time and delay in minutes. Raises KeyError or IndexError if there's no route."""
    summary = data["routes"][0]["summary"]
    travel = float(summary["travelTimeInSeconds"])
    delay = float(summary.get("trafficDelayInSeconds") or 0)
    usual = summary.get("noTrafficTravelTimeInSeconds") or summary.get("historicTrafficTravelTimeInSeconds")
    usual_seconds = float(usual) if usual else travel - delay
    delay_minutes = max(0, round(delay / 60))
    if delay_minutes <= 3:
        state = "ok"
    elif delay_minutes <= 10:
        state = "slow"
    else:
        state = "bad"
    return {
        "minutes": max(1, round(travel / 60)),
        "usual_minutes": max(1, round(usual_seconds / 60)),
        "delay_minutes": delay_minutes,
        "miles": round(float(summary.get("lengthInMeters") or 0) / METRES_PER_MILE, 1),
        "state": state,
    }
