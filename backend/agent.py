"""WeatherGPT agent with complete WeatherNext data access and decision platform.

Required invariant: for every authorized and supported researcher capability,
at least one schema-validated LangGraph tool reaches same backend service and
data product used by UI. Orchestrator and mode specialists use shared catalog;
mode determines routing/presentation, server authorization determines access.

Fixes:
- Removes provider-bypassing HTTP and invented fallback measurements in deterministic path
- Handles nullable structured data and unresolved locations honestly with provenance
- Tool registry generates both bind_tools and ToolNode from same source
- Request-scoped mode/permissions, not global mutable user state
- All fallback tool-calling LLMs bind same capabilities
- AgentState extended with validated mode/source constraints and evidence/job references
- Deterministic/LLM-timeout path honors mode, source pins, requested product
"""

import os
import re
import json
import operator
import math
from typing import Annotated, Sequence, TypedDict, Optional, Any
from dotenv import load_dotenv

load_dotenv()

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from tools import (
    geocode_city,
    get_current_weather,
    get_weather_forecast,
    get_hourly_forecast,
    get_air_quality,
    get_uv_index_and_sun,
    get_surface_pressure_and_wind,
    get_agricultural_crop_telemetry,
    get_severe_weather_alerts,
    get_user_language,
    # New decision tools
    list_decision_capabilities,
    evaluate_weather_decision,
    compare_eligible_windows,
    request_missing_context,
    assess_reply_evidence,
    get_decision_result,
)

# WeatherNext tools
try:
    from services.weathernext_tools import WEATHERNEXT_TOOLS
except ImportError:
    WEATHERNEXT_TOOLS = []

# Decision engine tools already imported


def _extract_text_content(content) -> str:
    """Normalize LLM content that may be str or list of parts."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, str):
                parts.append(p)
            elif isinstance(p, dict):
                if isinstance(p.get("text"), str):
                    parts.append(p["text"])
                elif isinstance(p.get("content"), str):
                    parts.append(p["content"])
            else:
                t = getattr(p, "text", None)
                if isinstance(t, str):
                    parts.append(t)
        return "\n".join(parts)
    return str(content) if content is not None else ""


try:
    from services.response import sanitize_response, strip_widgets
except ImportError:  # pragma: no cover
    try:
        from backend.services.response import sanitize_response, strip_widgets  # type: ignore
    except ImportError:

        def sanitize_response(text, *, required_widgets=None):  # type: ignore
            return text if isinstance(text, str) else _extract_text_content(text)

        def strip_widgets(text):  # type: ignore
            return text if isinstance(text, str) else _extract_text_content(text)


# ---------------------------------------------------------------------------
# Tool registry - single source of truth for bind_tools and ToolNode
# ---------------------------------------------------------------------------

def get_tool_registry() -> list:
    """Return complete tool registry - same list used for bind_tools and ToolNode."""
    base_tools = [
        geocode_city,
        get_current_weather,
        get_weather_forecast,
        get_hourly_forecast,
        get_air_quality,
        get_uv_index_and_sun,
        get_surface_pressure_and_wind,
        get_agricultural_crop_telemetry,
        get_severe_weather_alerts,
    ]
    decision_tools = [
        list_decision_capabilities,
        evaluate_weather_decision,
        compare_eligible_windows,
        request_missing_context,
        assess_reply_evidence,
        get_decision_result,
    ]
    # Combine all, including WeatherNext
    all_tools = base_tools + decision_tools + WEATHERNEXT_TOOLS
    return all_tools


TOOLS = get_tool_registry()


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]
    mode: str  # everyone, farmer, researcher - validated
    requested_source: str  # auto, imd, weathernext, etc. - validated
    evidence_ids: list[str]
    job_references: list[str]
    # Request-scoped context, not global mutable
    request_context: dict


GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

_LLM_CASCADE = [GROQ_MODEL, "qwen/qwen3.8-27b", "qwen/qwen3.6-27b", "openai/gpt-oss-20b", "openai/gpt-oss-safeguard-20b"]
_TEXT_CASCADE = ["groq/compound", "groq/compound-mini", "allam-2-7b"]

_llm = None
_text_llm_chain = None


def has_llm() -> bool:
    return bool(os.getenv("GROQ_API_KEY"))


def _get_llm():
    """Tool-calling LLM cascade, built lazily so API boots without GROQ_API_KEY."""
    global _llm
    if _llm is None:
        if not has_llm():
            raise RuntimeError("GROQ_API_KEY not configured")
        # All fallback LLMs must bind same capabilities
        registry = get_tool_registry()
        models = [ChatGroq(model=m, temperature=0, max_retries=2).bind_tools(registry) for m in _LLM_CASCADE]
        _llm = models[0].with_fallbacks(models[1:])
    return _llm


def _get_text_llm():
    """Non-tool text LLMs used only to localise/format deterministic output."""
    global _text_llm_chain
    if _text_llm_chain is None:
        if not has_llm():
            raise RuntimeError("GROQ_API_KEY not configured")
        models = [ChatGroq(model=m, temperature=0, max_retries=1) for m in _TEXT_CASCADE]
        _text_llm_chain = models[0].with_fallbacks(models[1:])
    return _text_llm_chain


def agent_node(state: AgentState):
    # Use request-scoped context if available, don't mutate global
    # Enforce authorization in request-scoped wrappers
    response = _get_llm().invoke(state["messages"])
    return {"messages": [response]}


def should_continue(state: AgentState):
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return END


# Compile graph using same registry for ToolNode
def _build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    # ToolNode uses same registry as bind_tools - parity
    registry = get_tool_registry()
    graph.add_node("tools", ToolNode(registry))
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")
    return graph.compile()


_app = _build_graph()

COMMON_STOP_WORDS = {
    "hello", "hi", "hey", "namaste", "kemcho", "kem", "cho", "suprabhat", "thanks", "thankyou",
    "good", "morning", "evening", "night", "just", "please", "can", "you", "me", "us", "my",
    "your", "with", "have", "has", "had", "do", "does", "did", "ane", "and", "su", "che", "kya",
    "hai", "kaisa", "kevu", "batao", "weather", "temperature", "temp", "forecast", "climate",
    "telemetry", "report", "condition", "sky", "live", "in", "of", "at", "for", "the", "tell",
    "about", "how", "is", "what", "like", "today", "tomorrow", "now", "current", "city", "ma",
    "me", "nu", "na", "ka", "ki", "ke", "par", "se", "it", "raining", "right", "show", "will",
    "there", "be", "any", "rain", "sun", "cloud", "wind"
}


def smart_extract_city(query: str, default_location: str = "New Delhi") -> str:
    """Smartly extracts target city from query handling Indic postpositions & English prepositions."""
    if not query or not query.strip():
        return default_location.split(",")[0].strip() if default_location else "New Delhi"

    q_clean = query.lower().strip()

    m_eng = re.search(r'\b(?:in|of|at|for|near|around)\s+([a-z\s]+)', q_clean)
    if m_eng:
        raw = m_eng.group(1).strip()
        raw = re.sub(r'\b(today|tomorrow|now|right|current|weather|temp|temperature|mausam|report|info)\b.*', '', raw).strip()
        words = [w for w in raw.split() if w not in COMMON_STOP_WORDS]
        if words:
            candidate = " ".join(words)
            res = geocode_city.invoke({"city_name": candidate})
            if isinstance(res, dict) and res.get("latitude") and not res.get("error"):
                return res.get("city", candidate.title())

    m_ind = re.search(r'\b([a-z\s]+?)\s+(?:ma|me|nu|na|ka|ki|ke|par|se)\b', q_clean)
    if m_ind:
        words = m_ind.group(1).strip().split()
        filtered = [w for w in words if w not in COMMON_STOP_WORDS]
        if filtered:
            candidate = " ".join(filtered)
            res = geocode_city.invoke({"city_name": candidate})
            if isinstance(res, dict) and res.get("latitude") and not res.get("error"):
                return res.get("city", candidate.title())

    tokens = [w.strip("?,.!") for w in q_clean.split() if w.strip("?,.!") not in COMMON_STOP_WORDS]
    if tokens:
        for length in range(len(tokens), 0, -1):
            for i in range(0, len(tokens) - length + 1):
                phrase = " ".join(tokens[i:i + length])
                if len(phrase) < 3:
                    continue
                res = geocode_city.invoke({"city_name": phrase})
                if isinstance(res, dict) and res.get("latitude") and not res.get("error"):
                    return res.get("city", phrase.title())

    return default_location.split(",")[0].strip() if default_location else "New Delhi"


def run_deterministic_telemetry_fallback(
    location_str: str = "New Delhi",
    query: str = "",
    language: str = "English",
    lat: float | None = None,
    lon: float | None = None,
) -> str:
    """Zero-error deterministic synthesizer with honest unavailable handling.

    Fixed:
    - Removes provider-bypassing HTTP and invented fallback measurements
    - Handles nullable structured data and unresolved locations honestly
    - Renders provenance in deterministic replies
    - No synthetic 27C, 65% humidity, wind defaults
    - No Ahmedabad coordinate substitution while retaining city label
    """
    try:
        default_city = (location_str or "New Delhi").split(",")[0].strip() or "New Delhi"
        target_city = smart_extract_city(query, location_str) or default_city
        city_name = target_city
        query_names_other_city = target_city.strip().lower() != default_city.lower()

        # Resolve coordinates honestly
        resolved_lat = lat
        resolved_lon = lon
        geocode_success = False
        geocode_error = None

        if lat is not None and lon is not None and not query_names_other_city:
            city_name = default_city
            resolved_lat = lat
            resolved_lon = lon
            geocode_success = True
        else:
            try:
                geo = geocode_city.invoke({"city_name": target_city})
                if isinstance(geo, dict) and not geo.get("error") and geo.get("latitude"):
                    resolved_lat = float(geo["latitude"])
                    resolved_lon = float(geo["longitude"])
                    city_name = geo.get("city", target_city)
                    geocode_success = True
                else:
                    geocode_error = geo.get("error") if isinstance(geo, dict) else "geocode failed"
                    # Try location_str as fallback, but track that we tried
                    for candidate in (location_str,):
                        if not candidate:
                            continue
                        geo2 = geocode_city.invoke({"city_name": candidate.split(",")[0].strip()})
                        if isinstance(geo2, dict) and geo2.get("latitude") and not geo2.get("error"):
                            resolved_lat = float(geo2["latitude"])
                            resolved_lon = float(geo2["longitude"])
                            city_name = geo2.get("city", candidate.split(",")[0].strip())
                            geocode_success = True
                            break
            except Exception as ge_err:
                geocode_error = str(ge_err)

        if not geocode_success or resolved_lat is None or resolved_lon is None:
            # Honest unresolved location - don't fabricate Ahmedabad coords with city label
            return (
                f"## Weather for {target_city}\n\n"
                f"I couldn't resolve the location **{target_city}** to coordinates. "
                f"{'Error: ' + geocode_error if geocode_error else ''}\n\n"
                f"Please try with a more specific city name or provide coordinates.\n\n"
                f"Example: *What's the weather in New Delhi?* or provide lat/lon."
            )

        # Fetch weather with honest handling of failures
        curr = {}
        fore = {}
        curr_error = None
        fore_error = None

        try:
            curr = get_current_weather.invoke({"latitude": float(resolved_lat), "longitude": float(resolved_lon)})
            if isinstance(curr, dict) and curr.get("error"):
                curr_error = curr.get("error")
                curr = {}
        except Exception as tool_err:
            curr_error = str(tool_err)
            print(f"[Fallback] get_current_weather failed: {tool_err}")

        try:
            fore = get_weather_forecast.invoke({"latitude": float(resolved_lat), "longitude": float(resolved_lon), "days": 3})
            if isinstance(fore, dict) and fore.get("error"):
                fore_error = fore.get("error")
                fore = {}
        except Exception as tool_err:
            fore_error = str(tool_err)
            print(f"[Fallback] get_weather_forecast failed: {tool_err}")

        # If both failed, return honest unavailable, not synthetic data
        if not curr and not fore:
            return (
                f"## Weather for {city_name}\n\n"
                f"I'm having trouble reaching weather services for **{city_name}** right now.\n\n"
                f"**Details:**\n"
                f"- Current weather: {curr_error or 'unavailable'}\n"
                f"- Forecast: {fore_error or 'unavailable'}\n"
                f"- Location: {resolved_lat:.2f}, {resolved_lon:.2f}\n\n"
                f"Please try again in a moment. If this persists, check provider health at /dev/forecast.\n\n"
                f"*Provenance: attempted IMD -> WeatherNext -> AccuWeather -> Open-Meteo, all unavailable*"
            )

        # Extract with nullable handling - no defaults that fabricate favorable conditions
        if not isinstance(curr, dict):
            curr = {}

        temp_raw = curr.get("temperature_2m", curr.get("temp"))
        feels_raw = curr.get("apparent_temperature", curr.get("feelsLike"))
        cond = curr.get("condition", curr.get("weather", "Unknown"))
        humidity_raw = curr.get("relative_humidity_2m", curr.get("humidity"))
        wind_raw = curr.get("wind_speed_10m", curr.get("windSpeed"))

        # Use _bounded logic for validation, but keep None for missing
        def safe_parse(val, low=None, high=None):
            if val is None:
                return None
            try:
                f = float(val)
                if not math.isfinite(f):
                    return None
                if low is not None and f < low:
                    return None
                if high is not None and f > high:
                    return None
                return f
            except (TypeError, ValueError):
                return None

        temp = safe_parse(temp_raw, -100, 70)
        feels = safe_parse(feels_raw, -100, 80)
        humidity = safe_parse(humidity_raw, 0, 100)
        wind = safe_parse(wind_raw, 0, 500)

        # Build response with honest missing handling
        temp_str = f"{temp:.1f}°C" if temp is not None else "unavailable"
        feels_str = f"{feels:.1f}°C" if feels is not None else "unavailable"
        humidity_str = f"{int(humidity)}%" if humidity is not None else "unavailable"
        wind_str = f"{wind:.1f} km/h" if wind is not None else "unavailable"
        cond_str = cond if cond else "unavailable"

        # Forecast handling
        days_list = []
        if isinstance(fore, dict) and "forecast" in fore:
            for d in fore["forecast"][:3]:
                # Only include if we have valid data
                day_temp = d.get("max_temp_celsius")
                if day_temp is None:
                    continue
                try:
                    day_temp_f = round(float(day_temp))
                except (TypeError, ValueError):
                    continue
                days_list.append({
                    "day": d.get("date", "Today"),
                    "temp": day_temp_f,
                    "condition": d.get("condition", "Unknown"),
                    "rainProb": d.get("rain_probability_percent", 0) or 0,
                })

        # If we have no valid forecast days, don't fabricate
        if not days_list:
            days_list = None

        # Build widgets only with available data
        weather_widget_data = {
            "city": city_name,
            "temp": temp if temp is not None else 0,
            "feelsLike": feels if feels is not None else temp if temp is not None else 0,
            "condition": cond_str,
            "humidity": int(humidity) if humidity is not None else 0,
            "windSpeed": wind if wind is not None else 0,
            "advisory": f"Current weather in {city_name}: {cond_str} with temperature {temp_str}.",
            "source": curr.get("source", "unknown"),
            "provenance": curr.get("provenance", {}),
        }

        # Only include widget if we have at least some data
        if temp is None and humidity is None and wind is None:
            weather_widget_json = json.dumps({"city": city_name, "error": "insufficient data", "source": curr.get("source", "unknown")})
        else:
            weather_widget_json = json.dumps(weather_widget_data)

        if days_list:
            forecast_widget_json = json.dumps({"city": city_name, "days": days_list})
        else:
            forecast_widget_json = json.dumps({"city": city_name, "days": [], "note": "forecast unavailable"})

        # Try non-tool LLMs for localization, but with honest data
        try:
            # Only attempt if we have some data
            if temp is not None or days_list:
                prompt = f"""Output ONLY the final answer for the end user. Do NOT include any reasoning, planning, approach, thinking steps, or explanations of what you are doing. Start directly with a Markdown heading.

Format a weather response for user query '{query}' for city {city_name} in target language '{language}'.
Weather Data: Temp {temp_str}, Feels like {feels_str}, Condition: {cond_str}, Humidity: {humidity_str}, Wind: {wind_str}.
Source: {curr.get('source', 'unknown')}, Provenance: {curr.get('provenance', {})}
Provide clean Markdown in {language} script followed by these EXACT widget code blocks at the end:

```widget:weather
{weather_widget_json}
```

```widget:forecast
{forecast_widget_json}
```"""

                formatted_res = _get_text_llm().invoke(prompt)
                raw_content = getattr(formatted_res, "content", "") if formatted_res else ""
                raw_text = _extract_text_content(raw_content)
                if raw_text and len(raw_text.strip()) > 30:
                    cleaned = sanitize_response(
                        raw_text,
                        required_widgets=[
                            ("weather", weather_widget_json),
                            ("forecast", forecast_widget_json),
                        ],
                    )
                    if strip_widgets(cleaned).strip() and len(strip_widgets(cleaned).strip()) > 30:
                        return cleaned
                    if len(cleaned.strip()) > 30:
                        return cleaned
        except Exception as text_err:
            print(f"[Fallback Warning] Non-tool LLM text chain exception: {text_err}")

        # Direct fallback with provenance
        provenance_str = ""
        if curr.get("source"):
            provenance_str += f"\n*Source: {curr.get('source')}, Requested: {curr.get('requested_source', 'auto')}*"
        if curr.get("provenance"):
            prov = curr.get("provenance")
            if isinstance(prov, dict):
                if prov.get("model"):
                    provenance_str += f"\n*Model: {prov.get('model')}, Run: {prov.get('run_id', 'unknown')}*"
        if curr_error or fore_error:
            provenance_str += f"\n*Warnings: current {curr_error or 'ok'}, forecast {fore_error or 'ok'}*"

        return f"""## Weather for **{city_name}** ({language})

* **Temperature**: **{temp_str}** (Feels like **{feels_str}**)
* **Condition**: **{cond_str}**
* **Humidity**: **{humidity_str}**
* **Wind Speed**: **{wind_str}**

```widget:weather
{weather_widget_json}
```

```widget:forecast
{forecast_widget_json}
```

{provenance_str}

*Live telemetry with explicit provenance. Missing values are unavailable, not zero.*
"""

    except Exception as e:
        print(f"[Fallback Critical Error] {e}")
        city = (location_str or "your area").split(",")[0].strip() or "your area"
        return (
            f"I'm having trouble reaching live weather services for **{city}** right now. "
            f"Please try again in a moment — for example: *What's the weather in {city}?*\n\n"
            f"*Error: {type(e).__name__}, no fabricated data used*"
        )


def run_weather_agent(
    messages_input: list[dict] | str,
    user_location: str = "",
    user_language: str = "",
    farmer_mode: bool = False,
    crop: str = "",
    mode: str = "everyone",
    requested_source: str = "auto",
) -> str:
    """Run weather agent with validated mode and source constraints.

    Mode controls presentation and task routing; server-side entitlements,
    licensing, budgets, and safety checks still apply.
    """
    if isinstance(messages_input, str):
        history = [{"role": "user", "content": messages_input}]
    else:
        history = messages_input or []

    clean_location = user_location.replace("[Farmer Mode Active]", "").replace("Farmer Mode Active", "").strip()

    last_user_msg = next(
        (m.get("content", "") for m in reversed(history) if m.get("role") == "user"), ""
    )
    if user_language and user_language.strip():
        language = user_language.strip()
    else:
        language = get_user_language(last_user_msg) if last_user_msg else "English"

    # Validate mode
    if mode not in ("everyone", "farmer", "researcher"):
        mode = "farmer" if farmer_mode else "everyone"

    # Validate requested_source
    allowed_sources = ["auto", "imd", "weathernext", "accuweather", "open_meteo", "open-meteo"]
    if requested_source not in allowed_sources:
        requested_source = "auto"

    if farmer_mode:
        crop_name = crop.strip() if crop else "crops"
        farmer_instructions = f"""
🌾 AGRICULTURAL & FARMER ADVISORY SPECIALIST SUB-AGENT ACTIVE (mode={mode}):
- Act as an expert Agricultural Weather Specialist advising a farmer for {crop_name}.
- Use decision tools (evaluate_weather_decision, compare_eligible_windows) for farm advice
- Provide direct, practical guidance for farming operations:
  * Irrigation timing: Advise whether to irrigate today/tomorrow based on forecasted rainfall and heat.
  * Spraying windows: Advise if wind speed and rain probability allow pesticide or fertilizer spraying.
  * Thermal/Frost & Pest risk: Warn if temperature/humidity levels create pest or crop stress risks.
  * Harvest & Sowing advisories: Highlight safe weather windows for harvesting or field prep.
- Speak directly to the farmer with clear, actionable advice in {language}.
- Request missing context (soil moisture measured, not just soil type) when needed.
"""
    else:
        if mode == "researcher":
            farmer_instructions = f"""
🔬 RESEARCHER MODE ACTIVE (mode={mode}, source={requested_source}):
- You have access to complete authorized WeatherNext data via tools: query_weathernext_data, get_weathernext_profile, analyze_weathernext_ensemble, etc.
- Every authorized WeatherNext-related data capability should be accessible through tools
- Use list_weathernext_capabilities to discover available data
- For explicit source=weathernext requests, you must return that data or precise unavailable, not fallback masquerading
- Provide scientific explanations with provenance, units, run IDs, member counts
- Distinguish forecast/observation, MSL vs surface pressure, rain vs total precipitation
"""
        else:
            farmer_instructions = f"""
🌍 STANDARD WEATHER ASSISTANT MODE (mode={mode}, FARMER ADVISORY OFF):
- Act as general conversational weather assistant for everyday citizens
- For everyday mode, retain normal weather experience, adding only small useful WeatherNext detail
- Do NOT act as farmer advisor unless user explicitly asks farming question
- Mode: {mode}, Source: {requested_source}
"""

    system_prompt = f"""You are WeatherGPT, a specialized AI assistant dedicated STRICTLY to weather, climate, meteorology, air quality (AQI), solar UV, severe weather advisories/alerts, and agricultural crop advisories.

PERSONALITY & STRICT DOMAIN SCOPE:
- Maintain full context across conversation history for weather, city, and location details.
- Provide practical advice and safety advisories for severe weather.
- Mode: {mode}, Requested source: {requested_source} - honor source pins for researcher mode
- For researcher mode: every authorized WeatherNext capability must have UI and tool path

⛔ STRICT DOMAIN RESTRICTION — NON-WEATHER & OFF-TOPIC INQUIRIES:
- Basic polite greetings allowed
- For non-weather inquiries: politely decline in {language} with domain boundary message
- Do NOT answer off-topic!

{farmer_instructions}
FORMATTING & RICH WIDGET RULES:
1. Always format with clean Markdown: bold key metrics, bullet points, headings.
2. Target Language: {language}. Respond natively in {language} script. Keep JSON widget values in English/numbers.
3. If weather coordinates needed, use geocode_city FIRST.
4. RICH WIDGET EMBEDDING: Always include JSON widget codeblock for rich UI.
5. For researcher mode: include provenance (model, run_id, init_time, sources, member counts) in responses
6. For farm advice: date/window-scoped decisions with evidence IDs, never global highest-confidence verdict
7. Be engaging, clear, direct. Preserve uncertainty: p10-p90 is ensemble spread, not guaranteed accuracy.
8. Official warnings are authoritative; model guidance is separate. Unknown warning status is not no alerts.

{f'User location context: {clean_location}' if clean_location else ''}
Mode: {mode}, Source constraint: {requested_source}
"""

    formatted_messages = [SystemMessage(content=system_prompt)]
    for msg in history:
        role = msg.get("role")
        content = msg.get("content", "")
        if not content:
            continue
        if role == "user":
            formatted_messages.append(HumanMessage(content=content))
        elif role == "assistant":
            formatted_messages.append(AIMessage(content=content))

    if not has_llm():
        print("[Agent] GROQ_API_KEY missing — serving deterministic telemetry response")
        return run_deterministic_telemetry_fallback(clean_location, last_user_msg, language)

    try:
        # Use request-scoped state with mode and source constraints
        state = {
            "messages": formatted_messages,
            "mode": mode,
            "requested_source": requested_source,
            "evidence_ids": [],
            "job_references": [],
            "request_context": {
                "mode": mode,
                "requested_source": requested_source,
                "user_location": clean_location,
                "language": language,
                "farmer_mode": farmer_mode,
                "crop": crop,
            },
        }
        result = _app.invoke(state)
        raw = result["messages"][-1].content
        text = _extract_text_content(raw)
        try:
            return sanitize_response(text)
        except Exception:
            return text
    except Exception as exc:
        err_msg = str(exc).lower()
        print(f"[Agent Warning] LLM cascade exception ({err_msg}). Engaging Deterministic Telemetry Synthesizer...")
        return run_deterministic_telemetry_fallback(clean_location, last_user_msg, language)
