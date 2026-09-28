"""Chat / voice orchestration shared by the web app and both mobile apps.

Per turn:
1. intent (keywords, optionally System One) -> greeting / off-topic / abuse get canned replies
2. resolve the place (named in the question, else the client's location)
3. gather live evidence once (forecast chain + supplement + official warnings)
4. simple weather asks -> deterministic answer from that evidence (localised by the LLM when available)
   everything else -> LangGraph agent with the evidence in its prompt, hard timeout
5. any agent failure -> the deterministic answer; a pinned source is never substituted

The response always carries ``card`` when there is data, built from the same
evidence, so the mobile result screen shows real numbers and never canned ones.
"""

from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass, field
from typing import Any, Optional

from weathergpt import geo
from weathergpt.ai import agent, evidence, intent, place
from weathergpt.ai.sanitize import sanitize_response
from weathergpt.config import settings
from weathergpt.runtime import log_event

LANGUAGES = {
    "en": "English", "hi": "Hindi", "gu": "Gujarati", "mr": "Marathi", "ta": "Tamil", "te": "Telugu",
    "bn": "Bengali", "kn": "Kannada", "ml": "Malayalam", "pa": "Punjabi", "or": "Odia", "ur": "Urdu",
    "as": "Assamese",
}
_NAME_TO_CODE = {v.lower(): k for k, v in LANGUAGES.items()}

GREETING = {
    "en": "I'm **WeatherGPT** — ask me about the weather, rain, air quality, official IMD warnings or your farm. "
          "Try: *Will it rain tomorrow in Ahmedabad?*",
    "hi": "मैं **WeatherGPT** हूँ — मौसम, बारिश, वायु गुणवत्ता, IMD चेतावनी या खेती के बारे में पूछिए। "
          "जैसे: *क्या कल अहमदाबाद में बारिश होगी?*",
    "gu": "હું **WeatherGPT** છું — હવામાન, વરસાદ, હવાની ગુણવત્તા, IMD ચેતવણી કે ખેતી વિશે પૂછો. "
          "જેમ કે: *કાલે અમદાવાદમાં વરસાદ પડશે?*",
    "mr": "मी **WeatherGPT** आहे — हवामान, पाऊस, हवेची गुणवत्ता, IMD इशारे किंवा शेतीबद्दल विचारा.",
    "ta": "நான் **WeatherGPT** — வானிலை, மழை, காற்றின் தரம், IMD எச்சரிக்கைகள் அல்லது விவசாயம் பற்றி கேளுங்கள்.",
    "te": "నేను **WeatherGPT** — వాతావరణం, వర్షం, గాలి నాణ్యత, IMD హెచ్చరికలు లేదా వ్యవసాయం గురించి అడగండి.",
    "bn": "আমি **WeatherGPT** — আবহাওয়া, বৃষ্টি, বাতাসের মান, IMD সতর্কতা বা চাষ নিয়ে জিজ্ঞাসা করুন।",
    "kn": "ನಾನು **WeatherGPT** — ಹವಾಮಾನ, ಮಳೆ, ಗಾಳಿಯ ಗುಣಮಟ್ಟ, IMD ಎಚ್ಚರಿಕೆಗಳು ಅಥವಾ ಕೃಷಿ ಬಗ್ಗೆ ಕೇಳಿ.",
    "ml": "ഞാൻ **WeatherGPT** — കാലാവസ്ഥ, മഴ, വായു ഗുണനിലവാരം, IMD മുന്നറിയിപ്പുകൾ അല്ലെങ്കിൽ കൃഷി എന്നിവയെക്കുറിച്ച് ചോദിക്കൂ.",
}
OFF_TOPIC = {
    "en": "I'm a weather assistant, so I can't help with that — but ask me about weather, rain, air quality, "
          "official warnings or farm timing.",
    "hi": "मैं मौसम सहायक हूँ, इसलिए इसमें मदद नहीं कर सकता — मौसम, बारिश, वायु गुणवत्ता या खेती के बारे में पूछिए।",
    "gu": "હું હવામાન સહાયક છું, તેથી આમાં મદદ કરી શકતો નથી — હવામાન, વરસાદ કે ખેતી વિશે પૂછો.",
}
_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=16, thread_name_prefix="chat")


def language_code(value: Optional[str], accept_language: Optional[str] = None) -> str:
    raw = (value or "").strip().lower().replace("_", "-")
    code = raw.split("-")[0] if raw else ""
    if code in LANGUAGES:
        chosen = code
    elif raw in _NAME_TO_CODE:
        chosen = _NAME_TO_CODE[raw]
    else:
        chosen = "en"
    if chosen == "en" and accept_language:
        primary = accept_language.split(",")[0].split(";")[0].strip().lower().split("-")[0]
        if primary in LANGUAGES:
            chosen = primary
    return chosen


@dataclass
class ChatTurn:
    message: str
    history: list[dict]
    language: str                      # ISO code
    location: str = ""
    lat: Optional[float] = None
    lon: Optional[float] = None
    mode: str = "everyone"
    requested_source: str = "auto"
    farm: dict = field(default_factory=dict)
    client: str = "unknown"


@dataclass
class ChatOutcome:
    response: str
    path: str
    intent: dict
    card: Optional[dict] = None
    place: Optional[dict] = None
    evidence_meta: Optional[dict] = None


def _clean(text: str) -> str:
    try:
        return sanitize_response(text) or text
    except Exception:
        return text


def _resolve_place(turn: ChatTurn, question: str) -> Optional[dict]:
    named = place.resolve(question)
    if named is not None:
        home = (turn.location or "").split(",")[0].strip().lower()
        if turn.lat is not None and turn.lon is not None and named["name"].lower() == home:
            return {"name": turn.location.split(",")[0].strip(), "lat": turn.lat, "lon": turn.lon}
        return named
    if turn.lat is not None and turn.lon is not None:
        return {"name": (turn.location or "your location").split(",")[0].strip(), "lat": turn.lat, "lon": turn.lon}
    if turn.location:
        return geo.geocode(turn.location.split(",")[0])
    return None


def system_prompt(turn: ChatTurn, facts: str, language_name: str) -> str:
    mode_text = {
        "farmer": ("The user is a FARMER. Give practical, date-specific advice on irrigation, spraying, sowing, "
                   "harvest and field work. Farm profile: "
                   + (", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in turn.farm.items() if v) or "not provided")
                   + ". Use get_farm_advisory for hour-level windows."),
        "researcher": ("The user is a RESEARCHER. Be precise: name sources, model runs, units, uncertainty "
                       "(p10–p90 is ensemble spread, not accuracy) and distinguish observations from model guidance. "
                       "Use get_climate_history and get_imd_product for data products."),
    }.get(turn.mode, "The user is a member of the public. Be brief, friendly and practical.")
    pin = (f"The user pinned the data source '{turn.requested_source}': use only that source and never substitute another."
           if turn.requested_source != "auto" else "")
    return f"""You are WeatherGPT, a voice-first weather assistant for India.
Answer in {language_name} (native script), in short spoken-friendly Markdown: lead with the answer in one sentence,
then at most 4 bullets. Numbers and units stay as digits. Never invent measurements: use the live data below or
call a tool. Official IMD/NDMA warnings are authoritative and must be mentioned when present; if warning status is
unknown, say it is unknown rather than 'no alerts'. Only discuss weather, climate, air quality and farming;
politely decline anything else.
{mode_text}
{pin}

{facts}
"""


def run(turn: ChatTurn) -> ChatOutcome:
    cfg = settings()
    question = turn.message.strip() or next((str(m.get("content") or "") for m in reversed(turn.history)
                                             if m.get("role") == "user"), "")
    context = " ".join(str(m.get("content") or "") for m in turn.history[-4:] if m.get("role") == "user")[-600:] or question
    decision = intent.decide(question)
    lang = turn.language
    language_name = LANGUAGES.get(lang, "English")

    if intent.is_abusive(decision) or decision["intent"] == "unrelated":
        return ChatOutcome(OFF_TOPIC.get(lang, OFF_TOPIC["en"]), "guarded", decision)
    if decision["intent"] == "greeting":
        return ChatOutcome(GREETING.get(lang, GREETING["en"]), "greeting", decision)

    where = _resolve_place(turn, question) or _resolve_place(turn, context)
    if where is None:
        return ChatOutcome("Which place should I check? Tell me a city or share your location.", "clarify", decision)

    ev = evidence.gather(where["name"], where["lat"], where["lon"], requested_source=turn.requested_source,
                         days=7 if turn.mode != "researcher" else 10)
    card = evidence.card(ev, decision["intent"])
    meta = {"selected_source": ev.selection.selected_source, "requested_source": ev.selection.requested_source,
            "degraded": ev.selection.degraded, "alerts_status": (ev.alerts or {}).get("status"),
            "fallback_reasons": ev.selection.fallback_reasons}

    def outcome(text: str, path: str) -> ChatOutcome:
        return ChatOutcome(_clean(text), path, decision, card, where, meta)

    if ev.forecast is None and turn.requested_source != "auto":
        return outcome(evidence.unavailable_reply(ev), "pinned")

    deterministic = evidence.reply(ev, decision["intent"])
    fast = (cfg.chat_fast_path and decision["intent"] in intent.FAST_INTENTS and turn.mode == "everyone"
            and len(question) <= 220 and (decision["engine"] == "keywords" or
                                          ((decision.get("ai") or {}).get("live_data") or 0) >= 0.7))

    if not cfg.has_llm:
        return outcome(deterministic, "fast" if fast else "fallback")

    if fast:
        if lang == "en":
            return outcome(deterministic, "fast")
        try:
            return outcome(_POOL.submit(agent.translate, deterministic, language_name).result(timeout=10), "fast")
        except Exception as exc:
            log_event("WARN", "chat translation failed", {"error": type(exc).__name__})
            return outcome(deterministic, "fast")

    history = turn.history or [{"role": "user", "content": question}]
    if not history or history[-1].get("content") != question:
        history = history + [{"role": "user", "content": question}]
    prompt = system_prompt(turn, evidence.facts(ev), language_name)
    future = _POOL.submit(agent.run, prompt, history)
    try:
        text = future.result(timeout=cfg.chat_timeout_seconds)
        if text and text.strip():
            if "```widget:" not in text and ev.forecast is not None:
                text = f"{text.strip()}\n\n{evidence.widgets(ev)}"
            return outcome(text, "agent")
    except concurrent.futures.TimeoutError:
        future.cancel()
        log_event("WARN", "chat agent timed out — deterministic answer served", {})
    except Exception as exc:
        log_event("WARN", "chat agent failed — deterministic answer served", {"error": f"{type(exc).__name__}: {exc}"[:200]})
    return outcome(deterministic, "fallback")


def meta_for(turn: ChatTurn, out: ChatOutcome) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "path": out.path, "client": turn.client, "language": turn.language, "mode": turn.mode,
        "location": (out.place or {}).get("name") or turn.location or None,
        "lat": (out.place or {}).get("lat"), "lon": (out.place or {}).get("lon"),
        "intent": out.intent["intent"], "intent_engine": out.intent["engine"],
    }
    if out.intent.get("confidence") is not None:
        meta["intent_confidence"] = round(out.intent["confidence"], 3)
    if out.evidence_meta:
        meta.update(out.evidence_meta)
    return meta
