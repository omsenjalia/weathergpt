"""Chat orchestration shared by web and mobile clients.

Routing policy (per request):
  1. greeting / meta          → canned intro, no upstream calls
  2. simple weather question  → deterministic telemetry (multi-provider fusion), no LLM
  3. everything else          → LangGraph agent with a hard timeout, falling back to the
                                deterministic telemetry path on timeout / error / no key
"""

from __future__ import annotations

import concurrent.futures
import os
from dataclasses import dataclass

from schemas import ChatRequest, ClientKind

LANGUAGE_CODE_MAP: dict[str, str] = {
    "en": "English", "en-us": "English", "en-in": "English", "en-gb": "English",
    "hi": "Hindi", "hi-in": "Hindi",
    "gu": "Gujarati", "gu-in": "Gujarati",
    "mr": "Marathi", "mr-in": "Marathi",
    "ta": "Tamil", "ta-in": "Tamil",
    "te": "Telugu", "te-in": "Telugu",
    "bn": "Bengali", "bn-in": "Bengali",
    "kn": "Kannada", "kn-in": "Kannada",
    "ml": "Malayalam", "ml-in": "Malayalam",
    "pa": "Punjabi", "pa-in": "Punjabi",
    "or": "Odia", "ur": "Urdu", "as": "Assamese", "ne": "Nepali",
}

GREETINGS = (
    "hi", "hello", "hey", "yo", "sup", "namaste", "namaskar", "kem cho", "kemcho",
    "good morning", "good evening", "good night", "thanks", "thank you",
    "what do you do", "who are you", "help", "what can you do",
    "how are you", "ok", "okay", "yes", "no",
)

COMPLEX_MARKERS = (
    "compare", "historical", "anomaly", "trend", "why", "explain",
    "irrigat", "pesticide", "spray", "harvest", "sow", "crop advice",
    "multi-day plan", "week ahead detailed", "should i", "can i", "plan",
)

SIMPLE_MARKERS = (
    "weather", "temperature", "temp", "forecast", "rain", "humidity",
    "wind", "aqi", "uv", "hot", "cold", "mausam", "baarish", "hawa",
    "degree", "celsius", "condition", "climate", "storm", "thunder",
    "heat", "cool", "cloudy", "sunny", "monsoon",
)

GREETING_REPLY = (
    "I'm **WeatherGPT** — I help with live weather, forecasts, rain alerts, "
    "air quality, and farming advisories.\n\n"
    "Try asking: *Will it rain tomorrow in Ahmedabad?* or *What's the temperature in Delhi?*"
)


def normalize_language(lang: str | None) -> str:
    """Map ISO codes (mobile) and display names (web) to a canonical language name."""
    raw = (lang or "").strip()
    if not raw:
        return "English"
    lower = raw.lower().replace("_", "-")
    if lower in LANGUAGE_CODE_MAP:
        return LANGUAGE_CODE_MAP[lower]
    return raw[:1].upper() + raw[1:]


def language_from_header(accept_language: str | None) -> str | None:
    """Primary tag from an `Accept-Language` header, or None."""
    if not accept_language:
        return None
    primary = accept_language.split(",")[0].strip().split(";")[0].strip()
    return primary or None


def detect_client(request: ChatRequest, user_agent: str | None = None) -> ClientKind:
    hint = (request.client or "").strip().lower()
    if hint in ("web", "browser"):
        return "web"
    if hint in ("mobile", "app", "android", "ios", "flutter"):
        return "mobile"
    if request.lat is not None and request.lon is not None:
        return "mobile"
    ua = (user_agent or "").lower()
    if "dart" in ua or "okhttp" in ua or "flutter" in ua:
        return "mobile"
    if "mozilla" in ua:
        return "web"
    return "unknown"


def is_greeting_or_meta(text: str) -> bool:
    q = (text or "").strip().lower().rstrip("!?. ")
    if not q:
        return True
    if q in GREETINGS:
        return True
    return any(q.startswith(g + sep) for g in GREETINGS for sep in (" ", "?", "!", ","))


def is_simple_weather_query(text: str, farmer_mode: bool) -> bool:
    """Heuristic: current conditions / short forecast → deterministic path only."""
    if farmer_mode:
        return False
    q = (text or "").lower().strip()
    if not q or len(q) > 220 or is_greeting_or_meta(q):
        return False
    if any(m in q for m in COMPLEX_MARKERS):
        return False
    if any(m in q for m in SIMPLE_MARKERS):
        return True
    tokens = [t for t in q.replace("?", " ").split() if t]
    return 2 <= len(tokens) <= 5 and all(t.isalpha() for t in tokens)


def resolve_history(request: ChatRequest) -> tuple[list[dict] | str, str]:
    """Return (payload for the agent, last user utterance) for either client shape."""
    if request.messages:
        last = next(
            (str(m.get("content") or "") for m in reversed(request.messages)
             if isinstance(m, dict) and m.get("role") == "user"),
            "",
        )
        return request.messages, (last or request.message).strip()
    return request.message, request.message.strip()


@dataclass
class ChatResult:
    response: str
    path: str  # "greeting" | "fast" | "agent" | "fallback"
    client: ClientKind
    language: str
    location: str


def run_chat(request: ChatRequest, *, client: ClientKind = "unknown") -> ChatResult:
    """Synchronous chat pipeline. Call via `run_in_threadpool` from async handlers."""
    from agent import run_deterministic_telemetry_fallback, run_weather_agent, has_llm

    payload, last_msg = resolve_history(request)
    language = normalize_language(request.language)
    location = (request.location or "").strip() or "New Delhi"
    timeout_s = float(os.getenv("CHAT_TIMEOUT_SECONDS", "22"))
    fast_path = os.getenv("CHAT_FAST_PATH", "1") != "0"

    def _result(text: str, path: str) -> ChatResult:
        return ChatResult(text, path, client, language, location)

    def _fallback(path: str = "fallback") -> ChatResult:
        return _result(
            run_deterministic_telemetry_fallback(
                location, last_msg, language, lat=request.lat, lon=request.lon
            ),
            path,
        )

    if is_greeting_or_meta(last_msg):
        return _result(GREETING_REPLY, "greeting")

    if fast_path and is_simple_weather_query(last_msg, bool(request.farmer_mode)):
        try:
            return _fallback("fast")
        except Exception as exc:
            print(f"[chat] fast path failed: {exc}")

    if not has_llm():
        return _fallback()

    def _agent() -> str:
        return run_weather_agent(payload, location, language, request.farmer_mode, request.crop)

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            text = pool.submit(_agent).result(timeout=timeout_s)
        return _result(text, "agent")
    except concurrent.futures.TimeoutError:
        print("[chat] agent timeout — deterministic fallback")
    except Exception as exc:
        print(f"[chat] agent error: {exc}")
    return _fallback()
