"""WeatherGPT API — single FastAPI app serving two clients.

    weathergpt  (web,    React/Vite)   → POST /chat, GET /dev, POST /dev/sandbox, GET /fusion, /v2/weather/*
    weathergpt-app (mobile, Flutter)   → POST /chat, GET /weather, /advisory, /historical, /comparison, /v2/decisions/*

Layout
------
    main.py            app factory + middleware (this file)
    schemas.py         shared pydantic contracts
    state.py           uptime + recent-log ring buffer
    services/          open_meteo (baseline), fusion (legacy), forecast (IMD->WeatherNext->AccuWeather->Open-Meteo),
                       config (typed loader), weathernext_auth (credentials factory),
                       weathernext_catalog, weathernext_tools, forecast_cache, forecast_aggregation,
                       decisions/* (registry, engine, policy, features, questions, audit),
                       chat (routing policy), advisory (farm logic), typesafe (Jev)
    routers/           chat, mobile, dev, weather_v2, decisions
    agent.py, tools.py LangGraph agent + telemetry tools with parity

Run locally:  uvicorn main:app --host 0.0.0.0 --port 8888
Vercel:       api/index.py re-exports `app`.
"""

from __future__ import annotations

import time
import uuid

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

from routers import chat as chat_router  # noqa: E402
from routers import dev as dev_router  # noqa: E402
from routers import mobile as mobile_router  # noqa: E402
from routers import weather_v2 as weather_v2_router  # noqa: E402
from routers import decisions as decisions_router  # noqa: E402
from state import log_event  # noqa: E402
from services.config import get_config  # noqa: E402

API_VERSION = "2.1.0"
QUIET_PATHS = {"/health", "/health/", "/dev", "/dev/"}

CHAT_CONTRACT = {
    "request": {
        "message": "string (mobile single turn)",
        "messages": "[{role, content}] (web history; mobile may also send)",
        "location": "string",
        "lat": "number optional (mobile)",
        "lon": "number optional (mobile)",
        "language": "English | Hindi | ... (web) or en | hi | ... (mobile / Accept-Language)",
        "farmer_mode": "bool",
        "crop": "string",
        "client": "web | mobile optional hint",
        "mode": "everyone|farmer|researcher (new, validated)",
        "requested_source": "auto|imd|weathernext|accuweather|open_meteo (researcher)",
        "model": "weathernext_2|weathernext_3 (when requested_source=weathernext)",
    },
    "response": {
        "response": "markdown string",
        "meta": "{path, client, language, location, requested_source, selected_source, provenance}",
        "v2": "Optional structured weather/decision evidence for new clients",
    },
}


def create_app() -> FastAPI:
    app = FastAPI(
        title="WeatherGPT API",
        version=API_VERSION,
        description=(
            "Shared backend for **weathergpt** (web) and **weathergpt-app** (Flutter).\n\n"
            "Forecast provider priority (new): **IMD (when configured and eligible) → "
            "Google DeepMind WeatherNext → AccuWeather → Open-Meteo (fallback)**. "
            "Legacy fusion (Open-Meteo > AccuWeather > others) retained as diagnostic.\n\n"
            "WeatherNext surfaces: WN2/WN3 BigQuery, GCS statistics, GCS full ensemble (64 members), "
            "Earth Engine tiles, with capability catalog at /v2/weather/catalog.\n\n"
            "Decision platform: 45 initial Jev features across routing, farmer, everyone, "
            "researcher, quality, ops with off/shadow/enforce controls at /v2/decisions/*.\n\n"
            "LangGraph agent has parity between bind_tools and ToolNode for all capabilities."
        ),
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,  # must be False when allow_origins is "*" (browser rule)
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start = time.time()
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        try:
            response = await call_next(request)
        except Exception as exc:  # last-resort guard so clients always get JSON
            duration_ms = round((time.time() - start) * 1000, 2)
            log_event("ERROR", f"HTTP {request.method} {request.url.path} failed",
                      {"duration_ms": duration_ms, "request_id": request_id, "error": str(exc)})
            return JSONResponse(
                status_code=500,
                content={"detail": "Internal server error", "request_id": request_id},
                headers={"Access-Control-Allow-Origin": "*", "X-Request-ID": request_id},
            )
        if request.url.path not in QUIET_PATHS:
            log_event(
                "INFO",
                f"HTTP {request.method} {request.url.path} -> {response.status_code}",
                {"duration_ms": round((time.time() - start) * 1000, 2), "request_id": request_id},
            )
        response.headers["X-Request-ID"] = request_id
        return response

    app.include_router(chat_router.router)
    app.include_router(mobile_router.router)
    app.include_router(dev_router.router)
    app.include_router(weather_v2_router.router)
    app.include_router(decisions_router.router)
    app.include_router(decisions_router.admin_router)

    @app.get("/", tags=["meta"])
    async def root():
        """Service index — confirms the dual-client API surface."""
        cfg = get_config()
        return {
            "service": "WeatherGPT API",
            "version": API_VERSION,
            "status": "ok",
            "clients": {
                "web": {"repo": "weathergpt",
                        "endpoints": ["/chat", "/fusion", "/dev", "/dev/sandbox", "/health", "/v2/weather/*"]},
                "mobile": {"repo": "weathergpt-app",
                           "endpoints": ["/chat", "/weather", "/advisory", "/historical",
                                         "/comparison", "/fusion", "/health", "/v2/decisions/*"]},
            },
            "provider_priority": {
                "current": cfg.provider_priority,
                "default": ["imd", "weathernext", "accuweather", "open_meteo"],
                "policy_version": "1.0.0",
                "legacy_fusion": ["Open-Meteo (ECMWF)", "AccuWeather", "WeatherAPI.com",
                                  "Tomorrow.io", "OpenWeatherMap"],
            },
            # Backward compat for old clients/tests expecting fusion_priority
            "fusion_priority": ["Open-Meteo (ECMWF)", "AccuWeather", "WeatherAPI.com", "Tomorrow.io", "OpenWeatherMap"],
            "weathernext": {
                "enabled": cfg.weathernext.enabled,
                "auth_mode": cfg.weathernext.auth_mode,
                "surface": cfg.weathernext.surface,
                "surfaces": ["bigquery", "gcs_statistics", "gcs_ensemble", "earth_engine"],
                "project": cfg.weathernext.project,
                "tables": {
                    "wn3_0p1": cfg.weathernext.bq.table_3 or cfg.weathernext.bq.surface_table,
                    "wn3_0p05": cfg.weathernext.bq.table_3_high_resolution,
                    "wn2": cfg.weathernext.bq.table_2,
                },
            },
            "jev": {
                "enabled": cfg.jev.enabled,
                "model": cfg.jev.model,
                "weathernext_mode": cfg.jev.weathernext_mode,
                "decision_features": cfg.jev.decision_features,
            },
            "chat_contract": CHAT_CONTRACT,
        }

    log_event("INFO", "Backend server starting up with WeatherNext + Jev decision platform...")
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8888)
