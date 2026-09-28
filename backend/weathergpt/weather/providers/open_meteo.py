"""Open-Meteo: key-less global baseline and the source of supplemental fields.

``timezone=auto`` makes Open-Meteo return *naive local* timestamps; they are
converted to UTC with the ``utc_offset_seconds`` the response carries. (The
previous backend stamped local times as UTC, shifting every Indian hourly
bucket by 5.5 h.)
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from weathergpt import http
from weathergpt.runtime import make_cache
from weathergpt.weather.codes import wmo_condition
from weathergpt.weather.models import DayPoint, Forecast, HourPoint, Provenance, ProviderResult, as_int, finite
from weathergpt.weather.providers.base import Provider

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

_CURRENT = ("temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,"
            "wind_direction_10m,wind_gusts_10m,pressure_msl,surface_pressure,precipitation,cloud_cover,uv_index")
_HOURLY = ("temperature_2m,apparent_temperature,relative_humidity_2m,precipitation_probability,precipitation,"
           "weather_code,wind_speed_10m,wind_direction_10m,wind_gusts_10m,pressure_msl,cloud_cover,uv_index")
_DAILY = ("temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum,weather_code,"
          "sunrise,sunset,uv_index_max,wind_speed_10m_max")

_forecast_cache = make_cache("open_meteo_forecast", 256)
_aq_cache = make_cache("open_meteo_air_quality", 256)
FORECAST_TTL = 600
AQ_TTL = 1800


def _cell(lat: float, lon: float) -> str:
    return f"{round(lat, 2)}:{round(lon, 2)}"


def local_to_utc(raw: Any, offset_seconds: int) -> Optional[datetime]:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc)
    return (dt - timedelta(seconds=offset_seconds)).replace(tzinfo=timezone.utc)


def fetch_raw(lat: float, lon: float, days: int = 7) -> dict:
    """Cached raw forecast response (16 days max). Raises ``http.UpstreamError``."""
    days = max(1, min(int(days), 16))
    # One cached call per cell serves every horizon up to what was fetched.
    fetch_days = 16 if days > 7 else 7
    key = f"{_cell(lat, lon)}:{fetch_days}"
    hit = _forecast_cache.get(key)
    if hit is not None:
        return hit
    data = http.get_json(FORECAST_URL, {
        "latitude": round(lat, 4), "longitude": round(lon, 4),
        "current": _CURRENT, "hourly": _HOURLY, "daily": _DAILY,
        "forecast_days": fetch_days, "timezone": "auto", "wind_speed_unit": "kmh",
    }, timeout=10.0)
    if not isinstance(data, dict) or "hourly" not in data:
        raise http.UpstreamError("invalid_response", "Open-Meteo response had no hourly block", 502)
    _forecast_cache.set(key, data, FORECAST_TTL)
    return data


def fetch_air_quality(lat: float, lon: float) -> Optional[dict]:
    """Current air quality (European + US AQI, PM). None when unavailable. Never raises."""
    key = _cell(lat, lon)
    hit = _aq_cache.get(key)
    if hit is not None:
        return hit or None
    try:
        data = http.get_json(AIR_QUALITY_URL, {
            "latitude": round(lat, 4), "longitude": round(lon, 4),
            "current": "european_aqi,us_aqi,pm2_5,pm10", "timezone": "auto",
        }, timeout=6.0)
    except http.UpstreamError:
        return None
    cur = (data or {}).get("current") or {}
    out = {
        "european_aqi": finite(cur.get("european_aqi"), 0, 1000),
        "us_aqi": finite(cur.get("us_aqi"), 0, 1000),
        "pm2_5": finite(cur.get("pm2_5"), 0, 2000),
        "pm10": finite(cur.get("pm10"), 0, 5000),
        "standard": "european",
        "source": "open_meteo",
        "time": cur.get("time"),
    }
    if out["european_aqi"] is None and out["us_aqi"] is None and out["pm2_5"] is None:
        _aq_cache.set(key, {}, 300)
        return None
    _aq_cache.set(key, out, AQ_TTL)
    return out


def _col(block: dict, name: str, i: int) -> Any:
    arr = block.get(name)
    return arr[i] if isinstance(arr, list) and i < len(arr) else None


def _pressure(block: dict, i: Optional[int] = None) -> tuple[Optional[float], Optional[str]]:
    get = (lambda k: block.get(k)) if i is None else (lambda k: _col(block, k, i))
    msl = finite(get("pressure_msl"), 800, 1200)
    if msl is not None:
        return msl, "msl"
    sfc = finite(get("surface_pressure"), 300, 1200)
    return (sfc, "surface") if sfc is not None else (None, None)


def parse(data: dict, lat: float, lon: float, forecast_days: int) -> Forecast:
    offset = int(finite(data.get("utc_offset_seconds")) or 0)
    now = datetime.now(timezone.utc)

    cur = data.get("current") or {}
    code = as_int(cur.get("weather_code"))
    pressure, ptype = _pressure(cur)
    current = HourPoint(
        time_utc=local_to_utc(cur.get("time"), offset) or now,
        temperature_c=finite(cur.get("temperature_2m"), -90, 65),
        feels_like_c=finite(cur.get("apparent_temperature"), -100, 80),
        humidity_percent=finite(cur.get("relative_humidity_2m"), 0, 100),
        wind_speed_kmh=finite(cur.get("wind_speed_10m"), 0, 500),
        wind_direction_deg=finite(cur.get("wind_direction_10m"), 0, 360),
        wind_gust_kmh=finite(cur.get("wind_gusts_10m"), 0, 600),
        pressure_hpa=pressure, pressure_type=ptype,
        precipitation_mm=finite(cur.get("precipitation"), 0, 1000),
        weather_code=code, condition=wmo_condition(code),
        cloud_cover_percent=finite(cur.get("cloud_cover"), 0, 100),
        uv_index=finite(cur.get("uv_index"), 0, 20),
    ) if cur else None

    h = data.get("hourly") or {}
    hourly: list[HourPoint] = []
    for i, raw in enumerate(h.get("time") or []):
        t = local_to_utc(raw, offset)
        if t is None:
            continue
        hc = as_int(_col(h, "weather_code", i))
        p, pt = _pressure(h, i)
        hourly.append(HourPoint(
            time_utc=t,
            temperature_c=finite(_col(h, "temperature_2m", i), -90, 65),
            feels_like_c=finite(_col(h, "apparent_temperature", i), -100, 80),
            humidity_percent=finite(_col(h, "relative_humidity_2m", i), 0, 100),
            precipitation_probability=finite(_col(h, "precipitation_probability", i), 0, 100),
            precipitation_mm=finite(_col(h, "precipitation", i), 0, 1000),
            weather_code=hc, condition=wmo_condition(hc),
            wind_speed_kmh=finite(_col(h, "wind_speed_10m", i), 0, 500),
            wind_direction_deg=finite(_col(h, "wind_direction_10m", i), 0, 360),
            wind_gust_kmh=finite(_col(h, "wind_gusts_10m", i), 0, 600),
            pressure_hpa=p, pressure_type=pt,
            cloud_cover_percent=finite(_col(h, "cloud_cover", i), 0, 100),
            uv_index=finite(_col(h, "uv_index", i), 0, 20),
        ))

    d = data.get("daily") or {}
    daily: list[DayPoint] = []
    for i, date in enumerate((d.get("time") or [])[:forecast_days]):
        dc = as_int(_col(d, "weather_code", i))
        daily.append(DayPoint(
            date=str(date),
            high_c=finite(_col(d, "temperature_2m_max", i), -90, 65),
            low_c=finite(_col(d, "temperature_2m_min", i), -90, 65),
            rain_probability=finite(_col(d, "precipitation_probability_max", i), 0, 100),
            precipitation_mm=finite(_col(d, "precipitation_sum", i), 0, 2000),
            wind_kmh_max=finite(_col(d, "wind_speed_10m_max", i), 0, 500),
            weather_code=dc, condition=wmo_condition(dc),
            sunrise=_col(d, "sunrise", i), sunset=_col(d, "sunset", i),
            uv_index_max=finite(_col(d, "uv_index_max", i), 0, 20),
            hours_covered=24, covers_full_day=True, precipitation_interval="24h",
            statistic="deterministic", source="open_meteo",
        ))

    return Forecast(
        location={"lat": lat, "lon": lon, "timezone": data.get("timezone"),
                  "timezone_abbreviation": data.get("timezone_abbreviation"),
                  "utc_offset_seconds": offset, "timezone_source": "open_meteo",
                  "elevation_m": finite(data.get("elevation"))},
        current=current,
        current_kind="model",
        hourly=hourly,
        daily=daily,
        provenance=Provenance(
            source="open_meteo", model="open_meteo_best_match", freshness_status="fresh",
            issued_at_utc=now, requested_lat=lat, requested_lon=lon,
            sampled_lat=finite(data.get("latitude")), sampled_lon=finite(data.get("longitude")),
            spatial_method="open_meteo_grid", resolution_deg=0.1, sources=["open_meteo"],
            horizon_hours=len(hourly),
        ),
    )


class OpenMeteoProvider(Provider):
    name = "open_meteo"

    def availability(self, lat, lon):
        return True, None, None

    def fetch(self, lat, lon, *, forecast_days, **options) -> ProviderResult:
        started = time.perf_counter()
        try:
            data = fetch_raw(lat, lon, forecast_days)
            forecast = parse(data, lat, lon, forecast_days)
            forecast.air_quality = fetch_air_quality(lat, lon)
        except http.UpstreamError as exc:
            return ProviderResult(False, reason=exc.reason, message=str(exc), transient=True,
                                  latency_ms=(time.perf_counter() - started) * 1000)
        except Exception as exc:  # malformed payloads must not crash the chain
            return ProviderResult(False, reason=f"parse_error_{type(exc).__name__}", message=str(exc)[:200],
                                  transient=True, latency_ms=(time.perf_counter() - started) * 1000)
        return ProviderResult(True, forecast=forecast, latency_ms=(time.perf_counter() - started) * 1000)
