"""Fill honest gaps in a selected forecast with clearly-attributed secondary data.

WeatherNext (and IMD / AccuWeather forecasts) do not ship astronomy
(sunrise/sunset), a UV index or air quality, and a ``minimal`` BigQuery column
profile leaves humidity, pressure, cloud cover and therefore the sky condition
unselected. Until now the client rendered "—" for all of those tiles even
though the information exists elsewhere.

This module supplements *only the fields the selected provider left ``None``*
from Open-Meteo and records where every value came from in ``field_sources``.
The primary forecast — temperature, precipitation, wind speed, run/provenance —
is never overwritten, so a WeatherNext payload stays a WeatherNext payload.

Rules
- one bounded Open-Meteo forecast call (+ one air-quality call), 6 s timeout each
- any failure is recorded and swallowed: the primary forecast is returned as-is
- every filled field is listed by name so the UI can say "via Open-Meteo"
- disabled with ``WEATHER_SUPPLEMENT_ENABLED=0`` (tests, offline demos)
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from services.forecast_models import NormalizedForecast, ProviderName
from services.open_meteo import (
    AIR_QUALITY_URL,
    FORECAST_URL,
    UpstreamError,
    code_to_condition,
    get_json,
)

SUPPLEMENT_PROVIDER = "open_meteo"
_CACHE_TTL_SECONDS = 15 * 60
_CELL_DEG = 0.1

# Fields a supplement may fill, in the order they are reported.
CURRENT_FIELDS = (
    "feels_like_c",
    "humidity_percent",
    "pressure_hpa",
    "wind_direction_deg",
    "uv_index",
    "cloud_cover_percent",
    "condition",
)
DAILY_FIELDS = ("sunrise", "sunset", "uv_index_max")

_cache: dict[str, tuple[float, dict]] = {}
_cache_lock = threading.Lock()


def is_enabled() -> bool:
    return os.getenv("WEATHER_SUPPLEMENT_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _cell_key(lat: float, lon: float, days: int) -> str:
    return f"{round(round(lat / _CELL_DEG) * _CELL_DEG, 2)}:{round(round(lon / _CELL_DEG) * _CELL_DEG, 2)}:{days}"


def _finite(value: Any) -> Optional[float]:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num if num == num and abs(num) != float("inf") else None


def _parse_local(value: Any, offset_seconds: int) -> Optional[datetime]:
    """Open-Meteo ``timezone=auto`` timestamps are naive local; convert to UTC."""
    if not value:
        return None
    try:
        naive = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if naive.tzinfo is not None:
        return naive.astimezone(timezone.utc)
    return (naive - timedelta(seconds=offset_seconds)).replace(tzinfo=timezone.utc)


def fetch_supplement(lat: float, lon: float, *, forecast_days: int = 7) -> dict:
    """Fetch (cached) Open-Meteo secondary products for ``lat``/``lon``.

    Returns a dict with ``current``, ``hourly`` (by UTC hour), ``daily`` (by
    date), ``air_quality``, ``timezone``, ``utc_offset_seconds`` and ``errors``.
    Never raises.
    """
    days = max(1, min(int(forecast_days or 7), 16))
    key = _cell_key(lat, lon, days)
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < _CACHE_TTL_SECONDS:
            return {**hit[1], "cache_hit": True}

    out: dict[str, Any] = {
        "provider": SUPPLEMENT_PROVIDER,
        "current": {},
        "hourly": {},
        "daily": {},
        "air_quality": None,
        "timezone": None,
        "utc_offset_seconds": None,
        "errors": [],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "cache_hit": False,
    }

    try:
        data = get_json(
            FORECAST_URL,
            {
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,"
                           "wind_direction_10m,surface_pressure,pressure_msl,cloud_cover,uv_index",
                "hourly": "weather_code,relative_humidity_2m,cloud_cover,uv_index,apparent_temperature",
                "daily": "sunrise,sunset,uv_index_max,weather_code",
                "forecast_days": days,
                "timezone": "auto",
            },
            timeout=6.0,
        )
        offset = int(data.get("utc_offset_seconds") or 0)
        out["timezone"] = data.get("timezone")
        out["utc_offset_seconds"] = offset

        cur = data.get("current") or {}
        code = cur.get("weather_code")
        out["current"] = {
            "feels_like_c": _finite(cur.get("apparent_temperature")),
            "humidity_percent": _finite(cur.get("relative_humidity_2m")),
            "pressure_hpa": _finite(cur.get("pressure_msl")) or _finite(cur.get("surface_pressure")),
            "pressure_type": "msl" if _finite(cur.get("pressure_msl")) is not None else "surface",
            "wind_direction_deg": _finite(cur.get("wind_direction_10m")),
            "cloud_cover_percent": _finite(cur.get("cloud_cover")),
            "uv_index": _finite(cur.get("uv_index")),
            "weather_code": int(code) if _finite(code) is not None else None,
            "condition": code_to_condition(code) if _finite(code) is not None else None,
            "time_utc": _parse_local(cur.get("time"), offset),
        }

        hourly = data.get("hourly") or {}
        times = hourly.get("time") or []
        codes = hourly.get("weather_code") or []
        hums = hourly.get("relative_humidity_2m") or []
        clouds = hourly.get("cloud_cover") or []
        uvs = hourly.get("uv_index") or []
        feels = hourly.get("apparent_temperature") or []
        by_hour: dict[str, dict] = {}
        for i, raw in enumerate(times):
            t = _parse_local(raw, offset)
            if t is None:
                continue
            c = codes[i] if i < len(codes) else None
            by_hour[t.isoformat()] = {
                "weather_code": int(c) if _finite(c) is not None else None,
                "condition": code_to_condition(c) if _finite(c) is not None else None,
                "humidity_percent": _finite(hums[i]) if i < len(hums) else None,
                "cloud_cover_percent": _finite(clouds[i]) if i < len(clouds) else None,
                "uv_index": _finite(uvs[i]) if i < len(uvs) else None,
                "feels_like_c": _finite(feels[i]) if i < len(feels) else None,
            }
        out["hourly"] = by_hour

        daily = data.get("daily") or {}
        d_times = daily.get("time") or []
        d_rise = daily.get("sunrise") or []
        d_set = daily.get("sunset") or []
        d_uv = daily.get("uv_index_max") or []
        d_codes = daily.get("weather_code") or []
        by_date: dict[str, dict] = {}
        for i, date in enumerate(d_times):
            c = d_codes[i] if i < len(d_codes) else None
            by_date[str(date)] = {
                "sunrise": d_rise[i] if i < len(d_rise) else None,
                "sunset": d_set[i] if i < len(d_set) else None,
                "uv_index_max": _finite(d_uv[i]) if i < len(d_uv) else None,
                "weather_code": int(c) if _finite(c) is not None else None,
                "condition": code_to_condition(c) if _finite(c) is not None else None,
            }
        out["daily"] = by_date
    except UpstreamError as exc:
        out["errors"].append({"call": "forecast", "reason": str(exc), "status_code": exc.status_code})
    except Exception as exc:  # defensive: supplements must never break the primary forecast
        out["errors"].append({"call": "forecast", "reason": f"exception_{type(exc).__name__}"})

    try:
        aq = get_json(
            AIR_QUALITY_URL,
            {"latitude": lat, "longitude": lon, "current": "european_aqi,us_aqi,pm2_5,pm10", "timezone": "auto"},
            timeout=6.0,
        )
        cur_aq = aq.get("current") or {}
        if any(cur_aq.get(k) is not None for k in ("european_aqi", "pm2_5")):
            out["air_quality"] = {
                "european_aqi": _finite(cur_aq.get("european_aqi")),
                "us_aqi": _finite(cur_aq.get("us_aqi")),
                "pm2_5": _finite(cur_aq.get("pm2_5")),
                "pm10": _finite(cur_aq.get("pm10")),
                "standard": "european",
                "source": SUPPLEMENT_PROVIDER,
                "time": cur_aq.get("time"),
            }
    except UpstreamError as exc:
        out["errors"].append({"call": "air_quality", "reason": str(exc), "status_code": exc.status_code})
    except Exception as exc:
        out["errors"].append({"call": "air_quality", "reason": f"exception_{type(exc).__name__}"})

    if not out["errors"]:
        with _cache_lock:
            _cache[key] = (now, out)
    return out


def supplement_forecast(
    forecast: NormalizedForecast,
    lat: float,
    lon: float,
    *,
    forecast_days: int = 7,
    supplement: Optional[dict] = None,
) -> dict:
    """Fill ``None`` fields of ``forecast`` in place and return ``field_sources``.

    ``field_sources`` maps every user-visible field to the provider that
    supplied it (``weathernext``, ``open_meteo`` …) or ``None`` when nobody
    could. The ``_supplement`` entry describes the secondary fetch itself.
    """
    primary = forecast.provenance.selected_source.value
    # Cached forecasts are shared objects that may already have been
    # supplemented on an earlier request; keep their attribution honest.
    previous: dict[str, Any] = {k: v for k, v in (getattr(forecast, "field_sources", None) or {}).items() if k != "_supplement"}
    sources: dict[str, Any] = {}
    filled: list[str] = []

    def mark(field: str, value: Any, *, from_supplement: bool) -> None:
        if value is None:
            sources.setdefault(field, None)
            return
        if not from_supplement and previous.get(field) == SUPPLEMENT_PROVIDER:
            sources[field] = SUPPLEMENT_PROVIDER
            return
        sources[field] = SUPPLEMENT_PROVIDER if from_supplement else primary
        if from_supplement:
            filled.append(field)

    cur = forecast.current
    # Baseline attribution for what the primary provider already supplied.
    if cur is not None:
        for field in ("temperature_c", "wind_speed_kmh", "precipitation_mm", "precipitation_probability") + CURRENT_FIELDS:
            mark(field, getattr(cur, field, None), from_supplement=False)
    if forecast.daily:
        first = forecast.daily[0]
        for field in DAILY_FIELDS:
            mark(field, first.get(field), from_supplement=False)
    mark("air_quality", forecast.air_quality, from_supplement=False)

    meta: dict[str, Any] = {"provider": SUPPLEMENT_PROVIDER, "enabled": is_enabled(), "attempted": False,
                            "filled": filled, "errors": [], "cache_hit": False}

    # Open-Meteo already carries everything; nothing to add.
    if forecast.provenance.selected_source == ProviderName.OPEN_METEO or not is_enabled():
        sources["_supplement"] = meta
        try:
            forecast.field_sources = sources
        except Exception:
            pass
        return sources

    meta["attempted"] = True
    supp = supplement if supplement is not None else fetch_supplement(lat, lon, forecast_days=forecast_days)
    meta["errors"] = list(supp.get("errors") or [])
    meta["cache_hit"] = bool(supp.get("cache_hit"))

    # Location / timezone metadata (WeatherNext only knows a solar approximation).
    if supp.get("timezone"):
        loc = dict(forecast.location or {})
        loc.setdefault("timezone_approximation", loc.get("timezone"))
        loc["timezone"] = supp["timezone"]
        loc["utc_offset_seconds"] = supp.get("utc_offset_seconds")
        loc["timezone_source"] = SUPPLEMENT_PROVIDER
        forecast.location = loc

    s_cur = supp.get("current") or {}
    if cur is not None and s_cur:
        for field in CURRENT_FIELDS:
            if getattr(cur, field, None) is None and s_cur.get(field) is not None:
                setattr(cur, field, s_cur[field])
                if field == "pressure_hpa":
                    cur.pressure_type = s_cur.get("pressure_type", "surface")
                if field == "condition" and cur.weather_code is None:
                    cur.weather_code = s_cur.get("weather_code")
                    if cur.missing_reason == "cloud_cover_not_selected":
                        cur.missing_reason = None
                mark(field, s_cur[field], from_supplement=True)

    s_hourly = supp.get("hourly") or {}
    hourly_filled = 0
    if s_hourly:
        for p in forecast.hourly:
            row = s_hourly.get(p.time_utc.astimezone(timezone.utc).isoformat())
            if not row:
                continue
            touched = False
            if p.condition is None and row.get("condition") is not None:
                p.condition = row["condition"]
                p.weather_code = row.get("weather_code")
                if p.missing_reason == "cloud_cover_not_selected":
                    p.missing_reason = None
                touched = True
            for field in ("humidity_percent", "cloud_cover_percent", "uv_index", "feels_like_c"):
                if getattr(p, field, None) is None and row.get(field) is not None:
                    setattr(p, field, row[field])
                    touched = True
            hourly_filled += int(touched)
    if hourly_filled or previous.get("hourly_condition") == SUPPLEMENT_PROVIDER:
        sources["hourly_condition"] = SUPPLEMENT_PROVIDER
        if hourly_filled:
            filled.append(f"hourly:{hourly_filled}")

    s_daily = supp.get("daily") or {}
    if s_daily and forecast.daily:
        for day in forecast.daily:
            row = s_daily.get(str(day.get("date")))
            if not row:
                continue
            for field in DAILY_FIELDS:
                if day.get(field) is None and row.get(field) is not None:
                    day[field] = row[field]
                    day.setdefault("field_sources", {})[field] = SUPPLEMENT_PROVIDER
            if day.get("condition") is None and row.get("condition") is not None:
                day["condition"] = row["condition"]
                day["weather_code"] = row.get("weather_code")
                day.setdefault("field_sources", {})["condition"] = SUPPLEMENT_PROVIDER
        first = forecast.daily[0]
        for field in DAILY_FIELDS:
            if sources.get(field) is None and first.get(field) is not None:
                mark(field, first.get(field), from_supplement=True)

    if forecast.air_quality is None and supp.get("air_quality"):
        forecast.air_quality = supp["air_quality"]
        mark("air_quality", forecast.air_quality, from_supplement=True)

    methods = dict(forecast.provenance.methods or {})
    methods["supplement"] = (
        f"{SUPPLEMENT_PROVIDER} fills only null fields ({', '.join(filled) if filled else 'nothing filled'}); "
        "primary forecast values are never overwritten"
    )
    try:
        # ForecastProvenance is frozen; methods is a mutable dict we can update in place.
        forecast.provenance.methods.clear()
        forecast.provenance.methods.update(methods)
    except Exception:
        pass

    sources["_supplement"] = meta
    try:
        forecast.field_sources = sources
    except Exception:
        pass
    return sources


# Reasons that mean "this provider was simply not set up", not "it failed".
NOT_CONFIGURED_REASONS = {
    "missing_credentials",
    "credentials_missing_credentials",
    "credentials_invalid_config",
    "weathernext_disabled",
    "not_configured",
    "unknown_provider",
    "disabled",
}


def is_degraded(fallback_reasons: list[dict], *, is_stale: bool = False) -> bool:
    """True only when a *configured* higher-priority provider failed or data is stale.

    Skipping IMD because no key is configured is not a degradation the user
    should be warned about; a WeatherNext query error or a stale run is.
    """
    if is_stale:
        return True
    for reason in fallback_reasons or []:
        code = str(reason.get("reason") or "")
        if code in NOT_CONFIGURED_REASONS or code.startswith("credentials_"):
            continue
        return True
    return False
