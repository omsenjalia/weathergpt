"""Proposed new routes for WeatherNext integration.

Routes are conditional on permission. First run privately.

- GET /v2/weather - compact current/forecast overview and bounded hourly/daily
- GET /v2/weather/catalog - complete entitlement-filtered capability metadata
- GET /v2/weather/series - selected variables, point, run, valid-time window, statistic
- GET /v2/weather/profile - one location/valid time, selected upper-air fields/levels
- GET /v2/weather/ensemble - selected member series for bounded scientific requests
- GET /v2/weather/tiles/... - run-keyed authorized map tiles
- GET /v2/weather/cyclones - granted cyclone tracks
- POST /v2/weather/jobs and scoped job status/cancel/result

Every result carries schema_version, model, run_id, init_time, etc., plus
mode, capability/product ID, requested/selected source, provenance.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Query, HTTPException, Depends
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response

from services.forecast import get_forecast_service
from services.forecast_models import ProviderName, SELECTION_POLICY_VERSION
from services.forecast_aggregation import build_precip_next_24h, build_temperature_spread
from services.weathernext_catalog import get_catalog, surface_access_manifest
from services.config import get_config
from services.forecast_cache import get_cache

router = APIRouter(prefix="/v2/weather", tags=["weather-v2"])

ALLOWED_SOURCES = {"auto", "imd", "weathernext", "accuweather", "open_meteo", "open-meteo", "openmeteo"}


def _validate_mode(mode: str) -> str:
    if mode not in ("everyone", "farmer", "researcher"):
        raise HTTPException(status_code=400, detail="mode must be everyone|farmer|researcher")
    return mode


def _resolve_source(requested_source: str, source: str) -> str:
    """``requested_source`` (Flutter / chat contract) wins over legacy ``source``."""
    chosen = (requested_source or source or "auto").strip().lower()
    if chosen not in ALLOWED_SOURCES:
        raise HTTPException(status_code=400, detail="requested_source must be auto|imd|weathernext|accuweather|open_meteo")
    return "open_meteo" if chosen in ("open-meteo", "openmeteo") else chosen


@router.get("")
@router.get("/")
async def get_weather_v2(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    mode: str = Query("everyone", description="everyone|farmer|researcher"),
    requested_source: str = Query("", description="auto|imd|weathernext|accuweather|open_meteo (preferred name)"),
    source: str = Query("auto", description="Legacy alias for requested_source"),
    model: str = Query("weathernext_3", description="weathernext_3|weathernext_2 when requested_source=weathernext"),
    run_id: str = Query("", description="Pin a WeatherNext run, e.g. weathernext_3_0_0_2026091900"),
    forecast_days: int = Query(3, ge=1, le=15),
    language: str = Query("en"),
) -> dict[str, Any]:
    """Compact current/forecast overview with provenance.

    Uses IMD -> WeatherNext -> AccuWeather -> Open-Meteo selection for auto.
    Explicit source pins bypass automatic substitution and never substitute
    another provider: a pinned source either returns its data or an explicit
    ``status: unavailable`` with ``fallback_reasons``.
    """
    mode = _validate_mode(mode)
    effective_source = _resolve_source(requested_source, source)
    normalized_model = (model or "weathernext_3").strip().lower().replace("-", "_")
    if normalized_model not in {"weathernext_2", "weathernext_3", "wn2", "wn3", "2", "3"}:
        raise HTTPException(status_code=400, detail="model must be weathernext_2 or weathernext_3")
    if effective_source != "weathernext":
        normalized_model = "weathernext_3"

    def _fetch():
        service = get_forecast_service()
        result = service.select_forecast(
            lat=lat,
            lon=lon,
            product="forecast",
            requested_source=effective_source,
            mode=mode,
            forecast_days=forecast_days,
            run_id=run_id or None,
            model=normalized_model,
        )

        if not result.forecast:
            # Return structured unavailable, not fabricated values
            return {
                "schema_version": "2.0.0",
                "status": "unavailable",
                "mode": mode,
                "requested_source": effective_source,
                "model": normalized_model,
                "selected_source": "unavailable",
                "selection_policy_version": SELECTION_POLICY_VERSION,
                "error": result.error,
                "fallback_reasons": result.fallback_reasons,
                "tried_providers": result.tried_providers,
                "provenance": {
                    "requested_source": effective_source,
                    "model": normalized_model,
                    "selected_source": "unavailable",
                    "fallback_reasons": result.fallback_reasons,
                    "tried_providers": result.tried_providers,
                },
                "lat": lat,
                "lon": lon,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }

        forecast = result.forecast
        now = datetime.now(timezone.utc)
        # Build response with required fields
        return {
            "schema_version": forecast.schema_version,
            "status": "ok",
            "mode": mode,
            "model": forecast.provenance.model,
            "location": forecast.location,
            "current": forecast.current.to_dict() if forecast.current else None,
            "hourly": [p.to_dict() for p in forecast.hourly[:24]],
            "daily": forecast.daily,
            # Everyone-card summaries (null when the provider cannot support them honestly)
            "temperature_spread": build_temperature_spread(forecast, now),
            "precip_next_24h": build_precip_next_24h(forecast, now),
            "provenance": {
                **forecast.provenance.to_dict(),
                "requested_source": result.requested_source,
                "selected_source": result.selected_source.value,
                "selection_policy_version": SELECTION_POLICY_VERSION,
                "fallback_reasons": result.fallback_reasons,
                "tried_providers": result.tried_providers,
                "is_stale": result.is_stale,
                "latency_ms": result.latency_ms,
            },
            "source": result.selected_source.value,
            "providers_used": forecast.provenance.sources,
            "air_quality": forecast.air_quality,
            "alerts": forecast.alerts,
            "fetched_at": now.isoformat(),
        }

    return await run_in_threadpool(_fetch)


@router.get("/catalog")
async def get_catalog_endpoint(
    surface: str = Query("", description="Filter by surface: bigquery|gcs_ensemble|gcs_statistics|earth_engine|weather_lab"),
    state: str = Query("", description="Filter by state"),
    product: str = Query("", description="Filter by product"),
) -> dict[str, Any]:
    """Complete entitlement-filtered capability/variable metadata."""
    catalog = get_catalog()
    records = catalog.all()

    if surface:
        records = [r for r in records if r.surface == surface]
    if state:
        records = [r for r in records if r.access_status.value == state]
    if product:
        records = [r for r in records if product.lower() in r.product.lower() or product.lower() in r.capability_id.lower()]

    # Entitlement filtering: for now, show all but mark not_granted
    # In production, filter based on user auth and grant
    return {
        "schema_version": "2.0.0",
        "total": len(records),
        "filtered": len(records),
        "coverage": catalog.coverage_report(),
        "surface_access": surface_access_manifest(),
        "capabilities": [
            {
                "capability_id": r.capability_id,
                "product": r.product,
                "model_version": r.model_version,
                "surface": r.surface,
                "operation": r.operation,
                "resource_identifier": r.resource_identifier,
                "schema": r.schema,
                "temporal_coverage": r.temporal_coverage,
                "spatial_coverage": r.spatial_coverage,
                "access_status": r.access_status.value,
                "license": r.license,
                "distribution_rules": r.distribution_rules,
                "provider_adapter": r.provider_adapter,
                "backend_route": r.backend_route,
                "ui_entry_point": r.ui_entry_point,
                "langgraph_tool": r.langgraph_tool,
                "blocker": r.blocker,
            }
            for r in records
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _parse_iso(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@router.get("/series")
async def get_series(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    variable: str = Query(..., description="Variable ID, e.g., temperature_2m"),
    run_id: str = Query("", description="Exact run ID, e.g., weathernext_3_0_0_2026091900"),
    statistic: str = Query("mean", description="mean|p10|p25|p50|p75|p90"),
    start_time: str = Query("", description="Valid time start ISO"),
    end_time: str = Query("", description="Valid time end ISO"),
    forecast_days: int = Query(7, ge=1, le=15),
    model: str = Query("weathernext_3", description="weathernext_2|weathernext_3"),
    mode: str = Query("researcher"),
    requested_source: str = Query("weathernext", description="Series is a WeatherNext product; other values are rejected"),
) -> dict[str, Any]:
    """Selected variable, point, run, valid-time window, statistic; strict limits.

    Values come from the precomputed ensemble statistics of one run. ``points``
    keeps the legacy hourly shape; ``values`` carries the requested statistic
    plus every statistic available for the variable.
    """
    mode = _validate_mode(mode)
    if mode != "researcher":
        # Series is primarily researcher, but allow farmer/everyone with limited vars
        if variable not in ("temperature_2m", "total_precipitation_1hr"):
            raise HTTPException(status_code=403, detail="Variable requires researcher mode")
    if requested_source and requested_source.lower() != "weathernext":
        raise HTTPException(status_code=400, detail="series is only served from weathernext")
    normalized_model = (model or "weathernext_3").lower().replace("-", "_")
    if normalized_model not in {"weathernext_2", "weathernext_3", "wn2", "wn3", "2", "3"}:
        raise HTTPException(status_code=400, detail="model must be weathernext_2 or weathernext_3")
    if statistic not in ("mean", "p10", "p25", "p50", "p75", "p90"):
        raise HTTPException(status_code=400, detail="statistic must be mean|p10|p25|p50|p75|p90")

    # Validate variable exists
    catalog = get_catalog()
    matching = [r for r in catalog.all() if variable in r.capability_id]
    if not matching:
        raise HTTPException(status_code=404, detail=f"Variable {variable} not found in catalog")

    # Check cost bounds
    cfg = get_config().weathernext
    if not cfg.enabled:
        return {
            "status": "not_granted",
            "message": "WeatherNext disabled",
            "variable": variable,
        }

    start_dt = _parse_iso(start_time)
    end_dt = _parse_iso(end_time)

    def _fetch():
        service = get_forecast_service()
        result = service.select_forecast(
            lat=lat,
            lon=lon,
            product="forecast",
            requested_source="weathernext",
            mode=mode,
            forecast_days=forecast_days,
            run_id=run_id or None,
            model=normalized_model,
        )
        if not result.forecast:
            return {
                "status": "unavailable",
                "variable": variable,
                "error": result.error,
                "fallback_reasons": result.fallback_reasons,
            }

        forecast = result.forecast
        ensemble = forecast.ensemble or {}
        series = (ensemble.get("series") or {}).get(variable)

        def _in_window(t: datetime) -> bool:
            if start_dt and t < start_dt:
                return False
            if end_dt and t > end_dt:
                return False
            return True

        # Legacy hourly shape (bounded to 168 points = 7 days hourly)
        hourly = [p for p in forecast.hourly if _in_window(p.time_utc)][:168]

        values: list[dict] = []
        available_statistics: list[str] = []
        units = {"temperature_2m": "C", "total_precipitation_1hr": "mm"}.get(variable, "unknown")
        if series:
            units = series.get("units", units)
            available_statistics = list(series.get("statistics") or [])
            for entry in series.get("values") or []:
                t = _parse_iso(str(entry.get("time_utc")))
                if t is None or not _in_window(t):
                    continue
                values.append({"time_utc": entry.get("time_utc"), "value": entry.get(statistic), **{k: v for k, v in entry.items() if k != "time_utc"}})
            values = values[:168]

        status = "ok"
        if series and statistic not in available_statistics:
            status = "statistic_unavailable"
        elif not series:
            status = "variable_not_in_column_profile"

        return {
            "schema_version": "2.0.0",
            "status": status,
            "variable": variable,
            "statistic": statistic,
            "available_statistics": available_statistics,
            "units": units,
            "run_id": forecast.provenance.run_id,
            "init_time_utc": forecast.provenance.init_time_utc.isoformat() if forecast.provenance.init_time_utc else None,
            "members": ensemble.get("members"),
            "values": values,
            "points": [p.to_dict() for p in hourly],
            "provenance": {
                **forecast.provenance.to_dict(),
                "requested_source": result.requested_source,
                "selected_source": result.selected_source.value,
                "fallback_reasons": result.fallback_reasons,
                "tried_providers": result.tried_providers,
            },
            "column_profile": cfg.bq.column_profile,
        }

    return await run_in_threadpool(_fetch)


@router.get("/profile")
async def get_profile(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    valid_time: str = Query(..., description="Valid time ISO"),
    variables: str = Query("temperature,u_component_of_wind,v_component_of_wind", description="Comma-separated"),
    levels: str = Query("850,500,250", description="Comma-separated hPa levels"),
    model: str = Query("weathernext_3", description="weathernext_2|weathernext_3"),
    mode: str = Query("researcher"),
) -> dict[str, Any]:
    """One location/valid time, selected upper-air fields/levels."""
    mode = _validate_mode(mode)
    if mode != "researcher":
        raise HTTPException(status_code=403, detail="Profile requires researcher mode")
    normalized_model = (model or "weathernext_3").lower().replace("-", "_")
    if normalized_model not in {"weathernext_2", "weathernext_3", "wn2", "wn3", "2", "3"}:
        raise HTTPException(status_code=400, detail="model must be weathernext_2 or weathernext_3")

    def _fetch():
        try:
            level_list = [int(x.strip()) for x in levels.split(",") if x.strip()]
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid levels")

        from services.forecast_models import PRESSURE_LEVELS
        invalid = [l for l in level_list if l not in PRESSURE_LEVELS]
        if invalid:
            raise HTTPException(status_code=400, detail=f"Unsupported levels {invalid}, allowed {PRESSURE_LEVELS}")
        var_list = [v.strip() for v in variables.split(",") if v.strip()]
        try:
            from services.weathernext_bigquery import parse_run_id
            from services.weathernext_gcs import WeatherNextGCSQueryError, get_gcs_adapter
            payload = get_gcs_adapter().query_profile(
                lat, lon, variables=var_list, levels=level_list,
                model=normalized_model, run_id=valid_time or "",
            )
            return {
                "schema_version": "2.0.0", "status": "ok",
                "location": {"lat": lat, "lon": lon}, "valid_time": valid_time,
                "variables": var_list, "levels": level_list,
                "profile": payload["profile"],
                "provenance": {
                    "surface": payload.get("surface"), "bucket": payload.get("bucket"),
                    "model_version": payload.get("model_version"), "is_ensemble": True,
                },
            }
        except WeatherNextGCSQueryError as exc:
            return {"status": "unavailable", "error": str(exc),
                    "fallback_reasons": [{"surface": "gcs_ensemble", "reason": exc.code}]}

    return await run_in_threadpool(_fetch)


@router.get("/ensemble")
async def get_ensemble(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    variable: str = Query("temperature_2m"),
    run_id: str = Query(""),
    model: str = Query("weathernext_3"),
    mode: str = Query("researcher"),
) -> dict[str, Any]:
    """Return a bounded point extract from the full GCS ensemble Zarr."""
    mode = _validate_mode(mode)
    if mode != "researcher":
        raise HTTPException(status_code=403, detail="Ensemble requires researcher mode and authorization")
    if (model or "").lower().replace("-", "_") not in {"weathernext_2", "weathernext_3", "wn2", "wn3", "2", "3"}:
        raise HTTPException(status_code=400, detail="model must be weathernext_2 or weathernext_3")

    def _fetch():
        try:
            from services.weathernext_gcs import WeatherNextGCSQueryError, get_gcs_adapter
            payload = get_gcs_adapter().query_ensemble(lat, lon, variable=variable, model=model, run_id=run_id)
            return {
                "schema_version": "2.0.0",
                "status": "ok",
                "variable": variable,
                "model": payload.get("model"),
                "model_version": payload.get("model_version"),
                "run_id": payload.get("run_id") or run_id or None,
                "members": payload.get("members", 0),
                "member_values": payload.get("member_values", []),
                "units": payload.get("units"),
                "surface": payload.get("surface"),
                "bucket": payload.get("bucket"),
                "note": "Bounded point extract; full regional export requires a confirmed job",
                "provenance": {
                    "surface": payload.get("surface"),
                    "bucket": payload.get("bucket"),
                    "model_version": payload.get("model_version"),
                    "is_ensemble": True,
                },
            }
        except WeatherNextGCSQueryError as exc:
            return {"status": "unavailable", "error": str(exc), "fallback_reasons": [{"surface": "gcs_ensemble", "reason": exc.code}]}
        except Exception as exc:
            return {"status": "unavailable", "error": type(exc).__name__, "fallback_reasons": [{"surface": "gcs_ensemble", "reason": "query_failed"}]}

    return await run_in_threadpool(_fetch)


@router.get("/tiles/{variable}/{run_id}/{z}/{x}/{y}.png")
async def get_tile(
    variable: str,
    run_id: str,
    z: int,
    x: int,
    y: int,
    model: str = Query("weathernext_3"),
    high_resolution: bool = Query(False),
    statistic: str = Query("mean"),
):
    """Proxy an authorized Earth Engine WeatherNext map tile as PNG bytes."""
    if not get_config().weathernext.enabled:
        raise HTTPException(status_code=403, detail="WeatherNext disabled")
    try:
        from services.weathernext_ee import WeatherNextEEError, get_ee_adapter
        content = await run_in_threadpool(
            lambda: get_ee_adapter().get_tile(
                variable, run_id, z, x, y, model=model,
                high_resolution=high_resolution, statistic=statistic,
            )
        )
        return Response(content=content, media_type="image/png", headers={"Cache-Control": "public, max-age=300"})
    except WeatherNextEEError as exc:
        # A map tile must not silently become a fake image.  JSON explains the
        # missing entitlement/dependency to the Explore client and operator.
        raise HTTPException(status_code=503, detail={"status": "unavailable", "reason": exc.code, "message": str(exc)})


@router.get("/cyclones")
async def get_cyclones(
    storm_id: str = Query(""),
    model: str = Query("weathernext_cyclones"),
    run_id: str = Query(""),
    mode: str = Query("researcher"),
) -> dict[str, Any]:
    """Granted cyclone tracks/intensity/member/verification data."""
    mode = _validate_mode(mode)
    if mode != "researcher":
        raise HTTPException(status_code=403, detail="Cyclone data requires researcher mode")

    catalog = get_catalog()
    cap = catalog.get("weathernext_cyclones_tracks")
    if cap and cap.access_status.value != "verified":
        return {
            "status": "unverified",
            "message": "Cyclone delivery contract not verified",
            "blocker": cap.blocker,
        }

    return {
        "status": "ok",
        "storm_id": storm_id,
        "model": model,
        "run_id": run_id,
        "tracks": [],
        "note": "Requires verified cyclone adapter",
    }


# Jobs for expensive regional/member exports
_jobs: dict[str, dict] = {}


@router.post("/jobs")
async def create_job(
    variable: str = Query(...),
    region: str = Query(..., description="Bounding box or region ID"),
    time_range: str = Query(..., description="ISO start/end"),
    mode: str = Query("researcher"),
) -> dict[str, Any]:
    """Bounded extraction/export or inference jobs; estimate cost and require confirmation."""
    mode = _validate_mode(mode)
    if mode != "researcher":
        raise HTTPException(status_code=403, detail="Jobs require researcher mode")

    import uuid

    job_id = str(uuid.uuid4())[:8]
    estimated = {"bytes": 10_000_000, "compute_seconds": 60, "amount_usd": 0.05}

    _jobs[job_id] = {
        "job_id": job_id,
        "variable": variable,
        "region": region,
        "time_range": time_range,
        "status": "prepared",
        "estimated_cost": estimated,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "requires_confirmation": True,
    }

    return {
        "status": "prepared",
        "job": _jobs[job_id],
        "message": "Job prepared, confirm with POST /v2/weather/jobs/{job_id}/confirm",
    }


@router.post("/jobs/{job_id}/confirm")
async def confirm_job(job_id: str) -> dict[str, Any]:
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = _jobs[job_id]
    job["status"] = "running"
    job["started_at"] = datetime.now(timezone.utc).isoformat()
    return {"status": "running", "job": job}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str) -> dict[str, Any]:
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"status": "ok", "job": _jobs[job_id]}


@router.delete("/jobs/{job_id}")
async def cancel_job(job_id: str) -> dict[str, Any]:
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    _jobs[job_id]["status"] = "cancelled"
    _jobs[job_id]["cancelled_at"] = datetime.now(timezone.utc).isoformat()
    return {"status": "cancelled", "job": _jobs[job_id]}


@router.get("/health")
async def weather_health() -> dict[str, Any]:
    """Source health, latest complete runs, freshness/coverage, fallback reasons, cache diagnostics."""
    from services.weathernext_auth import get_credentials_factory_status

    cache = get_cache()
    service = get_forecast_service()

    # Check each provider
    provider_health = {}
    for name, provider in service.providers.items():
        eligible, reason = provider.is_eligible("forecast", 22.0, 72.0)  # sample India coords
        provider_health[name.value] = {
            "configured": provider.is_configured(),
            "eligible": eligible,
            "reason": reason,
            "consecutive_failures": provider._consecutive_failures,
            "circuit_breaker_open": provider.should_circuit_break(),
            "capability": {
                "max_days": provider.capability.max_forecast_days,
                "has_ensemble": provider.capability.has_ensemble,
                "freshness_budget_hours": provider.capability.freshness_budget_hours,
            },
        }

    weathernext_bigquery = None
    try:
        from services.weathernext_bigquery import get_bigquery_adapter
        weathernext_bigquery = get_bigquery_adapter().stats()
    except Exception as exc:  # pragma: no cover - diagnostics must never fail the endpoint
        weathernext_bigquery = {"error": type(exc).__name__}

    gcs_health = None
    ee_health = None
    try:
        from services.weathernext_gcs import get_gcs_adapter
        gcs_health = get_gcs_adapter().stats()
    except Exception as exc:
        gcs_health = {"error": type(exc).__name__}
    try:
        from services.weathernext_ee import get_ee_adapter
        ee_health = get_ee_adapter().health()
    except Exception as exc:
        ee_health = {"error": type(exc).__name__}

    return {
        "status": "ok",
        "selection_policy_version": SELECTION_POLICY_VERSION,
        "provider_priority": get_config().provider_priority,
        "provider_health": provider_health,
        "surface_access": surface_access_manifest(),
        "weathernext_auth": get_credentials_factory_status(),
        "weathernext_bigquery": weathernext_bigquery,
        "weathernext_gcs": gcs_health,
        "weathernext_earth_engine": ee_health,
        "cache": cache.stats(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
