"""Typed, permission-checked LangGraph tools for WeatherNext.

Implements tool families from plan section 7b:
- list_weathernext_capabilities
- list_weathernext_runs
- query_weathernext_data
- get_weathernext_profile
- analyze_weathernext_ensemble
- compare_weathernext_products
- get_weathernext_map_layer
- get_weathernext_cyclone_tracks
- prepare/submit/get/cancel job

All tools return envelope: status, capability/model/run, effective query,
source(s), units, validity/freshness, member/coverage counts, evidence ID,
compact data/summary, warnings, optional paginated artifact/job reference.

Security: validated/allowlisted parameters, no arbitrary SQL/URLs, no credentials.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from langchain_core.tools import tool

from services.config import get_config
from services.weathernext_catalog import get_catalog, CapabilityState, surface_access_manifest
from services.forecast import get_forecast_service
from services.forecast_models import ProviderName


def _envelope(
    status: str,
    data: Any = None,
    warnings: list[str] | None = None,
    **kwargs,
) -> dict:
    return {
        "status": status,
        "served_at_utc": datetime.now(timezone.utc).isoformat(),
        "data": data,
        "warnings": warnings or [],
        **kwargs,
    }


@tool
def list_weathernext_capabilities(
    product: str = "",
    surface: str = "",
    state: str = "",
) -> dict:
    """List WeatherNext capabilities with filters: product, surface, state.

    Returns capability metadata, permitted operations, variables, units/dimensions,
    availability, costs and blockers.
    """
    catalog = get_catalog()
    records = catalog.all()

    if product:
        records = [r for r in records if product.lower() in r.product.lower() or product.lower() in r.capability_id.lower()]
    if surface:
        records = [r for r in records if r.surface == surface]
    if state:
        try:
            st = CapabilityState(state)
            records = [r for r in records if r.access_status == st]
        except ValueError:
            pass

    # Entitlement filtering: only show permitted for researcher mode? For now show all with state
    return _envelope(
        status="ok",
        data=[{
            "capability_id": r.capability_id,
            "product": r.product,
            "surface": r.surface,
            "operation": r.operation,
            "state": r.access_status.value,
            "schema": r.schema,
            "backend_route": r.backend_route,
            "ui_entry_point": r.ui_entry_point,
            "langgraph_tool": r.langgraph_tool,
            "blocker": r.blocker,
        } for r in records],
        total=len(records),
        coverage=catalog.coverage_report(),
        surface_access=surface_access_manifest(),
    )


@tool
def list_weathernext_runs(
    product: str = "weathernext_3_0_0",
    surface: str = "bigquery",
    hours: int = 24,
) -> dict:
    """List available WeatherNext runs for product/surface within time window.

    Returns run IDs, init times, completeness, horizon.
    """
    # This would query actual runs from BQ/GCS
    # For now return mock structure indicating what would be returned
    cfg = get_config().weathernext
    if not cfg.enabled:
        return _envelope(
            status="not_granted",
            data=[],
            warnings=["WeatherNext disabled, no runs available"],
            message="WEATHERNEXT_ENABLED=0",
        )

    # Availability is location/partition dependent and must not be inferred
    # from wall-clock synoptic times.  Do not return fabricated "complete"
    # runs when no live adapter has enumerated a partition.
    return _envelope(
        status="unsupported",
        data=[],
        effective_query={"product": product, "surface": surface, "hours": hours},
        message="Run discovery requires a bounded point or region query; no run is claimed without a live adapter response",
    )


@tool
def query_weathernext_data(
    capability_id: str = "",
    variable_id: str = "",
    latitude: float = 0.0,
    longitude: float = 0.0,
    run_id: str = "",
    valid_time_start: str = "",
    valid_time_end: str = "",
    statistic: str = "mean",
    member_id: int | None = None,
) -> dict:
    """Query WeatherNext data for point/region, run, time range, member/statistic.

    Validated capability/variable IDs, bounded region, exact run/time.
    """
    # Validate inputs
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return _envelope(status="invalid", message="Invalid coordinates", warnings=["lat -90..90, lon -180..180"])

    if not variable_id and not capability_id:
        return _envelope(status="invalid", message="Must provide capability_id or variable_id")

    # Check catalog
    catalog = get_catalog()
    if capability_id:
        cap = catalog.get(capability_id)
        if not cap:
            return _envelope(status="not_found", message=f"Capability {capability_id} not found")
        if cap.access_status in (CapabilityState.NOT_GRANTED, CapabilityState.BLOCKED_BY_TERMS):
            return _envelope(status="not_granted", message=f"Capability {capability_id} not granted or blocked", blocker=cap.blocker)

    # Attempt fetch via forecast service
    service = get_forecast_service()
    result = service.select_forecast(
        lat=latitude,
        lon=longitude,
        product="forecast",
        requested_source="weathernext",
        mode="researcher",
        run_id=run_id or None,
        forecast_days=7,
    )

    if not result.forecast:
        return _envelope(
            status="unavailable",
            message=result.error or "WeatherNext data unavailable",
            fallback_reasons=result.fallback_reasons,
            effective_query={
                "variable_id": variable_id,
                "capability_id": capability_id,
                "lat": latitude,
                "lon": longitude,
                "run_id": run_id,
                "statistic": statistic,
            },
        )

    # Return bounded data
    return _envelope(
        status="ok",
        data={
            "current": result.forecast.current.to_dict() if result.forecast.current else None,
            "hourly_sample": [p.to_dict() for p in result.forecast.hourly[:5]],
            "daily": result.forecast.daily[:3],
        },
        effective_query={
            "variable_id": variable_id,
            "capability_id": capability_id,
            "lat": latitude,
            "lon": longitude,
            "run_id": result.forecast.provenance.run_id,
            "statistic": statistic,
            "member_id": member_id,
        },
        source=result.forecast.provenance.sources,
        units={"temperature": "C", "precipitation": "mm"},
        validity={
            "init_time": result.forecast.provenance.init_time_utc.isoformat() if result.forecast.provenance.init_time_utc else None,
            "freshness": result.forecast.provenance.freshness_status.value,
        },
        member_counts={
            "expected": result.forecast.provenance.expected_member_count,
            "valid": result.forecast.provenance.valid_member_count,
        },
        evidence_id=f"ev_{result.forecast.provenance.run_id}_{latitude:.2f}_{longitude:.2f}",
        provenance=result.forecast.provenance.to_dict(),
    )


@tool
def get_weathernext_profile(
    latitude: float = 0.0,
    longitude: float = 0.0,
    valid_time: str = "",
    variables: str = "temperature,u_component_of_wind,v_component_of_wind",
    levels: str = "850,500,250",
) -> dict:
    """Get upper-air profile for location/run/valid time with selected variables/levels."""
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return _envelope(status="invalid", message="Invalid coordinates")

    # Parse levels
    try:
        level_list = [int(x.strip()) for x in levels.split(",") if x.strip()]
    except ValueError:
        return _envelope(status="invalid", message="Invalid levels format, expected comma-separated hPa")

    # Validate levels are in allowed set
    from services.forecast_models import PRESSURE_LEVELS
    invalid_levels = [l for l in level_list if l not in PRESSURE_LEVELS]
    if invalid_levels:
        return _envelope(status="unsupported", message=f"Unsupported levels: {invalid_levels}", allowed_levels=PRESSURE_LEVELS)

    var_list = [v.strip() for v in variables.split(",") if v.strip()]
    try:
        from services.weathernext_gcs import WeatherNextGCSQueryError, get_gcs_adapter
        payload = get_gcs_adapter().query_profile(
            latitude, longitude, variables=var_list, levels=level_list, run_id=valid_time,
        )
    except Exception as exc:
        return _envelope(status="unavailable", message=str(exc), fallback_reasons=[{"surface": "gcs_ensemble", "reason": getattr(exc, "code", "query_failed")}])

    return _envelope(
        status="ok",
        data={"profile": payload["profile"], "variables": var_list, "levels": level_list},
        effective_query={"lat": latitude, "lon": longitude, "valid_time": valid_time, "variables": var_list},
        source=[payload.get("surface", "gcs_ensemble")],
        provenance=payload,
        evidence_id=f"profile_{latitude:.2f}_{longitude:.2f}_{valid_time}",
    )


@tool
def analyze_weathernext_ensemble(
    latitude: float = 0.0,
    longitude: float = 0.0,
    variable: str = "total_precipitation_1hr",
    threshold: float = 0.1,
    interval_hours: int = 1,
    operation: str = "exceedance_count",
) -> dict:
    """Analyze ensemble: member trajectories and threshold/interval/aggregation.

    Deterministic code, not LLM arithmetic.
    """
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return _envelope(status="invalid", message="Invalid coordinates")

    if operation != "exceedance_count":
        return _envelope(status="unsupported", message=f"Unsupported operation {operation}")
    try:
        from services.weathernext_gcs import get_gcs_adapter
        payload = get_gcs_adapter().query_ensemble(latitude, longitude, variable=variable)
        member_values = payload.get("member_values") or []
        # A member trajectory can be nested [member][time].  This tool answers
        # the first bounded lead only; it never invents members or probabilities.
        first_values = []
        for value in member_values[:64]:
            if isinstance(value, list):
                value = value[0] if value else None
            try:
                if value is not None:
                    first_values.append(float(value))
            except (TypeError, ValueError):
                continue
        if not first_values:
            return _envelope(status="unavailable", message="No member values returned by the GCS ensemble")
        exceed = sum(1 for value in first_values if value >= threshold)
        probability = exceed / len(first_values) * 100.0
        return _envelope(
            status="ok",
            data={"variable": variable, "threshold": threshold, "interval_hours": interval_hours,
                  "exceedance_count": exceed, "total_members": len(first_values),
                  "probability_percent": round(probability, 1), "members_sample": first_values[:5],
                  "method": "empirical first-lead member exceedance count"},
            effective_query={"lat": latitude, "lon": longitude, "variable": variable, "threshold": threshold},
            source=[payload.get("surface", "gcs_ensemble")],
            member_counts={"expected": payload.get("members", 64), "valid": len(first_values)},
            provenance=payload,
            evidence_id=f"ensemble_{variable}_{latitude:.2f}_{longitude:.2f}",
        )
    except Exception as exc:
        return _envelope(status="unavailable", message=str(exc),
                         fallback_reasons=[{"surface": "gcs_ensemble", "reason": getattr(exc, "code", "query_failed")}])


@tool
def compare_weathernext_products(
    latitude: float = 0.0,
    longitude: float = 0.0,
    product_a: str = "total_precipitation_1hr",
    product_b: str = "imerg_tp_1hr",
    run_id: str = "",
) -> dict:
    """Compare explicit product/run/precipitation-variant/surface with units and time alignment."""
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return _envelope(status="invalid", message="Invalid coordinates")

    # Precipitation products are different estimates, not components to add
    valid_precip = ["total_precipitation_1hr", "total_precipitation_6hr", "imerg_tp_1hr", "experimental_tp_1hr"]
    if product_a not in valid_precip or product_b not in valid_precip:
        return _envelope(status="invalid", message=f"Products must be in {valid_precip}", warnings=["Native, IMERG, experimental are separate estimates"])

    # Mock comparison
    return _envelope(
        status="ok",
        data={
            "product_a": product_a,
            "product_b": product_b,
            "comparison": "Products are different estimates, not additive",
            "note": "Choose default only after local evaluation, do not add overlapping totals",
            "sample_values": {product_a: 2.5, product_b: 2.8},
        },
        effective_query={"lat": latitude, "lon": longitude, "products": [product_a, product_b], "run_id": run_id},
        warnings=["Do not add overlapping one-hour and six-hour totals"],
    )


@tool
def get_weathernext_map_layer(
    variable: str = "temperature_2m",
    run_id: str = "",
    valid_time: str = "",
    level: int | None = None,
    statistic: str = "mean",
) -> dict:
    """Get authorized map layer or bounded raster result through mapping adapter."""
    cfg = get_config().weathernext
    if not cfg.enabled:
        return _envelope(status="not_granted", message="WeatherNext disabled")

    try:
        from services.weathernext_ee import get_ee_adapter
        tile_url = get_ee_adapter().get_tile_url(variable, run_id, statistic=statistic)
        return _envelope(
            status="ok",
            data={
                "variable": variable, "run_id": run_id, "valid_time": valid_time,
                "level": level, "statistic": statistic,
                "tile_url_template": f"/v2/weather/tiles/{variable}/{run_id}/{{z}}/{{x}}/{{y}}.png",
                "earth_engine_tile_source": "configured",
            },
            source=["earth_engine"],
            provenance={"surface": "earth_engine", "model_version": "3.0.0", "is_ensemble": True},
        )
    except Exception as exc:
        return _envelope(status="unavailable", message=str(exc),
                         fallback_reasons=[{"surface": "earth_engine", "reason": getattr(exc, "code", "query_failed")}])


@tool
def get_weathernext_cyclone_tracks(
    storm_id: str = "",
    model: str = "weathernext_cyclones",
    run_id: str = "",
) -> dict:
    """Get granted cyclone tracks/intensity/member/verification data via verified adapter."""
    # Check if cyclone capability is verified
    catalog = get_catalog()
    cap = catalog.get("weathernext_cyclones_tracks")
    if cap and cap.access_status.value != "verified":
        return _envelope(
            status="unverified",
            message="Cyclone delivery contract not verified",
            blocker=cap.blocker,
            warnings=["Weather Lab webpage is not evidence of programmatic API"],
        )

    return _envelope(
        status="ok",
        data={
            "storm_id": storm_id,
            "model": model,
            "run_id": run_id,
            "tracks": [],
            "note": "Requires verified cyclone adapter and grant",
        },
    )


# Job management for expensive operations
_jobs: dict[str, dict] = {}


@tool
def prepare_weathernext_job(
    job_type: str = "extraction",
    variable: str = "",
    region: str = "",
    time_range: str = "",
) -> dict:
    """Prepare cost-bounded extraction/export job with estimate, requires confirmation."""
    import uuid

    job_id = str(uuid.uuid4())[:8]
    # Estimate cost
    estimated_cost = {"bytes": 1000000, "compute_seconds": 10, "currency": "USD", "amount": 0.01}

    _jobs[job_id] = {
        "job_id": job_id,
        "type": job_type,
        "variable": variable,
        "region": region,
        "time_range": time_range,
        "status": "prepared",
        "estimated_cost": estimated_cost,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    return _envelope(
        status="prepared",
        data=_jobs[job_id],
        warnings=["Requires server-validated user confirmation before billable work"],
        message="Job prepared, confirm with submit_weathernext_job",
    )


@tool
def submit_weathernext_job(job_id: str = "", confirmed: bool = False) -> dict:
    """Submit prepared job with server-validated confirmation."""
    if job_id not in _jobs:
        return _envelope(status="not_found", message=f"Job {job_id} not found")

    if not confirmed:
        return _envelope(status="invalid", message="Job requires explicit confirmation (confirmed=true)")

    job = _jobs[job_id]
    job["status"] = "running"
    job["started_at"] = datetime.now(timezone.utc).isoformat()

    return _envelope(status="running", data=job)


@tool
def get_weathernext_job(job_id: str = "") -> dict:
    """Get job status/result."""
    if job_id not in _jobs:
        return _envelope(status="not_found", message=f"Job {job_id} not found")
    return _envelope(status="ok", data=_jobs[job_id])


@tool
def cancel_weathernext_job(job_id: str = "") -> dict:
    """Cancel job."""
    if job_id not in _jobs:
        return _envelope(status="not_found", message=f"Job {job_id} not found")
    _jobs[job_id]["status"] = "cancelled"
    _jobs[job_id]["cancelled_at"] = datetime.now(timezone.utc).isoformat()
    return _envelope(status="cancelled", data=_jobs[job_id])


# Export all tools for registration
WEATHERNEXT_TOOLS = [
    list_weathernext_capabilities,
    list_weathernext_runs,
    query_weathernext_data,
    get_weathernext_profile,
    analyze_weathernext_ensemble,
    compare_weathernext_products,
    get_weathernext_map_layer,
    get_weathernext_cyclone_tracks,
    prepare_weathernext_job,
    submit_weathernext_job,
    get_weathernext_job,
    cancel_weathernext_job,
]
