"""The LangGraph agent wiring, with ChatGroq replaced by a scripted model.

Guards the langgraph / langchain-core API surface the agent uses (StateGraph,
ToolNode, bind_tools, with_fallbacks, @tool) across dependency upgrades.
"""

from __future__ import annotations

import pytest

pytest.importorskip("langgraph")

import langchain_groq  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402
from langchain_core.runnables import RunnableLambda  # noqa: E402

from weathergpt import geo  # noqa: E402
from weathergpt.ai import agent  # noqa: E402


class ScriptedGroq:
    """First turn asks for geocode_place; once the tool result is in, answers from it."""

    seen: list = []

    def __init__(self, model: str, **_kwargs) -> None:
        self.model = model

    def bind_tools(self, tools):
        assert {t.name for t in tools} >= {"geocode_place", "get_weather"}

        def reply(messages):
            ScriptedGroq.seen.append([m.type for m in messages])
            tool_results = [m for m in messages if m.type == "tool"]
            if not tool_results:
                return AIMessage(content="", tool_calls=[{"name": "geocode_place", "args": {"name": "Pune"},
                                                          "id": "call_1", "type": "tool_call"}])
            return AIMessage(content=f"Found it: {tool_results[-1].content}")

        return RunnableLambda(reply)


@pytest.fixture
def scripted(monkeypatch):
    ScriptedGroq.seen = []
    monkeypatch.setattr(langchain_groq, "ChatGroq", ScriptedGroq)
    monkeypatch.setattr(geo, "geocode", lambda name: {"name": name, "latitude": 18.52, "longitude": 73.86})
    agent.reset()
    yield
    agent.reset()


def test_agent_runs_a_tool_call_and_answers(scripted):
    answer = agent.run("You are a weather assistant.", [{"role": "user", "content": "weather in Pune?"}])

    assert answer.startswith("Found it:")
    assert "18.52" in answer and "Pune" in answer
    assert ScriptedGroq.seen == [["system", "human"], ["system", "human", "ai", "tool"]]


def test_agent_keeps_recent_history_only(scripted):
    history = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"} for i in range(20)]
    agent.run("sys", history)

    assert len(ScriptedGroq.seen[0]) == 1 + 12
