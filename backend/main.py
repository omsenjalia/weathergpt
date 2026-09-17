"""WeatherGPT API — single FastAPI app serving two clients.

    weathergpt  (web,    React/Vite)   → POST /chat, GET /dev, POST /dev/sandbox, GET /fusion
    weathergpt-app (mobile, Flutter)   → POST /chat, GET /weather, /advisory, /historical, /comparison

Layout
------
    main.py            app factory + middleware (this file)
    schemas.py         shared pydantic contracts
    state.py           uptime + recent-log ring buffer
    services/          open_meteo (baseline provider), fusion (ensemble), chat (routing policy)
    routers/           chat, mobile, dev
    agent.py, tools.py LangGraph agent + telemetry tools (unchanged public API)

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
from state import log_event  # noqa: E402

API_VERSION = "2.0.0"
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
    },
    "response": {"response": "markdown string", "meta": "{path, client, language, location}"},
}


def create_app() -> FastAPI:
    app = FastAPI(
        title="WeatherGPT API",
        version=API_VERSION,
        description=(
            "Shared backend for **weathergpt** (web) and **weathergpt-app** (Flutter).\n\n"
            "Current conditions everywhere come from the multi-provider fusion engine with "
            "priority **Open-Meteo > AccuWeather > WeatherAPI / Tomorrow.io / OpenWeatherMap**."
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

    @app.get("/", tags=["meta"])
    async def root():
        """Service index — confirms the dual-client API surface."""
        return {
            "service": "WeatherGPT API",
            "version": API_VERSION,
            "status": "ok",
            "clients": {
                "web": {"repo": "weathergpt",
                        "endpoints": ["/chat", "/fusion", "/dev", "/dev/sandbox", "/health"]},
                "mobile": {"repo": "weathergpt-app",
                           "endpoints": ["/chat", "/weather", "/advisory", "/historical",
                                         "/comparison", "/fusion", "/health"]},
            },
            "fusion_priority": ["Open-Meteo (ECMWF)", "AccuWeather", "WeatherAPI.com",
                                "Tomorrow.io", "OpenWeatherMap"],
            "chat_contract": CHAT_CONTRACT,
        }

    log_event("INFO", "Backend server starting up...")
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8888)
