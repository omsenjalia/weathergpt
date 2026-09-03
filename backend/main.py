import os
import sys
import time
import platform
try:
    import psutil
except ImportError:
    psutil = None
from datetime import datetime
from collections import deque
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from agent import run_weather_agent, GROQ_MODEL, TOOLS

START_TIME = time.time()
START_DATETIME = datetime.now().isoformat()
RECENT_LOGS = deque(maxlen=50)

def log_event(level: str, message: str, details: dict = None):
    entry = {
        "timestamp": datetime.now().isoformat(),
        "level": level,
        "message": message,
        "details": details or {}
    }
    RECENT_LOGS.appendleft(entry)

log_event("INFO", "Backend server starting up...")

app = FastAPI(title="WeatherGPT API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    try:
        response = await call_next(request)
        duration_ms = round((time.time() - start) * 1000, 2)
        if request.url.path not in ["/health", "/dev"]:
            log_event("INFO", f"HTTP {request.method} {request.url.path} -> {response.status_code}", {"duration_ms": duration_ms})
        return response
    except Exception as exc:
        duration_ms = round((time.time() - start) * 1000, 2)
        log_event("ERROR", f"HTTP {request.method} {request.url.path} failed: {str(exc)}", {"duration_ms": duration_ms, "error": str(exc)})
        return JSONResponse(status_code=500, content={"error": str(exc)})


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str = ""
    messages: list[dict] = []
    location: str = ""
    language: str = "English"


class ChatResponse(BaseModel):
    response: str


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    # Pass messages list if provided, otherwise fallback to message string
    payload = request.messages if request.messages else request.message
    response = await run_in_threadpool(
        run_weather_agent, payload, request.location, request.language
    )
    return ChatResponse(response=response)


@app.get("/health")
@app.get("/health/")
async def health():
    return {"status": "ok"}


@app.get("/dev")
@app.get("/dev/")
async def dev_diagnostics():
    uptime = round(time.time() - START_TIME, 2)
    if psutil:
        try:
            process = psutil.Process(os.getpid())
            mem_info = process.memory_info()
            mem_mb = round(mem_info.rss / (1024 * 1024), 2)
            cpu_pct = process.cpu_percent(interval=None)
        except Exception:
            mem_mb, cpu_pct = "N/A", "N/A"
    else:
        mem_mb, cpu_pct = "N/A", "N/A"

    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "server_start_time": START_DATETIME,
        "uptime_seconds": uptime,
        "system": {
            "platform": platform.platform(),
            "python_version": sys.version.split()[0],
            "process_pid": os.getpid(),
            "memory_usage_mb": mem_mb,
            "cpu_percent": cpu_pct,
        },
        "llm_config": {
            "model": GROQ_MODEL,
            "has_groq_key": bool(os.getenv("GROQ_API_KEY")),
        },
        "provider_keys_status": keys_status,
        "registered_endpoints": endpoints,
        "registered_ai_tools": ai_tools,
        "recent_logs": list(RECENT_LOGS),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8888)
