import os
import operator
from typing import Annotated, Sequence, TypedDict
from dotenv import load_dotenv

load_dotenv()

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from tools import geocode_city, get_current_weather, get_weather_forecast, get_user_language

TOOLS = [geocode_city, get_current_weather, get_weather_forecast]


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]


# NOTE: Model name must be one your Groq account has access to. Check yours with:
#   curl https://api.groq.com/openai/v1/models -H "Authorization: Bearer $GROQ_API_KEY"
# `llama-3.3-70b-versatile` was removed from free accounts in 2026.
# Qwen3 models have native support for 119 languages/dialects, including
# Hindi, Tamil, Telugu, Kannada, Malayalam, Bengali, Punjabi, Marathi, Gujarati,
# Oriya, Assamese, etc. — ideal for a multilingual India weather assistant.
GROQ_MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")

# Configure primary LLM and fallbacks to handle 429 Rate Limits gracefully
primary_llm = ChatGroq(model=GROQ_MODEL, temperature=0, max_retries=3).bind_tools(TOOLS)
fallback_1 = ChatGroq(model="llama-3.1-8b-instant", temperature=0, max_retries=3).bind_tools(TOOLS)
fallback_2 = ChatGroq(model="llama-3.3-70b-versatile", temperature=0, max_retries=3).bind_tools(TOOLS)
fallback_3 = ChatGroq(model="mixtral-8x7b-32768", temperature=0, max_retries=3).bind_tools(TOOLS)

llm = primary_llm.with_fallbacks([fallback_1, fallback_2, fallback_3])


def agent_node(state: AgentState):
    response = llm.invoke(state["messages"])
    return {"messages": [response]}


def should_continue(state: AgentState):
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return END


# Compile the graph once at module load time rather than rebuilding it on
# every request. Compilation is expensive and the graph structure never
# changes between calls.
def _build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", ToolNode(TOOLS))
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")
    return graph.compile()


_app = _build_graph()


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

    # If farmer_mode or crop passed in user_location context string
    if "[Farmer Mode" in user_location or "Farmer Mode" in user_location:
        farmer_mode = True

    # If user_language passed explicitly, use it; otherwise detect from text
    if user_language and user_language.strip():
        language = user_language.strip()
    else:
        last_user_msg = next(
            (m.get("content", "") for m in reversed(history) if m.get("role") == "user"), ""
        )
        language = get_user_language(last_user_msg) if last_user_msg else "English"

    farmer_instructions = ""
    if farmer_mode or crop:
        crop_name = crop.strip() if crop else "crops"
        farmer_instructions = f"""
🌾 AGRICULTURAL & FARMER ADVISORY MODE ACTIVE:
- Act as an expert Agricultural Weather Specialist advising a farmer for {crop_name}.
- Provide direct, practical guidance for farming operations:
  * Irrigation timing: Advise whether to irrigate today/tomorrow based on forecasted rainfall and heat.
  * Spraying windows: Advise if wind speed and rain probability allow pesticide or fertilizer spraying.
  * Thermal/Frost & Pest risk: Warn if temperature/humidity levels create pest or crop stress risks.
  * Harvest & Sowing advisories: Highlight safe weather windows for harvesting or field prep.
- Speak directly to the farmer with clear, actionable advice in {language}.
"""

    system_prompt = f"""You are WeatherGPT, a highly intelligent, friendly, and helpful AI weather assistant designed to give a seamless experience like Google Gemini.

PERSONALITY & BEHAVIOR:
- Warm, conversational, clear, and proactive — like chatting with Gemini.
- Maintain full context across the entire conversation history (e.g. remember city names, locations, dates, or travel plans discussed earlier in the chat).
- Provide practical advice (clothing suggestions, umbrella reminders, UV & heat guidance, outdoor activity viability) and safety advisories for severe weather conditions.
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

{f'User location context: {user_location}' if user_location else ''}
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
        if "429" in err_msg or "rate_limit" in err_msg or "too many requests" in err_msg:
            # Fall back to high-capacity instant model if primary model rate limits
            try:
                fast_llm = ChatGroq(model="llama-3.1-8b-instant", temperature=0).bind_tools(TOOLS)
                res = fast_llm.invoke(formatted_messages)
                return res.content
            except Exception:
                return "The WeatherGPT AI service is experiencing high traffic right now. Please wait a few seconds and try again."
        raise exc
