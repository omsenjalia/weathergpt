"""Fill gaps in the selected forecast from Open-Meteo, with per-field attribution.

IMD publishes no hourly series, rain probability or UV; WeatherNext has no
astronomy, UV or air quality. Only fields the selected provider left ``None``
are filled — primary values are never overwritten — and ``field_sources``
records who supplied every user-visible field, so the apps can show
"via Open-Meteo" instead of "—" or, worse, a misattributed number.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Optional

from weathergpt import http
from weathergpt.config import settings
from weathergpt.weather.models import DayPoint, Forecast
from weathergpt.weather.providers import open_meteo

SUPPLEMENT = "open_meteo"
CURRENT_FIELDS = ("temperature_c", "feels_like_c", "humidity_percent", "wind_speed_kmh", "wind_direction_deg",
                  "pressure_hpa", "precipitation_mm", "precipitation_probability", "cloud_cover_percent",
                  "uv_index", "condition")
DAILY_FIELDS = ("high_c", "low_c", "rain_probability", "precipitation_mm", "wind_kmh_max",
                "sunrise", "sunset", "uv_index_max", "condition")
HOURLY_FIELDS = ("temperature_c", "feels_like_c", "humidity_percent", "wind_speed_kmh", "wind_direction_deg",
                 "precipitation_mm", "precipitation_probability", "cloud_cover_percent", "uv_index", "pressure_hpa")


def attribute_only(forecast: Forecast) -> dict:
    """field_sources for a forecast that is not supplemented."""
    primary = forecast.provenance.source
    sources: dict[str, Any] = {}
    cur = forecast.current
    for f in CURRENT_FIELDS:
        sources[f] = primary if cur is not None and getattr(cur, f) is not None else None
    first = forecast.daily[0] if forecast.daily else None
    for f in ("sunrise", "sunset", "uv_index_max"):
        sources[f] = primary if first is not None and getattr(first, f) is not None else None
    sources["hourly"] = primary if forecast.hourly else None
    sources["air_quality"] = (forecast.air_quality or {}).get("source") if forecast.air_quality else None
    return sources


def supplement(forecast: Forecast, lat: float, lon: float, forecast_days: int, *, enabled: Optional[bool] = None) -> dict:
    """Fill ``None`` fields of ``forecast`` in place; return ``field_sources``."""
    primary = forecast.provenance.source
    enabled = settings().supplement_enabled if enabled is None else enabled
    meta: dict[str, Any] = {"provider": SUPPLEMENT, "enabled": enabled, "attempted": False, "filled": [],
                            "errors": [], "cache_hit": False}
    sources = attribute_only(forecast)
    if primary == SUPPLEMENT or not enabled:
        sources["_supplement"] = meta
        forecast.field_sources = sources
        return sources

    meta["attempted"] = True
    try:
        om = open_meteo.parse(open_meteo.fetch_raw(lat, lon, forecast_days), lat, lon, forecast_days)
    except http.UpstreamError as exc:
        meta["errors"].append({"call": "forecast", "reason": exc.reason})
        om = None
    except Exception as exc:
        meta["errors"].append({"call": "forecast", "reason": f"exception_{type(exc).__name__}"})
        om = None
    filled: list[str] = meta["filled"]

    if om is not None:
        # Timezone: IMD knows IST exactly; WeatherNext only has a solar approximation.
        if forecast.location.get("timezone_source") not in ("imd",) and om.location.get("timezone"):
            forecast.location.update(timezone=om.location["timezone"],
                                     utc_offset_seconds=om.location["utc_offset_seconds"], timezone_source=SUPPLEMENT)

        if forecast.current is None and om.current is not None:
            forecast.current = dataclasses.replace(om.current)
            forecast.current_kind = "model"
            for f in CURRENT_FIELDS:
                if getattr(forecast.current, f) is not None:
                    sources[f] = SUPPLEMENT
            filled.append("current")
        elif forecast.current is not None and om.current is not None:
            for f in CURRENT_FIELDS:
                if getattr(forecast.current, f) is None and getattr(om.current, f) is not None:
                    setattr(forecast.current, f, getattr(om.current, f))
                    if f == "condition":
                        forecast.current.weather_code = om.current.weather_code
                    if f == "pressure_hpa":
                        forecast.current.pressure_type = om.current.pressure_type
                    sources[f] = SUPPLEMENT
                    filled.append(f)

        if not forecast.hourly and om.hourly:
            forecast.hourly = [dataclasses.replace(p) for p in om.hourly]
            sources["hourly"] = SUPPLEMENT
            filled.append("hourly")
        elif forecast.hourly and om.hourly:
            by_time = {p.time_utc: p for p in om.hourly}
            touched = 0
            for p in forecast.hourly:
                src = by_time.get(p.time_utc)
                if src is None:
                    continue
                changed = False
                if p.condition is None and src.condition is not None:
                    p.condition, p.weather_code = src.condition, src.weather_code
                    if p.missing_reason == "cloud_cover_not_selected":
                        p.missing_reason = None
                    changed = True
                for f in HOURLY_FIELDS:
                    if getattr(p, f) is None and getattr(src, f) is not None:
                        setattr(p, f, getattr(src, f))
                        changed = True
                touched += changed
            if touched:
                sources["hourly_condition"] = SUPPLEMENT
                filled.append(f"hourly:{touched}")

        by_date = {d.date: d for d in om.daily}
        for day in forecast.daily:
            src = by_date.get(day.date)
            if src is None:
                continue
            for f in DAILY_FIELDS:
                if getattr(day, f) is None and getattr(src, f) is not None:
                    setattr(day, f, getattr(src, f))
                    if f == "condition":
                        day.weather_code = src.weather_code
                    day.field_sources[f] = SUPPLEMENT
        if forecast.daily:
            first = forecast.daily[0]
            for f in ("sunrise", "sunset", "uv_index_max"):
                if first.field_sources.get(f) == SUPPLEMENT:
                    sources[f] = SUPPLEMENT
                    filled.append(f)
            if any(d.field_sources for d in forecast.daily):
                filled.append("daily")

    if forecast.air_quality is None:
        aq = open_meteo.fetch_air_quality(lat, lon)
        if aq:
            forecast.air_quality = aq
            sources["air_quality"] = SUPPLEMENT
            filled.append("air_quality")
        else:
            meta["errors"].append({"call": "air_quality", "reason": "unavailable"})

    forecast.provenance.methods["supplement"] = (
        f"{SUPPLEMENT} filled only null fields ({', '.join(filled) or 'nothing'}); primary values are never overwritten"
    )
    sources["_supplement"] = meta
    forecast.field_sources = sources
    return sources


def daily_primary(day: DayPoint, primary: str) -> dict:
    """Per-day attribution: every non-null field not filled by the supplement is the primary's."""
    out = {}
    for f in DAILY_FIELDS:
        if getattr(day, f) is None:
            out[f] = None
        else:
            out[f] = day.field_sources.get(f, primary)
    return out
