"""Weather endpoints used by every client.

GET /v2/weather          nested + flat snapshot; unavailable -> 200 {status: "unavailable"}
GET /weather             same payload (legacy defaults); unavailable -> 502 {detail: {...}}
GET /v2/weather/health   provider chain health (configuration + circuit state, no secrets)
GET /v2/weather/catalog  what each provider supplies
GET /v2/weather/series   one variable as a time series (WeatherNext statistics or hourly values)
GET /v2/alerts           official warnings for a point (IMD + NDMA SACHET)
"""

from __future__ import annotations

import concurrent.futures
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

from weathergpt.alerts.service import get_alerts
from weathergpt.api.common import resolve_mode, resolve_model, resolve_source
from weathergpt.config import settings
from weathergpt.imd import client as imd_client
from weathergpt.runtime import cache_stats
from weathergpt.weather import payloads
from weathergpt.weather.models import SELECTION_POLICY_VERSION
from weathergpt.weather.service import service
from weathergpt.weather.supplement import supplement as run_supplement
from weathergpt.weathernext import auth as wn_auth
from weathergpt.weathernext import bigquery as wn_bigquery

router = APIRouter(tags=["weather"])
_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=8, thread_name_prefix="weather")


def snapshot(lat: float, lon: float, *, mode: str, source: str, forecast_days: int, hourly_hours: int,
             supplement: bool, alerts: bool, model: Optional[str], run_id: Optional[str], language: str) -> dict:
    alerts_future = _POOL.submit(get_alerts, lat, lon, timeout=6.0) if alerts else None
    sel = service().select(lat, lon, requested_source=source, forecast_days=forecast_days, model=model, run_id=run_id)
    if sel.forecast is None:
        return payloads.unavailable(sel, mode=mode, lat=lat, lon=lon)
    if supplement:
        run_supplement(sel.forecast, lat, lon, forecast_days)
    else:
        sel.forecast.field_sources = {}
    alert_block = None
    if alerts_future is not None:
        try:
            alert_block = alerts_future.result(timeout=7.0)
        except Exception:
            alert_block = {"status": "unknown", "alerts": [], "note": "warning lookup timed out"}
    return payloads.build(sel, mode=mode, forecast_days=forecast_days, hourly_hours=hourly_hours,
                          alerts=alert_block, language=language)


@router.get("/v2/weather")
@router.get("/v2/weather/", include_in_schema=False)
async def weather_v2(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    mode: Optional[str] = Query(None, description="everyone|farmer|researcher"),
    requested_source: Optional[str] = Query(None, description="auto|imd|weathernext|open_meteo"),
    source: Optional[str] = Query(None, description="Legacy alias of requested_source"),
    model: Optional[str] = Query(None, description="weathernext_3|weathernext_2 (WeatherNext only)"),
    run_id: Optional[str] = Query(None, description="Pin a WeatherNext run, e.g. weathernext_3_0_0_2026092800"),
    forecast_days: int = Query(7, ge=1, le=15),
    hourly_hours: int = Query(48, ge=1, le=168),
    supplement: bool = Query(True, description="Fill null fields from Open-Meteo, attributed per field"),
    alerts: bool = Query(True, description="Include official warnings (IMD + NDMA SACHET)"),
    language: str = Query("en"),
) -> dict[str, Any]:
    m = resolve_mode(mode)
    src = resolve_source(requested_source, source)
    wn_model = resolve_model(model) if model else None
    return await run_in_threadpool(snapshot, lat, lon, mode=m, source=src, forecast_days=forecast_days,
                                   hourly_hours=hourly_hours, supplement=supplement, alerts=alerts,
                                   model=wn_model, run_id=run_id, language=language)


@router.get("/weather")
@router.get("/weather/", include_in_schema=False)
async def weather_legacy(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    mode: Optional[str] = Query(None),
    requested_source: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    forecast_days: int = Query(7, ge=1, le=15),
    hourly_hours: int = Query(24, ge=1, le=168),
    alerts: bool = Query(True),
    language: str = Query("en"),
) -> dict[str, Any]:
    m = resolve_mode(mode)
    src = resolve_source(requested_source, source)
    body = await run_in_threadpool(snapshot, lat, lon, mode=m, source=src, forecast_days=forecast_days,
                                   hourly_hours=hourly_hours, supplement=True, alerts=alerts, model=None,
                                   run_id=None, language=language)
    if body.get("status") == "unavailable":
        raise HTTPException(status_code=502, detail=body)
    return body


@router.get("/v2/alerts")
async def alerts_endpoint(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180)) -> dict:
    return await run_in_threadpool(get_alerts, lat, lon)


@router.get("/v2/weather/health")
async def weather_health() -> dict[str, Any]:
    cfg = settings()
    return {
        "status": "ok",
        "check": "configuration_only",
        "selection_policy_version": SELECTION_POLICY_VERSION,
        "provider_priority": list(cfg.provider_priority),
        "provider_health": service().health(),
        "imd": imd_client.status(),
        "weathernext": {**wn_auth.status(), "bigquery": wn_bigquery.adapter().stats() if cfg.weathernext.enabled else None},
        "supplement_enabled": cfg.supplement_enabled,
        "alerts_enabled": cfg.alerts_enabled,
        "caches": cache_stats(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/v2/weather/catalog")
async def weather_catalog() -> dict[str, Any]:
    return {
        "schema_version": "3.0.0",
        "providers": [
            {"id": "imd", "name": "India Meteorological Department", "coverage": "India",
             "products": ["station observation (current)", "7-day city forecast (max/min/text)",
                          "district warnings & nowcast", "all IMD gateway products via /v2/imd/{endpoint}"],
             "hourly": False, "ensemble": False, "requires": ["IMD_API_KEY", "IMD_JWT_TOKEN", "whitelisted egress IP"]},
            {"id": "weathernext", "name": "Google DeepMind WeatherNext", "coverage": "global",
             "products": ["hourly ensemble statistics (mean, p10–p90)", "15-day horizon"],
             "hourly": True, "ensemble": True, "models": ["weathernext_3", "weathernext_2"],
             "requires": ["WEATHERNEXT_ENABLED=1", "GOOGLE_CLOUD_PROJECT", "WEATHERNEXT_TABLE_3", "Google credentials"]},
            {"id": "open_meteo", "name": "Open-Meteo", "coverage": "global",
             "products": ["current", "hourly", "16-day daily", "air quality", "UV", "sunrise/sunset", "ERA5 archive"],
             "hourly": True, "ensemble": False, "requires": []},
        ],
        "series_variables": ["temperature_2m", "total_precipitation_1hr", "wind_speed_10m", "dewpoint_temperature_2m",
                             "total_cloud_cover", "mean_sea_level_pressure"],
    }


_HOURLY_FIELD = {"temperature_2m": "temperature_c", "total_precipitation_1hr": "precipitation_mm",
                 "wind_speed_10m": "wind_speed_kmh", "total_cloud_cover": "cloud_cover_percent",
                 "mean_sea_level_pressure": "pressure_hpa", "relative_humidity_2m": "humidity_percent"}


@router.get("/v2/weather/series")
async def weather_series(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    variable: str = Query("temperature_2m"),
    statistic: str = Query("mean", description="mean|p10|p25|p50|p75|p90 (ensemble sources)"),
    requested_source: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    run_id: Optional[str] = Query(None),
    forecast_days: int = Query(7, ge=1, le=15),
) -> dict[str, Any]:
    src = resolve_source(requested_source)
    if statistic not in ("mean", "p10", "p25", "p50", "p75", "p90"):
        raise HTTPException(status_code=400, detail="statistic must be mean|p10|p25|p50|p75|p90")
    wn_model = resolve_model(model) if model else None

    def work() -> dict:
        sel = service().select(lat, lon, requested_source=src, forecast_days=forecast_days, model=wn_model, run_id=run_id)
        fc = sel.forecast
        if fc is None:
            return {"status": "unavailable", "variable": variable, "error": sel.error, "fallback_reasons": sel.fallback_reasons}
        series = ((fc.ensemble or {}).get("series") or {}).get(variable)
        if series:
            values = [{"time_utc": v["time_utc"], "value": v.get(statistic), **{k: x for k, x in v.items() if k != "time_utc"}}
                      for v in series["values"]]
            status = "ok" if statistic in series["statistics"] else "statistic_unavailable"
            units, stats = series["units"], series["statistics"]
        elif variable in _HOURLY_FIELD and statistic == "mean":
            key = _HOURLY_FIELD[variable]
            values = [{"time_utc": p.time_utc.isoformat(), "value": getattr(p, key)} for p in fc.hourly]
            status, stats = "ok", ["deterministic"]
            units = {"temperature_c": "C", "precipitation_mm": "mm", "wind_speed_kmh": "km/h",
                     "cloud_cover_percent": "%", "pressure_hpa": "hPa", "humidity_percent": "%"}[key]
        else:
            return {"status": "variable_unavailable", "variable": variable, "source": sel.selected_source,
                    "available": sorted(((fc.ensemble or {}).get("series") or {}).keys()) or sorted(_HOURLY_FIELD)}
        return {"schema_version": "3.0.0", "status": status, "variable": variable, "statistic": statistic,
                "available_statistics": stats, "units": units, "source": sel.selected_source,
                "run_id": fc.provenance.run_id, "members": (fc.ensemble or {}).get("members"),
                "values": values[:360], "provenance": fc.provenance.to_dict(), "fallback_reasons": sel.fallback_reasons}

    return await run_in_threadpool(work)


