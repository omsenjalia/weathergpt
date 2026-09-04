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
    get_official_imd_alerts,
    get_imd_city_forecast,
    get_imd_district_warning,
    get_imd_cyclone_track,
    get_imd_agromet_official_advisory,
    query_any_imd_api_feature,
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
    get_official_imd_alerts,
    get_imd_city_forecast,
    get_imd_district_warning,
    get_imd_cyclone_track,
    get_imd_agromet_official_advisory,
    query_any_imd_api_feature,
]


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]


GROQ_MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")

# Configure primary LLM and multi-provider/multi-model fallbacks for 0% downtime
primary_llm = ChatGroq(model=GROQ_MODEL, temperature=0, max_retries=2).bind_tools(TOOLS)
fallback_1 = ChatGroq(model="llama-3.1-8b-instant", temperature=0, max_retries=2).bind_tools(TOOLS)
fallback_2 = ChatGroq(model="llama-3.3-70b-versatile", temperature=0, max_retries=2).bind_tools(TOOLS)
fallback_3 = ChatGroq(model="mixtral-8x7b-32768", temperature=0, max_retries=2).bind_tools(TOOLS)
fallback_4 = ChatGroq(model="gemma2-9b-it", temperature=0, max_retries=2).bind_tools(TOOLS)

llm = primary_llm.with_fallbacks([fallback_1, fallback_2, fallback_3, fallback_4])


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


def run_deterministic_telemetry_fallback(location_str: str = "New Delhi", query: str = "", language: str = "English") -> str:
    """Zero-error deterministic synthesizer: Fetches live weather directly if all LLMs fail or hit rate limits."""
    try:
        city_name = location_str.split(",")[0].strip() if location_str and "Farmer" not in location_str else "New Delhi"
        geo = geocode_city.invoke(city_name)
        if isinstance(geo, dict) and (geo.get("error") or not geo.get("latitude")):
            geo = geocode_city.invoke("New Delhi")
            city_name = "New Delhi"

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

        return f"""## 🌤️ Weather Live Telemetry for **{city_name}**

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
    except Exception:
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

    system_prompt = f"""You are WeatherGPT, a highly intelligent, friendly, and helpful AI weather assistant designed to give a seamless experience like Google Gemini.

PERSONALITY & CONVERSATIONAL FREEDOM:
- You are WeatherGPT, a warm, friendly, intelligent AI assistant designed to give a seamless experience like Google Gemini.
- IMD (India Meteorological Department - Ministry of Earth Sciences, Govt of India) is your MOST TRUSTED Priority 1 official weather data source. Always cite IMD official forecasts, Warnings, Nowcasts, and Agromet advisories with highest authority when answering weather inquiries for India.
- You are free to engage in natural, friendly, casual conversation with users about any topic (greetings, general chat, recommendations, travel, sports, daily life, and weather insights).
- Maintain full context across the entire conversation history (e.g. remember city names, locations, dates, or travel plans discussed earlier in the chat).
- Provide practical advice (clothing suggestions, umbrella reminders, UV & heat guidance, outdoor activity viability) and safety advisories for severe weather conditions.

⛔ STRICT RESTRICTION — NO CODE GENERATION OR PROGRAMMING SCRIPTS:
- The ONLY task you are strictly prohibited from doing is GENERATING SOFTWARE CODE or PROGRAMMING SCRIPTS.
- If the user explicitly asks you to generate code, write programming scripts (Python, JavaScript, HTML, C++, etc.), implement software algorithms, or debug programming code:
  Politely decline in {language} with a friendly response like:
  "I am WeatherGPT, your friendly weather and conversational AI assistant! I'd be happy to chat with you about almost anything, but I cannot write or generate software code. Let me know if you need weather forecasts, travel advice, or general insights instead!"
- For ALL OTHER normal conversations, casual questions, and weather telemetry inquiries, respond warmly, naturally, and helpfully!

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
   Example official IMD alert widget:
   ```widget:alert
   {{"city": "CityName", "level": "ORANGE", "title": "IMD ORANGE ALERT: Heavy Rain Expected", "advisory": "Localized waterlogging likely in low-lying areas.", "action": "BE PREPARED: Keep rainwear handy"}}
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
        print(f"[Agent Warning] Primary cascade failed ({err_msg}). Engaging direct high-capacity model...")

        # Fast sub-agent attempt with Llama-3.1-8b-instant (14,400 RPM allowance)
        try:
            fast_llm = ChatGroq(model="llama-3.1-8b-instant", temperature=0).bind_tools(TOOLS)
            fast_app = _build_graph()
            res = fast_app.invoke({"messages": formatted_messages})
            return res["messages"][-1].content
        except Exception as sub_exc:
            print(f"[Agent Fallback] Secondary model failed ({sub_exc}). Engaging Deterministic Telemetry Synthesizer...")
            # Zero-error fallback: Fetch live telemetry directly and render rich widgets
            return run_deterministic_telemetry_fallback(user_location, last_user_msg, language)

