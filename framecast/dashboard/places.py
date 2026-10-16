"""Finding a place from a UK postcode (postcodes.io) or a town name (Open-Meteo's geocoder).

Both are free and need no key.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

POSTCODE_URL = "https://api.postcodes.io/postcodes/{}"
OUTCODE_URL = "https://api.postcodes.io/outcodes/{}"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"

_FULL_POSTCODE = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}$")
_OUTCODE = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]?$")


@dataclass
class Place:
    """A named point on the map."""

    name: str
    latitude: float
    longitude: float


def postcode_kind(text: str) -> str | None:
    """"full" for a whole postcode ("LS1 4AP"), "outcode" for its first half ("LS1"), else None."""
    value = text.strip().upper()
    if _FULL_POSTCODE.match(value):
        return "full"
    if _OUTCODE.match(value):
        return "outcode"
    return None


def _first(value: Any) -> str:
    if isinstance(value, list):
        value = value[0] if value else ""
    return str(value or "")


def parse_postcode(data: dict[str, Any]) -> Place | None:
    """Read postcodes.io's answer for a postcode or outcode."""
    result = data.get("result") if isinstance(data, dict) else None
    if not isinstance(result, dict) or result.get("latitude") is None or result.get("longitude") is None:
        return None
    name = _first(result.get("admin_district")) or _first(result.get("postcode")) or _first(result.get("outcode"))
    return Place(name, float(result["latitude"]), float(result["longitude"]))


def parse_geocode(data: dict[str, Any]) -> Place | None:
    """Read Open-Meteo's geocoding answer, taking the best match."""
    results = data.get("results") if isinstance(data, dict) else None
    if not results:
        return None
    best = results[0]
    return Place(str(best.get("name") or ""), float(best["latitude"]), float(best["longitude"]))


def place_request(text: str) -> tuple[str, dict[str, Any] | None, str]:
    """(url, query parameters, parser name) for looking ``text`` up."""
    kind = postcode_kind(text)
    value = text.strip().upper()
    if kind == "full":
        return POSTCODE_URL.format(quote(value.replace(" ", ""))), None, "postcode"
    if kind == "outcode":
        return OUTCODE_URL.format(quote(value)), None, "postcode"
    return GEOCODE_URL, {"name": text.strip(), "count": 1, "language": "en", "countryCode": "GB"}, "geocode"
