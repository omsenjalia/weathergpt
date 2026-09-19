"""Health, diagnostics, sandbox and fusion-inspector endpoints (web Dev Suite + uptime probes).

Extended with:
- Source health, latest complete runs, freshness/coverage, fallback reasons, cache/query-cost diagnostics
- Decision platform health
- WeatherNext connectivity checks (admin-only, no secrets)
"""

from __future__ import annotations

import os
import platform
import sys
import time
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from schemas import SandboxRequest
from services import typesafe
from services.fusion import PROVIDER_WEIGHTS, configured_providers, fuse_current_weather
from services.config import get_config
from services.weathernext_auth import get_credentials_factory_status, check_connectivity
from services.forecast import get_forecast_service
from services.forecast_cache import get_cache as get_forecast_cache
from services.decisions.audit import get_decision_cache_stats, get_audit_stats
from services.weathernext_catalog import get_catalog
from state import RECENT_LOGS, START_DATETIME, START_TIME

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

router = APIRouter(tags=["dev"])

CLIENTS = ["weathergpt", "weathergpt-app"]


@router.get("/health")
@router.get("/health/", include_in_schema=False)
async def health():
    return {"status": "ok", "clients": CLIENTS, "uptime_s": round(time.time() - START_TIME, 1)}


@router.get("/fusion")
async def fusion_inspector(
    lat: float = Query(..., description="Latitude"),
    lon: float = Query(..., description="Longitude"),
):
    """Server-side ensemble fusion for the given coordinates.

    Legacy diagnostic: per-provider readings, trust weights, outlier flags.
    New provider chain is at /v2/weather/health and /v2/weather?source=auto.
    """
    fused = await run_in_threadpool(fuse_current_weather, lat, lon)
    if fused.get("error"):
        raise HTTPException(status_code=502, detail=fused["error"])
    return {
        "lat": lat,
        "lon": lon,
        "priority_legacy": ["Open-Meteo (ECMWF)", "AccuWeather", "WeatherAPI.com", "Tomorrow.io", "OpenWeatherMap"],
        "priority_new": get_config().provider_priority,
        "configured_providers": configured_providers(),
        **fused,
    }


@router.get("/dev/weathernext")
async def dev_weathernext_health(
    probe: int = Query(0, description="1 = resolve credentials and run a BigQuery dry run (no bytes billed)"),
):
    """WeatherNext connectivity check - admin diagnostics without secrets.

    Default is offline (config + credential presence). ``probe=1`` resolves the
    credential chain (SA JSON -> ADC -> OAuth) and dry-runs the point query so
    the estimated bytes can be compared with WEATHERNEXT_BQ_MAX_BYTES_BILLED.
    """
    def _check():
        cfg = get_config().weathernext
        bigquery_stats = None
        try:
            from services.weathernext_bigquery import get_bigquery_adapter
            bigquery_stats = get_bigquery_adapter().stats()
        except Exception as exc:  # pragma: no cover
            bigquery_stats = {"error": type(exc).__name__}
        return {
            "auth": get_credentials_factory_status(),
            "connectivity": check_connectivity(probe=bool(probe)),
            "bigquery": bigquery_stats,
            "catalog_coverage": get_catalog().coverage_report(),
            "config": {
                "enabled": cfg.enabled,
                "auth_mode": cfg.auth_mode,
                "surface": cfg.surface,
                "table": cfg.bq.surface_table,
                "credential_sources": cfg.credential_sources(),
                "provider_priority": get_config().provider_priority,
            },
        }
    return await run_in_threadpool(_check)


@router.get("/dev/forecast")
async def dev_forecast_health(
    lat: float = Query(22.0, description="Sample lat"),
    lon: float = Query(72.0, description="Sample lon"),
):
    """Source health, latest complete runs, freshness/coverage, fallback reasons, cache diagnostics."""
    def _check():
        service = get_forecast_service()
        cache = get_forecast_cache()
        result = service.select_forecast(lat=lat, lon=lon, product="forecast", requested_source="auto", mode="everyone")
        return {
            "sample_location": {"lat": lat, "lon": lon},
            "selection": {
                "selected_source": result.selected_source.value,
                "requested_source": result.requested_source,
                "fallback_reasons": result.fallback_reasons,
                "tried_providers": result.tried_providers,
                "is_stale": result.is_stale,
                "latency_ms": result.latency_ms,
                "error": result.error,
                "has_forecast": result.forecast is not None,
                "provenance": result.forecast.provenance.to_dict() if result.forecast else None,
            },
            "provider_health": {
                name.value: {
                    "configured": provider.is_configured(),
                    "consecutive_failures": provider._consecutive_failures,
                    "circuit_breaker": provider.should_circuit_break(),
                }
                for name, provider in service.providers.items()
            },
            "cache": cache.stats(),
            "generated_at": datetime.now().isoformat(),
        }
    return await run_in_threadpool(_check)


@router.get("/dev/decisions")
async def dev_decisions_health():
    """Protected decision inspector, shadow comparison and redacted failure counters."""
    def _check():
        return {
            "cache_and_audit": get_decision_cache_stats(),
            "audit_stats": get_audit_stats(),
            "config": {
                "weathernext_mode": get_config().jev.weathernext_mode,
                "enabled_features": get_config().jev.decision_features,
                "total_budget_ms": get_config().jev.total_budget_ms,
                "max_calls_per_request": get_config().jev.max_calls_per_request,
            },
            "generated_at": datetime.now().isoformat(),
        }
    return await run_in_threadpool(_check)


@router.post("/dev/sandbox")
@router.post("/dev/sandbox/", include_in_schema=False)
async def sandbox_test(request: SandboxRequest):
    from agent import GROQ_MODEL, run_weather_agent

    start = time.time()
    try:
        response = await run_in_threadpool(
            run_weather_agent, request.prompt, request.location, request.language
        )
        return {
            "status": "success",
            "duration_ms": round((time.time() - start) * 1000, 2),
            "prompt": request.prompt,
            "location": request.location,
            "language": request.language,
            "response": response,
            "model_used": GROQ_MODEL,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "duration_ms": round((time.time() - start) * 1000, 2),
                "error": str(exc),
                "timestamp": datetime.now().isoformat(),
            },
        )


@router.get("/dev/intent")
@router.get("/dev/intent/", include_in_schema=False)
async def dev_intent(
    text: str = Query(
        ...,
        min_length=1,
        max_length=500,
        description="Sample user message to classify",
    ),
) -> dict:
    """Chat-routing decision inspector: keyword classifier vs TypeSafe System One."""
    from services.chat import FAST_INTENTS, decide_intent, is_simple_weather_query

    started = time.perf_counter()
    decision = await run_in_threadpool(decide_intent, text)
    ai = decision.get("ai")
    fast_path_enabled = os.getenv("CHAT_FAST_PATH", "1") != "0"
    if decision["engine"] == "system-one" and ai:
        would_fast_path = (
            decision["intent"] in FAST_INTENTS and (ai.get("live_data") or 0.0) >= 0.7
        )
        system_one = {
            "route": ai.get("route"),
            "probabilities": ai.get("probabilities") or {},
            "confidence": ai.get("confidence"),
            "live_data": ai.get("live_data"),
            "smalltalk": ai.get("smalltalk"),
            "abuse": ai.get("abuse"),
        }
    else:
        would_fast_path = fast_path_enabled and is_simple_weather_query(text, False)
        system_one = None
    return {
        "text": text,
        "engine": decision["engine"],
        "intent": decision["intent"],
        "confidence": decision["confidence"],
        "keyword_intent": decision["keyword_intent"],
        "system_one": system_one,
        "would_fast_path": bool(would_fast_path),
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        "timestamp": datetime.now().isoformat(),
    }


@router.get("/dev")
@router.get("/dev/", include_in_schema=False)
async def dev_diagnostics(http_request: Request):
    from agent import GROQ_MODEL, TOOLS

    mem_mb: float | str = "N/A"
    cpu_pct: float | str = "N/A"
    if psutil:
        try:
            proc = psutil.Process(os.getpid())
            mem_mb = round(proc.memory_info().rss / (1024 * 1024), 2)
            cpu_pct = proc.cpu_percent(interval=None)
        except Exception:
            pass

    app = http_request.app
    endpoints = []
    for route in app.routes:
        path = getattr(route, "path", None)
        if not path or not getattr(route, "include_in_schema", True):
            continue
        methods = getattr(route, "methods", None)
        endpoints.append(f"{path} [{','.join(sorted(methods)) if methods else 'GET'}]")

    def _has(*names: str) -> bool:
        return any(os.getenv(n) and not os.getenv(n, "").startswith("your_") for n in names)

    cfg = get_config()

    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "server_start_time": START_DATETIME,
        "uptime_seconds": round(time.time() - START_TIME, 2),
        "clients": CLIENTS,
        "system": {
            "platform": platform.platform(),
            "python_version": sys.version.split()[0],
            "process_pid": os.getpid(),
            "memory_usage_mb": mem_mb,
            "cpu_percent": cpu_pct,
        },
        "llm_config": {"model": GROQ_MODEL, "has_groq_key": _has("GROQ_API_KEY")},
        "ai_decisions": {
            "typesafe_enabled": typesafe.is_enabled(),
            "typesafe_model": typesafe.model_name() if typesafe.is_enabled() else None,
            "chat_routing": typesafe.is_enabled() and os.getenv("TYPESAFE_CHAT_ROUTING", "1") != "0",
            "advisory_scoring": typesafe.is_enabled(),
            "weathernext_mode": cfg.jev.weathernext_mode,
            "decision_features": cfg.jev.decision_features,
        },
        "provider_keys_status": {
            "groq_api_key": _has("GROQ_API_KEY"),
            "weatherapi_key": _has("WEATHERAPI_KEY", "VITE_WEATHERAPI_KEY"),
            "tomorrow_key": _has("TOMORROW_KEY", "VITE_TOMORROW_KEY"),
            "openweather_key": _has("OPENWEATHER_KEY", "VITE_OPENWEATHER_KEY"),
            "accuweather_key": _has("ACCUWEATHER_KEY", "VITE_ACCUWEATHER_KEY"),
            "imd_api_key": _has("IMD_API_KEY"),
            "imd_jwt_token": _has("IMD_JWT_TOKEN"),
            "typesafe_api_key": _has("TYPESAFE_API_KEY"),
        },
        "weathernext": {
            "enabled": cfg.weathernext.enabled,
            "auth_mode": cfg.weathernext.auth_mode,
            "surface": cfg.weathernext.surface,
            "project": cfg.weathernext.project,
            "provider_priority": cfg.provider_priority,
            "auth_status": get_credentials_factory_status(),
        },
        "fusion": {
            "weights": PROVIDER_WEIGHTS,
            "configured_providers": configured_providers(),
            "new_priority": cfg.provider_priority,
        },
        "forecast_cache": get_forecast_cache().stats(),
        "decision_cache": get_decision_cache_stats(),
        "catalog_coverage": get_catalog().coverage_report(),
        "registered_endpoints": endpoints,
        "registered_ai_tools": [getattr(t, "name", str(t)) for t in TOOLS],
        "recent_logs": list(RECENT_LOGS),
    }
