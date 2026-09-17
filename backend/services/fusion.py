"""Multi-provider current-conditions fusion engine.

Shared by:
  * the LangGraph agent tool `get_current_weather`
  * the deterministic chat fallback
  * the mobile `GET /weather` endpoint
  * the new `GET /fusion` endpoint (web Dev Suite "Ensemble Inspector")

Provider priority (trust weights) — **Open-Meteo > AccuWeather > everyone else**:

    Open-Meteo (ECMWF/IMD NWP)  2.00   always on, no key
    AccuWeather                 1.50   ACCUWEATHER_KEY
    WeatherAPI.com              1.20   WEATHERAPI_KEY
    Tomorrow.io                 1.20   TOMORROW_KEY
    OpenWeatherMap              1.10   OPENWEATHER_KEY

Algorithm
---------
1. All configured providers are queried **in parallel** with a hard per-provider timeout,
   so one slow vendor cannot stall the chat request.
2. Outlier guard: when Open-Meteo responded, any provider whose temperature deviates by
   more than `OUTLIER_TEMP_DELTA_C` from the Open-Meteo reading is excluded from the mean
   (but still reported with `outlier: true` for transparency).
3. Each metric is a weighted mean over the providers that actually reported it — missing
   values are never substituted with defaults.
4. The categorical `weathercode`/`condition` are taken from the highest-weighted provider
   that supplied one (Open-Meteo when available).
"""

from __future__ import annotations

import concurrent.futures
import os
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx

from services.open_meteo import (
    FORECAST_URL,
    code_to_condition,
    extract_weather_code,
)

# --------------------------------------------------------------------------- config

PROVIDER_WEIGHTS: dict[str, float] = {
    "Open-Meteo (ECMWF)": 2.0,
    "AccuWeather": 1.5,
    "WeatherAPI.com": 1.2,
    "Tomorrow.io": 1.2,
    "OpenWeatherMap": 1.1,
}

PROVIDER_ENV_KEYS: dict[str, tuple[str, ...]] = {
    "AccuWeather": ("ACCUWEATHER_KEY", "VITE_ACCUWEATHER_KEY"),
    "WeatherAPI.com": ("WEATHERAPI_KEY", "VITE_WEATHERAPI_KEY"),
    "Tomorrow.io": ("TOMORROW_KEY", "VITE_TOMORROW_KEY"),
    "OpenWeatherMap": ("OPENWEATHER_KEY", "VITE_OPENWEATHER_KEY"),
}

PROVIDER_TIMEOUT_S = float(os.getenv("FUSION_PROVIDER_TIMEOUT", "6"))
OUTLIER_TEMP_DELTA_C = float(os.getenv("FUSION_OUTLIER_DELTA_C", "7"))

NUMERIC_METRICS = ("temp", "feels_like", "humidity", "wind_kmh", "pressure_hpa", "uv_index")


@dataclass
class ProviderReading:
    name: str
    weight: float
    temp: float | None = None
    feels_like: float | None = None
    humidity: float | None = None
    wind_kmh: float | None = None
    pressure_hpa: float | None = None
    uv_index: float | None = None
    code: int | None = None
    condition: str | None = None
    outlier: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "weight": self.weight,
            "temp": self.temp,
            "feels_like": self.feels_like,
            "humidity": self.humidity,
            "wind_kmh": self.wind_kmh,
            "pressure_hpa": self.pressure_hpa,
            "uv_index": self.uv_index,
            "weather_code": self.code,
            "condition": self.condition,
            "outlier": self.outlier,
        }


def _num(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _provider_key(name: str) -> str | None:
    for env in PROVIDER_ENV_KEYS.get(name, ()):
        val = os.getenv(env)
        if val and not val.startswith("your_"):
            return val
    return None


def configured_providers() -> list[str]:
    """Names of providers that will be queried given the current environment."""
    names = ["Open-Meteo (ECMWF)"]
    names += [n for n in PROVIDER_ENV_KEYS if _provider_key(n)]
    return names


# --------------------------------------------------------------------------- fetchers


def _fetch_open_meteo(client: httpx.Client, lat: float, lon: float) -> ProviderReading | None:
    res = client.get(
        FORECAST_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "current": (
                "temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,"
                "surface_pressure,uv_index,weather_code"
            ),
            "timezone": "auto",
        },
    )
    res.raise_for_status()
    return reading_from_open_meteo_current(res.json().get("current") or {})


def reading_from_open_meteo_current(current: dict[str, Any]) -> ProviderReading | None:
    """Build an Open-Meteo reading from an already-fetched `current` block."""
    if not isinstance(current, dict) or current.get("temperature_2m") is None:
        return None
    code = extract_weather_code(current, default=0)
    return ProviderReading(
        name="Open-Meteo (ECMWF)",
        weight=PROVIDER_WEIGHTS["Open-Meteo (ECMWF)"],
        temp=_num(current.get("temperature_2m")),
        feels_like=_num(current.get("apparent_temperature")),
        humidity=_num(current.get("relative_humidity_2m")),
        wind_kmh=_num(current.get("wind_speed_10m")),
        pressure_hpa=_num(current.get("surface_pressure")),
        uv_index=_num(current.get("uv_index")),
        code=code,
        condition=code_to_condition(code),
    )


def _fetch_accuweather(client: httpx.Client, lat: float, lon: float) -> ProviderReading | None:
    key = _provider_key("AccuWeather")
    loc = client.get(
        "https://dataservice.accuweather.com/locations/v1/cities/geoposition/search",
        params={"apikey": key, "q": f"{lat},{lon}"},
    )
    loc.raise_for_status()
    loc_key = (loc.json() or {}).get("Key")
    if not loc_key:
        return None
    cond = client.get(
        f"https://dataservice.accuweather.com/currentconditions/v1/{loc_key}",
        params={"apikey": key, "details": "true"},
    )
    cond.raise_for_status()
    data = (cond.json() or [None])[0] or {}
    temp = _num(((data.get("Temperature") or {}).get("Metric") or {}).get("Value"))
    if temp is None:
        return None
    return ProviderReading(
        name="AccuWeather",
        weight=PROVIDER_WEIGHTS["AccuWeather"],
        temp=temp,
        feels_like=_num(((data.get("RealFeelTemperature") or {}).get("Metric") or {}).get("Value")),
        humidity=_num(data.get("RelativeHumidity")),
        wind_kmh=_num((((data.get("Wind") or {}).get("Speed") or {}).get("Metric") or {}).get("Value")),
        pressure_hpa=_num(((data.get("Pressure") or {}).get("Metric") or {}).get("Value")),
        uv_index=_num(data.get("UVIndex")),
        condition=data.get("WeatherText"),
    )


def _fetch_weatherapi(client: httpx.Client, lat: float, lon: float) -> ProviderReading | None:
    key = _provider_key("WeatherAPI.com")
    res = client.get(
        "https://api.weatherapi.com/v1/current.json",
        params={"key": key, "q": f"{lat},{lon}", "aqi": "yes"},
    )
    res.raise_for_status()
    curr = res.json().get("current") or {}
    temp = _num(curr.get("temp_c"))
    if temp is None:
        return None
    aq = curr.get("air_quality") or {}
    return ProviderReading(
        name="WeatherAPI.com",
        weight=PROVIDER_WEIGHTS["WeatherAPI.com"],
        temp=temp,
        feels_like=_num(curr.get("feelslike_c")),
        humidity=_num(curr.get("humidity")),
        wind_kmh=_num(curr.get("wind_kph")),
        pressure_hpa=_num(curr.get("pressure_mb")),
        uv_index=_num(curr.get("uv")),
        condition=(curr.get("condition") or {}).get("text"),
        extra={"pm2_5": _num(aq.get("pm2_5")), "pm10": _num(aq.get("pm10"))},
    )


def _fetch_tomorrow(client: httpx.Client, lat: float, lon: float) -> ProviderReading | None:
    key = _provider_key("Tomorrow.io")
    res = client.get(
        "https://api.tomorrow.io/v4/weather/realtime",
        params={"location": f"{lat},{lon}", "apikey": key, "units": "metric"},
    )
    res.raise_for_status()
    values = ((res.json().get("data") or {}).get("values")) or {}
    temp = _num(values.get("temperature"))
    if temp is None:
        return None
    wind_ms = _num(values.get("windSpeed"))
    return ProviderReading(
        name="Tomorrow.io",
        weight=PROVIDER_WEIGHTS["Tomorrow.io"],
        temp=temp,
        feels_like=_num(values.get("temperatureApparent")),
        humidity=_num(values.get("humidity")),
        wind_kmh=round(wind_ms * 3.6, 1) if wind_ms is not None else None,
        pressure_hpa=_num(values.get("pressureSurfaceLevel")),
        uv_index=_num(values.get("uvIndex")),
    )


def _fetch_openweather(client: httpx.Client, lat: float, lon: float) -> ProviderReading | None:
    key = _provider_key("OpenWeatherMap")
    res = client.get(
        "https://api.openweathermap.org/data/2.5/weather",
        params={"lat": lat, "lon": lon, "appid": key, "units": "metric"},
    )
    res.raise_for_status()
    body = res.json()
    main = body.get("main") or {}
    temp = _num(main.get("temp"))
    if temp is None:
        return None
    wind_ms = _num((body.get("wind") or {}).get("speed"))
    return ProviderReading(
        name="OpenWeatherMap",
        weight=PROVIDER_WEIGHTS["OpenWeatherMap"],
        temp=temp,
        feels_like=_num(main.get("feels_like")),
        humidity=_num(main.get("humidity")),
        wind_kmh=round(wind_ms * 3.6, 1) if wind_ms is not None else None,
        pressure_hpa=_num(main.get("pressure")),
        condition=((body.get("weather") or [{}])[0] or {}).get("description"),
    )


_FETCHERS: dict[str, Callable[[httpx.Client, float, float], ProviderReading | None]] = {
    "Open-Meteo (ECMWF)": _fetch_open_meteo,
    "AccuWeather": _fetch_accuweather,
    "WeatherAPI.com": _fetch_weatherapi,
    "Tomorrow.io": _fetch_tomorrow,
    "OpenWeatherMap": _fetch_openweather,
}


# --------------------------------------------------------------------------- fusion maths


def _weighted_mean(readings: list[ProviderReading], attr: str) -> float | None:
    pairs = [(getattr(r, attr), r.weight) for r in readings if getattr(r, attr) is not None]
    if not pairs:
        return None
    total_w = sum(w for _, w in pairs)
    return sum(v * w for v, w in pairs) / total_w if total_w else None


def _mark_outliers(readings: list[ProviderReading]) -> None:
    """Flag providers whose temperature is implausibly far from the Open-Meteo baseline."""
    base = next((r for r in readings if r.name == "Open-Meteo (ECMWF)" and r.temp is not None), None)
    if base is None:
        return
    for r in readings:
        if r is base or r.temp is None:
            continue
        r.outlier = abs(r.temp - base.temp) > OUTLIER_TEMP_DELTA_C


def fuse_readings(readings: list[ProviderReading]) -> dict[str, Any]:
    """Pure function: fuse a list of provider readings into a single conditions dict.

    Kept side-effect free so it can be unit-tested without network access.
    """
    readings = [r for r in readings if r is not None and r.temp is not None]
    if not readings:
        return {"error": "No provider returned temperature"}

    readings.sort(key=lambda r: r.weight, reverse=True)
    _mark_outliers(readings)
    usable = [r for r in readings if not r.outlier] or readings

    temp = _weighted_mean(usable, "temp")
    feels = _weighted_mean(usable, "feels_like")
    humidity = _weighted_mean(usable, "humidity")
    wind = _weighted_mean(usable, "wind_kmh")
    pressure = _weighted_mean(usable, "pressure_hpa")
    uv = _weighted_mean([r for r in usable if (r.uv_index or 0) > 0], "uv_index")

    # Categorical fields come from the most trusted provider that supplied them.
    code_src = next((r for r in usable if r.code is not None), None)
    cond_src = next((r for r in usable if r.condition), None)
    if cond_src is None and code_src is not None:
        code_src.condition = code_to_condition(code_src.code, "Normal")
        cond_src = code_src
    elif cond_src is not None and code_src is not None and cond_src.weight < code_src.weight:
        # Never let a lower-trust vendor override the top provider's WMO classification.
        code_src.condition = code_to_condition(code_src.code, cond_src.condition)
        cond_src = code_src

    temps = [r.temp for r in usable]
    spread = round(max(temps) - min(temps), 1) if len(temps) > 1 else 0.0
    if len(usable) == 1:
        confidence = "single-source"
    elif spread <= 1.5:
        confidence = "high"
    elif spread <= 3.5:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        # Legacy keys (agent tools / widgets / mobile) — keep stable.
        "temperature_2m": round(temp, 1),
        "apparent_temperature": round(feels if feels is not None else temp, 1),
        "relative_humidity_2m": round(humidity) if humidity is not None else None,
        "wind_speed_10m": round(wind, 1) if wind is not None else None,
        "weathercode": code_src.code if code_src else None,
        "condition": cond_src.condition if cond_src else "Normal",
        "providers_used": [r.name for r in usable],
        # Extended telemetry.
        "surface_pressure": round(pressure, 1) if pressure is not None else None,
        "uv_index": round(uv, 1) if uv is not None else None,
        "temp_spread_c": spread,
        "confidence": confidence,
        "warning": (
            "Providers disagree significantly on temperature."
            if confidence == "low" else
            "Only one provider returned usable data."
            if confidence == "single-source" else None
        ),
        "providers": [r.as_dict() for r in readings],
        "weights": {r.name: r.weight for r in readings},
    }


# --------------------------------------------------------------------------- entry point


def fuse_current_weather(
    latitude: float,
    longitude: float,
    *,
    open_meteo_current: dict[str, Any] | None = None,
    timeout_s: float | None = None,
) -> dict[str, Any]:
    """Query every configured provider in parallel and fuse the results.

    `open_meteo_current` lets callers that already fetched Open-Meteo (mobile `/weather`)
    skip the duplicate request.
    """
    timeout = timeout_s or PROVIDER_TIMEOUT_S
    names = configured_providers()
    readings: list[ProviderReading] = []

    pre_fetched = reading_from_open_meteo_current(open_meteo_current) if open_meteo_current else None
    if pre_fetched is not None:
        readings.append(pre_fetched)
        names = [n for n in names if n != "Open-Meteo (ECMWF)"]

    if names:
        try:
            with httpx.Client(timeout=timeout) as client:
                with concurrent.futures.ThreadPoolExecutor(max_workers=len(names)) as pool:
                    futures = {pool.submit(_FETCHERS[n], client, latitude, longitude): n for n in names}
                    done, _ = concurrent.futures.wait(futures, timeout=timeout + 1)
                    for fut in done:
                        try:
                            reading = fut.result()
                            if reading is not None:
                                readings.append(reading)
                        except Exception as exc:  # provider-level failure is non-fatal
                            print(f"[fusion] {futures[fut]} failed: {exc}")
        except Exception as exc:
            print(f"[fusion] provider pool failed: {exc}")

    if not readings:
        return {"error": "Failed to retrieve weather data from providers"}
    return fuse_readings(readings)
