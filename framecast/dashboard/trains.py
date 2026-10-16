"""Live departures from National Rail's Darwin, through the Rail Data Marketplace.

Needs a free key: register at raildata.org.uk and subscribe to the "Live
Departure Board" product. The key is sent in the ``x-apikey`` header, and the
answer follows Darwin's LDBWS object model (``trainServices``, ``std``, ``etd``…).
"""

from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import quote

DEPARTURES_URL = (
    "https://api1.raildata.org.uk/1010-live-departure-board-dep/LDBWS/api/20220120/GetDepBoardWithDetails/{}"
)
MAX_ROWS = 8
_CRS = re.compile(r"^[A-Z]{3}$")
_CLOCK = re.compile(r"^\d\d:\d\d$")
_TAGS = re.compile(r"<[^>]+>")


def valid_crs(code: str) -> bool:
    """True for a three-letter station code such as "KGX"."""
    return bool(_CRS.match(code))


def departures_request(station: str, to_station: str, key: str) -> tuple[str, dict[str, Any], dict[str, str]]:
    """(url, query parameters, headers) for a station's next departures."""
    params: dict[str, Any] = {"numRows": MAX_ROWS}
    if to_station:
        params.update(filterCrs=to_station, filterType="to")
    return DEPARTURES_URL.format(quote(station)), params, {"x-apikey": key}


def _status(service: dict[str, Any]) -> tuple[str, str]:
    """(what to show, "ok"/"late"/"cancelled") from a service's expected time."""
    etd = str(service.get("etd") or "").strip()
    if service.get("isCancelled") or etd.lower() == "cancelled":
        return "Cancelled", "cancelled"
    if etd.lower() == "on time":
        return "On time", "ok"
    if _CLOCK.match(etd):
        return f"Exp {etd}", "late"
    return etd, ("late" if etd else "ok")


def _message_text(message: Any) -> str:
    if isinstance(message, dict):
        message = message.get("Value") or message.get("value") or message.get("message") or ""
    text = " ".join(html.unescape(_TAGS.sub(" ", str(message or ""))).split())
    return re.sub(r" ([.,;:!?])", r"\1", text)  # where a tag ended just before the punctuation


def parse_departures(data: dict[str, Any], limit: int = MAX_ROWS) -> dict[str, Any]:
    """Turn a departure board into rows for the dashboard. Raises KeyError if it isn't one."""
    if "trainServices" not in data and "locationName" not in data:
        raise KeyError("trainServices")
    services = []
    for kind, items in (("train", data.get("trainServices")), ("bus", data.get("busServices"))):
        for service in items or []:
            destinations = [d for d in service.get("destination") or [] if isinstance(d, dict)]
            names = [str(d.get("locationName")) for d in destinations if d.get("locationName")]
            status, state = _status(service)
            services.append({
                "time": str(service.get("std") or ""),
                "destination": " & ".join(names) or "Unknown",
                "via": str(destinations[0].get("via") or "") if destinations else "",
                "platform": "Bus" if kind == "bus" else str(service.get("platform") or ""),
                "status": status,
                "state": state,
                "operator": str(service.get("operator") or ""),
                "reason": str(service.get("cancelReason") or service.get("delayReason") or ""),
            })
    services.sort(key=lambda s: s["time"])  # buses after trains otherwise; "HH:MM" sorts by time
    messages = [m for m in (_message_text(m) for m in data.get("nrccMessages") or []) if m]
    return {
        "station": str(data.get("locationName") or ""),
        "to": str(data.get("filterLocationName") or ""),
        "services": services[:limit],
        "messages": messages[:3],
    }
