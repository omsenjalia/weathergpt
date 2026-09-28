"""Health, diagnostics and developer tools (web Dev Suite, app Debug screen, uptime probes)."""

from __future__ import annotations

import os
import platform
import sys
import time
from datetime import datetime, timezone

import hmac

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from weathergpt import __version__
from weathergpt.ai import agent, intent, typesafe
from weathergpt.ai.tools import TOOLS
from weathergpt.config import settings
from weathergpt.imd import client as imd_client
from weathergpt.runtime import RECENT_LOGS, START_DATETIME, cache_stats, uptime_seconds
from weathergpt.speech import bhashini
from weathergpt.weather.service import service

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

router = APIRouter(tags=["dev"])
CLIENTS = ["weathergpt (web)", "weathergpt-app", "weathergpt-android"]


def require_admin(token: str | None) -> None:
    """Operator-only routes need ``X-Admin-Token`` matching ADMIN_TOKEN (disabled when unset)."""
    expected = (os.getenv("ADMIN_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(status_code=403, detail="Set ADMIN_TOKEN on the server to enable this route")
    if not token or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Invalid X-Admin-Token")


@router.get("/health")
@router.get("/health/", include_in_schema=False)
async def health() -> dict:
    return {"status": "ok", "version": __version__, "clients": CLIENTS, "uptime_s": uptime_seconds()}


@router.get("/dev")
@router.get("/dev/", include_in_schema=False)
async def diagnostics(http_request: Request) -> dict:
    cfg = settings()
    mem, cpu = "N/A", "N/A"
    if psutil:
        try:
            proc = psutil.Process(os.getpid())
            mem, cpu = round(proc.memory_info().rss / 2 ** 20, 2), proc.cpu_percent(interval=None)
        except Exception:
            pass
    endpoints = sorted(f"{r.path} [{','.join(sorted(getattr(r, 'methods', None) or ['GET']))}]"
                       for r in http_request.app.routes if getattr(r, "include_in_schema", True) and getattr(r, "path", None))
    return {
        "status": "ok",
        "version": __version__,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "server_start_time": START_DATETIME,
        "uptime_seconds": uptime_seconds(),
        "clients": CLIENTS,
        "system": {"platform": platform.platform(), "python_version": sys.version.split()[0],
                   "process_pid": os.getpid(), "memory_usage_mb": mem, "cpu_percent": cpu},
        "llm_config": {"model": cfg.groq_model, "fallbacks": list(cfg.groq_fallback_models), "has_groq_key": cfg.has_llm},
        "provider_priority": list(cfg.provider_priority),
        "provider_keys_status": {
            "groq_api_key": cfg.has_llm,
            "imd_api_key": bool(cfg.imd.api_key),
            "imd_jwt_token": bool(cfg.imd.jwt_token),
            "weathernext_enabled": cfg.weathernext.enabled,
            "google_credentials": bool(cfg.weathernext.credential_sources()),
            "bhashini": bhashini.is_configured(),
            "typesafe_api_key": typesafe.is_enabled(),
        },
        "provider_health": service().health(),
        "imd": imd_client.status(),
        "caches": cache_stats(),
        "registered_endpoints": endpoints,
        "registered_ai_tools": [t.name for t in TOOLS],
        "recent_logs": list(RECENT_LOGS),
    }


class SandboxRequest(BaseModel):
    prompt: str
    location: str = "New Delhi"
    language: str = "English"


@router.post("/dev/sandbox")
@router.post("/dev/sandbox/", include_in_schema=False)
async def sandbox(req: SandboxRequest) -> dict:
    from weathergpt.ai import chat as orchestrator

    started = time.time()
    turn = orchestrator.ChatTurn(message=req.prompt, history=[], language=orchestrator.language_code(req.language),
                                 location=req.location)
    try:
        out = await run_in_threadpool(orchestrator.run, turn)
        return {"status": "success", "duration_ms": round((time.time() - started) * 1000, 2), "prompt": req.prompt,
                "location": req.location, "language": req.language, "response": out.response, "path": out.path,
                "model_used": settings().groq_model if out.path == "agent" else "deterministic",
                "timestamp": datetime.now(timezone.utc).isoformat()}
    except Exception as exc:
        return {"status": "error", "duration_ms": round((time.time() - started) * 1000, 2), "error": str(exc),
                "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("/dev/intent")
async def dev_intent(text: str = Query(..., min_length=1, max_length=500)) -> dict:
    decision = await run_in_threadpool(intent.decide, text)
    return {"text": text, **decision, "fast_path_intent": decision["intent"] in intent.FAST_INTENTS}


@router.get("/dev/forecast")
async def dev_forecast(lat: float = Query(23.02), lon: float = Query(72.57), requested_source: str = Query("auto")) -> dict:
    def work() -> dict:
        sel = service().select(lat, lon, requested_source=requested_source)
        return {"selected_source": sel.selected_source, "requested_source": sel.requested_source,
                "fallback_reasons": sel.fallback_reasons, "tried_providers": sel.tried_providers,
                "is_stale": sel.is_stale, "degraded": sel.degraded, "latency_ms": sel.latency_ms, "error": sel.error,
                "provenance": sel.forecast.provenance.to_dict() if sel.forecast else None}
    return await run_in_threadpool(work)


@router.get("/dev/imd/probe")
async def imd_probe(x_admin_token: str | None = Header(None)) -> dict:
    """Calls every IMD endpoint once (uncached) — run this right after adding IMD credentials."""
    require_admin(x_admin_token)
    if not settings().imd.configured:
        return {"status": "not_configured", "missing": settings().imd.missing()}
    results = await run_in_threadpool(imd_client.probe)
    return {"status": "ok", "ok": sum(r["ok"] for r in results), "total": len(results), "results": results}


@router.post("/dev/reset")
async def reset_caches(x_admin_token: str | None = Header(None)) -> dict:
    """Drop caches and reload configuration (after rotating credentials)."""
    require_admin(x_admin_token)
    from weathergpt.config import reset_settings
    from weathergpt.runtime import clear_all_caches
    from weathergpt.weather.service import reset_service
    from weathergpt.weathernext import auth

    reset_settings()
    clear_all_caches()
    reset_service()
    auth.reset()
    agent.reset()
    return {"status": "ok"}
