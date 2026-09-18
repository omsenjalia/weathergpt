"""Health, diagnostics, sandbox and fusion-inspector endpoints (web Dev Suite + uptime probes)."""

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

    Exposes per-provider readings, trust weights, outlier flags and the fused result so the
    web Dev Suite "Ensemble Inspector" and the mobile app can show the same numbers without
    shipping vendor API keys to the client.
    """
    fused = await run_in_threadpool(fuse_current_weather, lat, lon)
    if fused.get("error"):
        raise HTTPException(status_code=502, detail=fused["error"])
    return {
        "lat": lat,
        "lon": lon,
        "priority": ["Open-Meteo (ECMWF)", "AccuWeather", "WeatherAPI.com", "Tomorrow.io", "OpenWeatherMap"],
        "configured_providers": configured_providers(),
        **fused,
    }


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
    """Chat-routing decision inspector: keyword classifier vs TypeSafe System One.

    Runs the exact same `decide_intent` as `/chat` and shows both engines'
    answers, the full System One probability distribution, which engine wins,
    and whether the message would take the deterministic fast path. Offline
    diagnostics: without a TYPESAFE_API_KEY the System One block is null.
    """
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
            "chat_routing": typesafe.is_enabled()
            and os.getenv("TYPESAFE_CHAT_ROUTING", "1") != "0",
            "advisory_scoring": typesafe.is_enabled(),
        },
        "provider_keys_status": {
            "groq_api_key": _has("GROQ_API_KEY"),
            "weatherapi_key": _has("WEATHERAPI_KEY", "VITE_WEATHERAPI_KEY"),
            "tomorrow_key": _has("TOMORROW_KEY", "VITE_TOMORROW_KEY"),
            "openweather_key": _has("OPENWEATHER_KEY", "VITE_OPENWEATHER_KEY"),
            "accuweather_key": _has("ACCUWEATHER_KEY", "VITE_ACCUWEATHER_KEY"),
        },
        "fusion": {"weights": PROVIDER_WEIGHTS, "configured_providers": configured_providers()},
        "registered_endpoints": endpoints,
        "registered_ai_tools": [getattr(t, "name", str(t)) for t in TOOLS],
        "recent_logs": list(RECENT_LOGS),
    }
