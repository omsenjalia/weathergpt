import os
import operator
from typing import Annotated, Sequence, TypedDict

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
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

llm = ChatGroq(model=GROQ_MODEL, temperature=0).bind_tools(TOOLS)


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


def run_weather_agent(user_message: str, user_location: str = "") -> str:
    language = get_user_language(user_message)

    system_prompt = f"""You are WeatherGPT, an AI weather assistant specializing in weather across India.

IMPORTANT RULES:
1. Always call geocode_city FIRST to get coordinates before calling any weather tool.
2. Respond in {language} language. Match the user's language exactly (English or any Indian language). Preserve the native script (Devanagari, Tamil, Telugu, Bengali, etc.).
3. Format your response using Markdown: use **bold** for key values, bullet lists and tables for multiple data points, and ## headings for sections. This makes it render nicely in the chat UI.
4. Always include safety advisories for severe weather (thunderstorms, heavy rain, extreme heat).
5. Provide practical advice like carrying an umbrella, staying hydrated, etc.
6. Be conversational and friendly.
7. Format temperatures clearly with units.
8. If a city is not found, ask the user to clarify or suggest nearby cities.

{f'User location context: {user_location}' if user_location else ''}
"""

    messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_message)]
    result = _app.invoke({"messages": messages})
    return result["messages"][-1].content
