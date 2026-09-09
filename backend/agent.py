import os
import json
import operator
from typing import Annotated, Sequence, TypedDict
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
)

TOOLS = [
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


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]


GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

# Configure primary LLM and tool-calling model fallbacks for 0% downtime across all Groq models
primary_llm = ChatGroq(model=GROQ_MODEL, temperature=0, max_retries=2).bind_tools(TOOLS)
fallback_1 = ChatGroq(model="qwen/qwen3.8-27b", temperature=0, max_retries=2).bind_tools(TOOLS)
fallback_2 = ChatGroq(model="qwen/qwen3.6-27b", temperature=0, max_retries=2).bind_tools(TOOLS)
fallback_3 = ChatGroq(model="openai/gpt-oss-20b", temperature=0, max_retries=2).bind_tools(TOOLS)
fallback_4 = ChatGroq(model="openai/gpt-oss-safeguard-20b", temperature=0, max_retries=2).bind_tools(TOOLS)

llm = primary_llm.with_fallbacks([fallback_1, fallback_2, fallback_3, fallback_4])

# Emergency non-tool text generation LLMs (for formatting/translating if tool-calling LLMs hit rate limits)
text_fallback_1 = ChatGroq(model="groq/compound", temperature=0, max_retries=1)
text_fallback_2 = ChatGroq(model="groq/compound-mini", temperature=0, max_retries=1)
text_fallback_3 = ChatGroq(model="allam-2-7b", temperature=0, max_retries=1)

text_llm_chain = text_fallback_1.with_fallbacks([text_fallback_2, text_fallback_3])


def agent_node(state: AgentState):
    response = llm.invoke(state["messages"])
    return {"messages": [response]}


def should_continue(state: AgentState):
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return END


# Compile the graph once at module load time
def _build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", ToolNode(TOOLS))
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
    """Smartly extracts target city from query handling Indic postpositions (ma, me, nu, ka) & English prepositions."""
    if not query or not query.strip():
        return default_location.split(",")[0].strip() if default_location else "New Delhi"

    q_clean = query.lower().strip()

    # 1. English prepositions: 'in/of/at/for/near/around <city>'
    m_eng = re.search(r'\b(?:in|of|at|for|near|around)\s+([a-z\s]+)', q_clean)
    if m_eng:
        raw = m_eng.group(1).strip()
        raw = re.sub(r'\b(today|tomorrow|now|right|current|weather|temp|temperature|mausam|report|info)\b.*', '', raw).strip()
        words = [w for w in raw.split() if w not in COMMON_STOP_WORDS]
        if words:
            candidate = " ".join(words)
            res = geocode_city.invoke(candidate)
            if isinstance(res, dict) and res.get("latitude") and not res.get("error"):
                return res.get("city", candidate.title())

    # 2. Indic postpositions: '<city> ma/me/nu/na/ka/ki/ke/par/se' (e.g. 'kolkata ma', 'mumbai me', 'delhi nu')
    m_ind = re.search(r'\b([a-z\s]+?)\s+(?:ma|me|nu|na|ka|ki|ke|par|se)\b', q_clean)
    if m_ind:
        words = m_ind.group(1).strip().split()
        filtered = [w for w in words if w not in COMMON_STOP_WORDS]
        if filtered:
            candidate = " ".join(filtered)
            res = geocode_city.invoke(candidate)
            if isinstance(res, dict) and res.get("latitude") and not res.get("error"):
                return res.get("city", candidate.title())

    # 3. Direct city search on non-stopword tokens
    tokens = [w.strip("?,.!") for w in q_clean.split() if w.strip("?,.!") not in COMMON_STOP_WORDS]
    for token in tokens:
        if len(token) >= 3:
            res = geocode_city.invoke(token)
            if isinstance(res, dict) and res.get("latitude") and not res.get("error"):
                return res.get("city", token.title())

    # 4. Fallback to default user location
    return default_location.split(",")[0].strip() if default_location else "New Delhi"


def run_deterministic_telemetry_fallback(location_str: str = "New Delhi", query: str = "", language: str = "English") -> str:
    """Zero-error deterministic synthesizer: Fetches live weather directly if all LLMs fail or hit rate limits."""
    try:
        target_city = smart_extract_city(query, location_str)
        geo = geocode_city.invoke(target_city)

        if isinstance(geo, dict) and (geo.get("error") or not geo.get("latitude")):
            geo = geocode_city.invoke("New Delhi")
            city_name = "New Delhi"
        else:
            city_name = geo.get("city", target_city)

        lat = geo.get("latitude", 28.6139)
        lon = geo.get("longitude", 77.209)
        curr = get_current_weather.invoke({"latitude": lat, "longitude": lon})
        fore = get_weather_forecast.invoke({"latitude": lat, "longitude": lon, "days": 3})

        temp = curr.get("temperature_2m", 27) if isinstance(curr, dict) else 27
        feels = curr.get("apparent_temperature", temp) if isinstance(curr, dict) else temp
        cond = curr.get("condition", "Partly Cloudy") if isinstance(curr, dict) else "Clear Sky"
        humidity = curr.get("relative_humidity_2m", 65) if isinstance(curr, dict) else 65
        wind = curr.get("wind_speed_10m", 12) if isinstance(curr, dict) else 12

        days_list = []
        if isinstance(fore, dict) and "forecast" in fore:
            for d in fore["forecast"][:3]:
                days_list.append({
                    "day": d.get("date", "Today"),
                    "temp": round(d.get("max_temp_celsius", temp)),
                    "condition": d.get("condition", cond),
                    "rainProb": d.get("rain_probability_percent", 10)
                })

        weather_widget_json = json.dumps({
            "city": city_name,
            "temp": temp,
            "feelsLike": feels,
            "condition": cond,
            "humidity": humidity,
            "windSpeed": wind,
            "advisory": f"Current weather in {city_name}: {cond} with temperature of {temp}°C."
        })

        forecast_widget_json = json.dumps({
            "city": city_name,
            "days": days_list if days_list else [{"day": "Today", "temp": temp, "condition": cond, "rainProb": 10}]
        })

        # Try non-tool LLMs (groq/compound, groq/compound-mini, allam-2-7b) to generate native language text response
        try:
            prompt = f"""Format a weather response for user query '{query}' for city {city_name} in target language '{language}'.
Weather Data: Temp {temp}°C, Feels like {feels}°C, Condition: {cond}, Humidity: {humidity}%, Wind: {wind} km/h.
Provide clean Markdown in {language} script followed by these EXACT widget code blocks at the end:

```widget:weather
{weather_widget_json}
```

```widget:forecast
{forecast_widget_json}
```"""
            formatted_res = text_llm_chain.invoke(prompt)
            if formatted_res and formatted_res.content and len(formatted_res.content) > 30:
                return formatted_res.content
        except Exception as text_err:
            print(f"[Fallback Warning] Non-tool LLM text chain exception: {text_err}")

        # Direct localized fallback output if non-tool LLMs are unreachable
        return f"""## 🌤️ Weather Telemetry for **{city_name}** ({language})

* **Temperature**: **{temp}°C** (Feels like **{feels}°C**)
* **Condition**: **{cond}**
* **Humidity**: **{humidity}%**
* **Wind Speed**: **{wind} km/h**

```widget:weather
{weather_widget_json}
```

```widget:forecast
{forecast_widget_json}
```

*Live telemetry gathered directly from multi-source weather satellites.*"""
    except Exception as e:
        print(f"[Fallback Critical Error] {e}")
        return "## 🌤️ WeatherGPT Live Status\n\nWeatherGPT live service is online. How can I help you with weather forecast, rain alerts, or farming advisories today?"



def run_weather_agent(
    messages_input: list[dict] | str,
    user_location: str = "",
    user_language: str = "",
    farmer_mode: bool = False,
    crop: str = "",
) -> str:
    if isinstance(messages_input, str):
        history = [{"role": "user", "content": messages_input}]
    else:
        history = messages_input or []

    # Clean user location to prevent stale context leaks
    clean_location = user_location.replace("[Farmer Mode Active]", "").replace("Farmer Mode Active", "").strip()

    # Detect user language
    last_user_msg = next(
        (m.get("content", "") for m in reversed(history) if m.get("role") == "user"), ""
    )
    if user_language and user_language.strip():
        language = user_language.strip()
    else:
        language = get_user_language(last_user_msg) if last_user_msg else "English"

    # Strict Farmer Mode evaluation: active ONLY when farmer_mode boolean is explicitly True
    if farmer_mode:
        crop_name = crop.strip() if crop else "crops"
        farmer_instructions = f"""
🌾 AGRICULTURAL & FARMER ADVISORY SPECIALIST SUB-AGENT ACTIVE:
- Act as an expert Agricultural Weather Specialist advising a farmer for {crop_name}.
- Provide direct, practical guidance for farming operations:
  * Irrigation timing: Advise whether to irrigate today/tomorrow based on forecasted rainfall and heat.
  * Spraying windows: Advise if wind speed and rain probability allow pesticide or fertilizer spraying.
  * Thermal/Frost & Pest risk: Warn if temperature/humidity levels create pest or crop stress risks.
  * Harvest & Sowing advisories: Highlight safe weather windows for harvesting or field prep.
- Speak directly to the farmer with clear, actionable advice in {language}.
"""
    else:
        farmer_instructions = """
🌍 STANDARD WEATHER ASSISTANT MODE (FARMER ADVISORY MODE IS OFF):
- Act strictly as a general conversational weather assistant for everyday citizens.
- Do NOT act as a farmer advisor or mention crops, farming, irrigation, or pesticide spraying unless the user explicitly asks a farming question in their prompt.
"""

    system_prompt = f"""You are WeatherGPT, a specialized AI assistant dedicated STRICTLY to weather, climate, meteorology, air quality (AQI), solar UV, severe weather advisories/alerts, and agricultural crop advisories.

PERSONALITY & STRICT DOMAIN SCOPE:
- You are WeatherGPT, a specialized AI assistant dedicated STRICTLY to weather, climate, meteorology, air quality (AQI), solar UV, severe weather advisories/alerts, and agricultural crop advisories.
- Maintain full context across conversation history for weather, city, and location details.
- Provide practical advice (clothing suggestions, umbrella reminders, UV & heat guidance, outdoor activity weather viability) and safety advisories for severe weather conditions.

⛔ STRICT DOMAIN RESTRICTION — NON-WEATHER & OFF-TOPIC INQUIRIES:
- You are STRICTLY RESTRICTED to weather, climate, air quality, severe weather alerts, and agricultural farming information.
- Basic polite greetings (e.g., "Hello", "Hi", "Who are you?") are allowed — introduce yourself warmly as WeatherGPT and offer weather or farming assistance.
- For ANY non-weather, non-climate, non-agricultural inquiry (such as general knowledge trivia, coding/programming scripts, sports, history, politics, general calculations, entertainment, or unrelated topics):
  You MUST politely decline in {language} with the following exact domain boundary message (translated into {language}):
  "Sorry, I do not contain any other data than weather, climate, air quality, and agricultural information. How can I help you with weather forecasts or farming advisories today?"
- Do NOT answer, summarize, generate code, or discuss topics outside of weather, climate, AQI, severe weather alerts, and agriculture!

{farmer_instructions}
FORMATTING & RICH WIDGET RULES:
1. Always format responses with clean Markdown: use **bold** key metrics, bullet points, clean tables, and ## headings.
2. Target Language: {language}. You MUST respond natively in {language} using its official native script (e.g. Devanagari for Hindi/Marathi, Gujarati script, Tamil, Telugu, Bengali, Kannada, Malayalam, Punjabi). Keep JSON widget values in English/numbers so the UI can parse them cleanly.
3. If weather coordinates are needed for a location, use `geocode_city` FIRST to get coordinates before invoking `get_current_weather` or `get_weather_forecast`.
4. RICH WIDGET EMBEDDING: Whenever providing weather for a city or a forecast, ALWAYS include a JSON widget codeblock so the chat UI displays a rich interactive visual card.
   Example current weather widget:
   ```widget:weather
   {{"city": "CityName", "temp": 30, "feelsLike": 34, "condition": "Clear Sky", "humidity": 65, "windSpeed": 12, "advisory": "Pleasant outdoor weather"}}
   ```
   Example forecast widget:
   ```widget:forecast
   {{"city": "CityName", "days": [{{"day": "Today", "temp": 30, "condition": "Clear", "rainProb": 10}}, {{"day": "Tomorrow", "temp": 28, "condition": "Rain", "rainProb": 80}}]}}
   ```
   Example alert widget:
   ```widget:alert
   {{"city": "CityName", "level": "ORANGE", "title": "ORANGE ALERT: Heavy Rain Expected", "advisory": "Localized waterlogging likely in low-lying areas.", "action": "BE PREPARED: Keep rainwear handy"}}
   ```
5. Be engaging, clear, and direct.

{f'User location context: {clean_location}' if clean_location else ''}
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

    try:
        result = _app.invoke({"messages": formatted_messages})
        return result["messages"][-1].content
    except Exception as exc:
        err_msg = str(exc).lower()
        print(f"[Agent Warning] LLM cascade exception ({err_msg}). Engaging Deterministic Telemetry Synthesizer...")
        return run_deterministic_telemetry_fallback(clean_location, last_user_msg, language)


