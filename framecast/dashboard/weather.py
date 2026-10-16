"""Weather from Open-Meteo, which is free for personal use and needs no key."""

from __future__ import annotations

from typing import Any

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
HOURS_AHEAD = 12
HOUR_STEP = 2

# WMO weather codes, as Open-Meteo documents them: (description, icon).
WEATHER_CODES: dict[int, tuple[str, str]] = {
    0: ("Clear", "clear"),
    1: ("Mostly clear", "clear"),
    2: ("Partly cloudy", "partly"),
    3: ("Cloudy", "cloud"),
    45: ("Fog", "fog"),
    48: ("Freezing fog", "fog"),
    51: ("Light drizzle", "drizzle"),
    53: ("Drizzle", "drizzle"),
    55: ("Heavy drizzle", "drizzle"),
    56: ("Freezing drizzle", "drizzle"),
    57: ("Freezing drizzle", "drizzle"),
    61: ("Light rain", "rain"),
    63: ("Rain", "rain"),
    65: ("Heavy rain", "rain"),
    66: ("Freezing rain", "rain"),
    67: ("Freezing rain", "rain"),
    71: ("Light snow", "snow"),
    73: ("Snow", "snow"),
    75: ("Heavy snow", "snow"),
    77: ("Snow grains", "snow"),
    80: ("Light showers", "showers"),
    81: ("Showers", "showers"),
    82: ("Heavy showers", "showers"),
    85: ("Snow showers", "snow"),
    86: ("Heavy snow showers", "snow"),
    95: ("Thunderstorms", "thunder"),
    96: ("Thunderstorms with hail", "thunder"),
    99: ("Thunderstorms with hail", "thunder"),
}


def forecast_params(latitude: float, longitude: float) -> dict[str, Any]:
    """Query parameters for the forecast request."""
    return {
        "latitude": round(latitude, 3),
        "longitude": round(longitude, 3),
        "current": "temperature_2m,apparent_temperature,weather_code,is_day,wind_speed_10m",
        "hourly": "temperature_2m,weather_code,precipitation_probability,is_day",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset",
        "timezone": "auto",
        "forecast_days": 4,
        "forecast_hours": HOURS_AHEAD + 1,
        "wind_speed_unit": "mph",
    }


def describe(code: Any, is_day: Any = 1) -> tuple[str, str]:
    """(description, icon) for a WMO code; clear and partly cloudy skies get night icons after dark."""
    text, icon = WEATHER_CODES.get(int(code) if isinstance(code, (int, float)) else -1, ("", "cloud"))
    if not is_day and icon in ("clear", "partly"):
        icon += "-night"
    return text, icon


def _number(value: Any) -> int | None:
    return round(value) if isinstance(value, (int, float)) else None


def _at(values: Any, index: int) -> Any:
    return values[index] if isinstance(values, list) and index < len(values) else None


def _clock(stamp: Any) -> str:
    """"2026-10-16T15:00" -> "15:00"."""
    return stamp[11:16] if isinstance(stamp, str) and len(stamp) >= 16 else ""


def _day(daily: dict[str, Any], index: int) -> dict[str, Any] | None:
    if _at(daily.get("time"), index) is None:
        return None
    text, icon = describe(_at(daily.get("weather_code"), index))
    return {
        "date": str(_at(daily.get("time"), index)),
        "text": text,
        "icon": icon,
        "high": _number(_at(daily.get("temperature_2m_max"), index)),
        "low": _number(_at(daily.get("temperature_2m_min"), index)),
        "rain_chance": _number(_at(daily.get("precipitation_probability_max"), index)),
        "sunrise": _clock(_at(daily.get("sunrise"), index)),
        "sunset": _clock(_at(daily.get("sunset"), index)),
    }


def parse_forecast(data: dict[str, Any]) -> dict[str, Any]:
    """Turn Open-Meteo's forecast into what the dashboard shows. Raises KeyError if it's not a forecast."""
    current = data["current"]
    text, icon = describe(current.get("weather_code"), current.get("is_day", 1))
    hourly = data.get("hourly") or {}
    hours = []
    for index in range(HOUR_STEP, HOURS_AHEAD + 1, HOUR_STEP):
        stamp = _at(hourly.get("time"), index)
        if stamp is None:
            break
        hour_text, hour_icon = describe(_at(hourly.get("weather_code"), index), _at(hourly.get("is_day"), index))
        hours.append({
            "time": _clock(stamp),
            "temp": _number(_at(hourly.get("temperature_2m"), index)),
            "icon": hour_icon,
            "text": hour_text,
            "rain_chance": _number(_at(hourly.get("precipitation_probability"), index)),
        })
    daily = data.get("daily") or {}
    return {
        "now": {
            "temp": _number(current.get("temperature_2m")),
            "feels": _number(current.get("apparent_temperature")),
            "wind_mph": _number(current.get("wind_speed_10m")),
            "text": text,
            "icon": icon,
        },
        "today": _day(daily, 0),
        "tomorrow": _day(daily, 1),
        "days": [day for day in (_day(daily, i) for i in (1, 2, 3)) if day],
        "hours": hours,
    }
