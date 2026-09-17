"""Open-Meteo helpers shared by the agent tools, the fusion engine and the mobile router.

Open-Meteo is the baseline provider: free, key-less, ECMWF/IMD-grade NWP output, and the
only provider that gives us structured hourly/daily forecasts. Everything else is layered
on top of it by the fusion engine.
"""

from __future__ import annotations

from typing import Any

import httpx
import time

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"

# WMO weather interpretation codes. Open-Meteo renamed `weathercode` -> `weather_code`;
# both are tolerated by `extract_weather_code`.
WEATHER_CODES: dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Foggy",
    48: "Icy fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


def extract_weather_code(block: dict[str, Any] | None, default: int = -1) -> int:
    """Return the WMO code from a `current`/`daily` block regardless of key spelling."""
    if not isinstance(block, dict):
        return default
    code = block.get("weather_code", block.get("weathercode", default))
    try:
        return int(code)
    except (TypeError, ValueError):
        return default


def code_to_condition(code: Any, default: str = "Unknown") -> str:
    try:
        return WEATHER_CODES.get(int(code), default)
    except (TypeError, ValueError):
        return default


class UpstreamError(RuntimeError):
    """Raised when Open-Meteo is unreachable or returns an unexpected payload."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def get_json(url: str, params: dict[str, Any], timeout: float = 12.0) -> dict[str, Any]:
    """GET `url` and return the JSON body as a dict, raising `UpstreamError` on failure."""
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            with httpx.Client(timeout=timeout) as client:
                res = client.get(url, params=params)
                res.raise_for_status()
                data = res.json()
            break
        except (httpx.TimeoutException, httpx.HTTPError, ValueError) as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(0.15)
    else:
        if isinstance(last_error, httpx.TimeoutException):
            raise UpstreamError("Weather upstream timed out", 504) from last_error
        if isinstance(last_error, ValueError):
            raise UpstreamError("Weather upstream returned invalid JSON", 502) from last_error
        raise UpstreamError("Weather upstream request failed", 502) from last_error
    if not isinstance(data, dict):
        raise UpstreamError("Unexpected weather upstream response", 502)
    return data


def geocode(city_name: str, timeout: float = 10.0) -> dict[str, Any]:
    """Resolve a place name to coordinates. Returns `{"error": ...}` when not found."""
    try:
        data = get_json(
            GEOCODING_URL,
            {"name": city_name, "count": 1, "language": "en"},
            timeout=timeout,
        )
    except UpstreamError as exc:
        return {"error": str(exc)}
    results = data.get("results") or []
    if not results:
        return {"error": f"City '{city_name}' not found"}
    hit = results[0]
    return {
        "latitude": hit["latitude"],
        "longitude": hit["longitude"],
        "city": hit.get("name", city_name),
        "country": hit.get("country", ""),
        "state": hit.get("admin1", ""),
    }
