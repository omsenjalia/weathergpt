"""FastAPI application factory."""

from __future__ import annotations

import hmac
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from weathergpt import __version__
from weathergpt.api import chat, dev, farm, imd, research, speech, weather
from weathergpt.config import settings
from weathergpt.runtime import log_event

QUIET_PATHS = {"/health", "/health/", "/dev", "/dev/", "/v2/speech/health"}
# Reachable without the backend secret: they reveal nothing and keep uptime probes working.
OPEN_PATHS = {"/", "/health", "/health/"}
SECRET_HEADER = "x-backend-secret"

DESCRIPTION = """Shared backend for **weathergpt** (web), **weathergpt-app** and **weathergpt-android**.

Forecast chain: **IMD → Google WeatherNext → Open-Meteo**. Gaps (hourly series, rain chance, UV, air quality,
astronomy) are filled from Open-Meteo and attributed per field in `field_sources`. Official warnings come from
IMD district warnings/nowcasts and the NDMA SACHET CAP feed. Every IMD gateway API is available under `/v2/imd`.
"""


def create_app() -> FastAPI:
    app = FastAPI(title="WeatherGPT API", version=__version__, description=DESCRIPTION)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["*"],
                       allow_headers=["*"], expose_headers=["X-Request-ID"])

    @app.middleware("http")
    async def require_backend_secret(request: Request, call_next):
        """Clients connect only when they send the same BACKEND_SECRET the server has.

        Unset on the server = no check. CORS preflights pass (browsers never attach
        custom headers to them); the real request that follows is still checked.
        """
        expected = settings().backend_secret
        if (not expected or request.method == "OPTIONS" or request.url.path in OPEN_PATHS
                or hmac.compare_digest((request.headers.get(SECRET_HEADER) or "").encode(), expected.encode())):
            return await call_next(request)
        return JSONResponse(status_code=401, headers={"Access-Control-Allow-Origin": "*"},
                            content={"detail": {"code": "backend_secret_mismatch",
                                                "message": "This client is not authorised for this backend"}})

    @app.middleware("http")
    async def request_log(request: Request, call_next):
        started = time.time()
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        try:
            response = await call_next(request)
        except Exception as exc:  # last resort: clients always get JSON
            log_event("ERROR", f"{request.method} {request.url.path} crashed",
                      {"request_id": request_id, "error": f"{type(exc).__name__}: {exc}"[:300]})
            return JSONResponse(status_code=500, content={"detail": "Internal server error", "request_id": request_id},
                                headers={"Access-Control-Allow-Origin": "*", "X-Request-ID": request_id})
        if request.url.path not in QUIET_PATHS:
            log_event("INFO", f"{request.method} {request.url.path} -> {response.status_code}",
                      {"duration_ms": round((time.time() - started) * 1000, 1), "request_id": request_id})
        response.headers["X-Request-ID"] = request_id
        return response

    for module in (weather, imd, farm, research, chat, speech, dev):
        app.include_router(module.router)

    @app.get("/", tags=["meta"])
    async def root() -> dict:
        cfg = settings()
        return {
            "service": "WeatherGPT API",
            "version": __version__,
            "status": "ok",
            "provider_priority": list(cfg.provider_priority),
            "clients": {
                "web (weathergpt)": ["/chat", "/dev", "/dev/sandbox", "/health"],
                "mobile (weathergpt-app, weathergpt-android)": [
                    "/v2/weather", "/weather", "/chat", "/advisory", "/historical", "/comparison",
                    "/v2/weather/health", "/v2/speech/health", "/v2/speech/tts", "/v2/speech/asr"],
                "shared": ["/v2/alerts", "/v2/imd", "/v2/imd/{endpoint}", "/v2/weather/series", "/v2/weather/catalog"],
            },
            "docs": "/docs",
        }

    log_event("INFO", f"WeatherGPT API {__version__} starting", {"priority": list(settings().provider_priority)})
    return app
