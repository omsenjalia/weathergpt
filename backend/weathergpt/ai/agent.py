"""LangGraph tool-calling agent on Groq, with a model cascade.

The orchestrator (``weathergpt.ai.chat``) pre-fetches live evidence and passes it
in the system prompt, so most answers need no tool call; tools cover follow-ups
(another place, hourly detail, history, raw IMD products).
"""

from __future__ import annotations

import operator
import threading
from typing import Annotated, Sequence, TypedDict

from weathergpt.config import settings

_graph = None
_lock = threading.Lock()


class AgentState(TypedDict):
    messages: Annotated[Sequence, operator.add]


def models() -> list[str]:
    cfg = settings()
    return [cfg.groq_model] + [m for m in cfg.groq_fallback_models if m != cfg.groq_model]


def _build():
    from langchain_groq import ChatGroq
    from langgraph.graph import END, StateGraph
    from langgraph.prebuilt import ToolNode

    from weathergpt.ai.tools import TOOLS

    chain = [ChatGroq(model=m, temperature=0.2, max_retries=1, api_key=settings().groq_api_key).bind_tools(TOOLS)
             for m in models()]
    llm = chain[0].with_fallbacks(chain[1:]) if len(chain) > 1 else chain[0]

    def agent(state: AgentState):
        return {"messages": [llm.invoke(state["messages"])]}

    def route(state: AgentState):
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) else END

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent)
    graph.add_node("tools", ToolNode(TOOLS))
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", route, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")
    return graph.compile()


def graph():
    global _graph
    with _lock:
        if _graph is None:
            _graph = _build()
        return _graph


def reset() -> None:
    global _graph
    with _lock:
        _graph = None


def text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, str):
                parts.append(p)
            elif isinstance(p, dict) and isinstance(p.get("text"), str):
                parts.append(p["text"])
        return "\n".join(parts)
    return str(content or "")


def run(system_prompt: str, history: list[dict], *, max_steps: int = 8) -> str:
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    messages = [SystemMessage(content=system_prompt)]
    for m in history[-12:]:
        content = str(m.get("content") or "").strip()
        if not content:
            continue
        messages.append(HumanMessage(content=content) if m.get("role") == "user" else AIMessage(content=content))
    result = graph().invoke({"messages": messages}, config={"recursion_limit": max_steps * 2 + 1})
    return text_of(result["messages"][-1].content)


def translate(markdown: str, language: str, *, timeout: float = 8.0) -> str:
    """Localise a deterministic answer (numbers, units and widget blocks unchanged)."""
    from langchain_groq import ChatGroq

    cfg = settings()
    llm = ChatGroq(model=cfg.groq_model, temperature=0, max_retries=0, timeout=timeout, api_key=cfg.groq_api_key)
    prompt = (f"Translate this weather answer into {language} using its native script. Keep Markdown formatting, "
              "every number and unit, and any ```widget:...``` blocks exactly as they are. Output only the "
              f"translation.\n\n{markdown}")
    return text_of(llm.invoke(prompt).content)
