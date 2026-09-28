"""The weather wire format — one builder for ``/v2/weather`` and ``/weather``.

Both apps (weathergpt-app and weathergpt-android) share the same parsers, which
accept either the nested v2 shape (``current`` / ``daily`` / ``hourly``) or the
flat legacy shape (``temperature_c`` / ``forecast``). The payload carries both,
so every client version renders it. Aliases are listed in ``HOURLY_ALIASES``.

Null semantics: absent data is ``null`` — never 0 (``weather_code`` 0 is "clear").
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from weathergpt.weather.models import SCHEMA_VERSION, SELECTION_POLICY_VERSION, Forecast, HourPoint
from weathergpt.weather.service import Selection
from weathergpt.weather.summaries import precip_next_24h, temperature_spread
from weathergpt.weather.supplement import daily_primary

# legacy key -> canonical key
HOURLY_ALIASES = {"time": "time_utc", "rain_probability": "precipitation_probability",
                  "wind_kmh": "wind_speed_kmh", "humidity": "humidity_percent"}


def hour_row(p: HourPoint) -> dict:
    row = p.to_dict()
    for legacy, canonical in HOURLY_ALIASES.items():
        row[legacy] = row[canonical]
    return row


def current_row(forecast: Forecast) -> Optional[dict]:
    if forecast.current is None:
        return None
    row = forecast.current.to_dict()
    row["kind"] = forecast.current_kind
    if forecast.current_kind == "observation" and forecast.provenance.station:
        observing = forecast.provenance.station.get("observation_station") or forecast.provenance.station
        row["station"] = {k: observing.get(k) for k in ("code", "name", "distance_km")}
    return row


def upcoming_hours(forecast: Forecast, limit: int, now: Optional[datetime] = None) -> list[HourPoint]:
    """Hours from the bucket that contains ``now`` onward.

    Buckets are location-local hours, which in India start at :30 UTC — so the
    cutoff is "bucket ends after now", not the UTC hour floor.
    """
    now = now or datetime.now(timezone.utc)
    upcoming = [p for p in forecast.hourly if p.time_utc + timedelta(hours=1) > now]
    return upcoming[:limit]


def build(selection: Selection, *, mode: str, forecast_days: int, hourly_hours: int,
          alerts: Optional[dict] = None, language: str = "en", now: Optional[datetime] = None) -> dict[str, Any]:
    fc = selection.forecast
    assert fc is not None
    now = now or datetime.now(timezone.utc)
    prov = fc.provenance
    cur = fc.current
    today = fc.daily[0] if fc.daily else None
    hours = upcoming_hours(fc, hourly_hours, now)
    daily = []
    for d in fc.daily[:forecast_days]:
        row = d.to_dict()
        row["rain_mm"] = d.precipitation_mm            # legacy alias
        row["field_sources"] = daily_primary(d, prov.source)
        daily.append(row)
    aq = fc.air_quality or {}
    fallback = selection.fallback_reasons
    degraded = selection.degraded

    # Code and condition always come from the same record, so the sky never
    # disagrees with its label.
    if cur is not None and (cur.condition is not None or cur.weather_code is not None):
        condition, weather_code = cur.condition, cur.weather_code
    elif today is not None:
        condition, weather_code = today.condition, today.weather_code
    else:
        condition, weather_code = None, None

    rain_probability = cur.precipitation_probability if cur and cur.precipitation_probability is not None else (
        today.rain_probability if today else None)
    if rain_probability is None and hours:
        rain_probability = hours[0].precipitation_probability

    provenance = {
        **prov.to_dict(),
        "requested_source": selection.requested_source,
        "selected_source": selection.selected_source,
        "selection_policy_version": SELECTION_POLICY_VERSION,
        "fallback_reasons": fallback,
        "tried_providers": selection.tried_providers,
        "is_stale": selection.is_stale,
        "degraded": degraded,
        "latency_ms": selection.latency_ms,
        "timezone": fc.location.get("timezone"),
        "current_kind": fc.current_kind,
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "ok",
        "mode": mode,
        "language": language,
        "lat": fc.location.get("lat"),
        "lon": fc.location.get("lon"),
        "location": fc.location,
        "timezone": fc.location.get("timezone"),
        "requested_source": selection.requested_source,
        "selected_source": selection.selected_source,
        "source": selection.selected_source,
        "model": prov.model,
        "run_id": prov.run_id,
        # --- nested (v2) -------------------------------------------------
        "current": current_row(fc),
        "hourly": [hour_row(p) for p in hours],
        "hourly_available": len(fc.hourly),
        "daily": daily,
        "forecast": daily,
        "air_quality": fc.air_quality,
        # --- flat (legacy /weather) ---------------------------------------
        "temperature_c": cur.temperature_c if cur else None,
        "feels_like_c": cur.feels_like_c if cur else None,
        "condition": condition,
        "weather_code": weather_code,
        "high_c": today.high_c if today else None,
        "low_c": today.low_c if today else None,
        "rain_probability": rain_probability,
        "wind_kmh": cur.wind_speed_kmh if cur else None,
        "wind_direction": cur.wind_direction_deg if cur else None,
        "humidity": cur.humidity_percent if cur else None,
        "pressure_hpa": cur.pressure_hpa if cur else None,
        "precipitation_mm": cur.precipitation_mm if cur else None,
        "cloud_cover": cur.cloud_cover_percent if cur else None,
        "uv_index": (cur.uv_index if cur and cur.uv_index is not None else (today.uv_index_max if today else None)),
        "sunrise": today.sunrise if today else None,
        "sunset": today.sunset if today else None,
        "aqi": aq.get("european_aqi") if aq else None,
        "us_aqi": aq.get("us_aqi") if aq else None,
        "pm2_5": aq.get("pm2_5") if aq else None,
        # --- IMD extras ------------------------------------------------------
        "observed": fc.location.get("observed"),
        "alerts": (alerts or {}).get("alerts", []) if alerts is not None else [],
        "alerts_status": (alerts or {}).get("status", "not_requested") if alerts is not None else "not_requested",
        "alerts_summary": {k: alerts.get(k) for k in ("highest_severity", "count", "district", "note")} if alerts else None,
        # --- summaries -------------------------------------------------------
        "temperature_spread": temperature_spread(fc, now),
        "precip_next_24h": precip_next_24h(fc, now),
        # --- provenance ------------------------------------------------------
        "field_sources": fc.field_sources,
        "degraded": degraded,
        "is_stale": selection.is_stale,
        "provenance": provenance,
        "fallback_reasons": fallback,
        "tried_providers": selection.tried_providers,
        "selection_policy_version": SELECTION_POLICY_VERSION,
        "providers_used": sorted({prov.source} | {v for k, v in fc.field_sources.items()
                                                    if isinstance(v, str) and not k.startswith("_")}),
        "fetched_at": now.isoformat(),
    }


def unavailable(selection: Selection, *, mode: str, lat: float, lon: float) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "unavailable",
        "mode": mode,
        "lat": lat,
        "lon": lon,
        "requested_source": selection.requested_source,
        "selected_source": "unavailable",
        "error": selection.error,
        "fallback_reasons": selection.fallback_reasons,
        "tried_providers": selection.tried_providers,
        "selection_policy_version": SELECTION_POLICY_VERSION,
        "degraded": True,
        "provenance": {"requested_source": selection.requested_source, "selected_source": "unavailable",
                       "fallback_reasons": selection.fallback_reasons, "tried_providers": selection.tried_providers},
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
