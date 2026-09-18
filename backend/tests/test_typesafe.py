"""Offline tests for the TypeSafe System One client and its chat-routing hook."""

import os
import sys

import httpx
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services import typesafe  # noqa: E402


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _ok_body(**overrides):
    body = {
        "model": "jev-latest",
        "answers": {
            "route": {
                "type": "choice",
                "choice": "rain_probability",
                "probabilities": {"rain_probability": 0.9, "greeting": 0.1},
                "confidence": 0.88,
            },
            "live_data": {"type": "noul", "noul": 0.93},
            "smalltalk": {"type": "noul", "noul": 0.02},
        },
        "usage": {"input_tokens": 40, "output_tokens": 12},
    }
    body.update(overrides)
    return body


def _queue_client(handler_calls: list, responses: list, status_code: int = 200):
    """Monkeypatch typesafe._client_factory with a MockTransport replaying responses."""

    def handler(request: httpx.Request) -> httpx.Response:
        handler_calls.append(dict(request.headers, url=str(request.url)))
        action = responses.pop(0) if responses else {"status": 500}
        if isinstance(action, dict) and action.get("type") == "error":
            raise httpx.ConnectError("boom", request=request)
        status = action.get("status", status_code) if isinstance(action, dict) else status_code
        payload = action.get("body") if isinstance(action, dict) else None
        return httpx.Response(status, json=payload if payload is not None else {})

    def factory(timeout: float) -> httpx.Client:
        return httpx.Client(
            base_url="https://mock.typesafe.test/v1",
            transport=httpx.MockTransport(handler),
        )

    return factory


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "tsk_test_key")
    monkeypatch.delenv("TYPESAFE_ENABLED", raising=False)
    monkeypatch.delenv("TYPESAFE_MAX_ATTEMPTS", raising=False)
    monkeypatch.delenv("TYPESAFE_RETRY_BACKOFF_SECONDS", raising=False)
    monkeypatch.setattr(typesafe, "_client_factory", typesafe._default_client)


# --------------------------------------------------------------------------- #
# Client behaviour
# --------------------------------------------------------------------------- #
def test_disabled_without_key(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    assert typesafe.is_enabled() is False


def test_placeholder_key_is_disabled(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "your_typesafe_api_key_here")
    assert typesafe.is_enabled() is False


def test_enabled_false_hard_disables(monkeypatch):
    monkeypatch.setenv("TYPESAFE_ENABLED", "0")
    assert typesafe.is_enabled() is False
    assert typesafe.evaluate("state", {"a": typesafe.noul("x")}) is None


def test_evaluate_success_and_accessors(monkeypatch):
    calls: list = []
    factory = _queue_client(calls, [{"status": 200, "body": _ok_body()}])
    monkeypatch.setattr(typesafe, "_client_factory", factory)

    result = typesafe.evaluate("hello", {"route": typesafe.choice("pick", {"a": "b"})})
    assert result is not None
    assert result["answers"]["route"]["choice"] == "rain_probability"
    assert result["model"] == "jev-latest"
    assert result["attempts"] == 1
    assert typesafe.choice_of(result["answers"], "route") == "rain_probability"
    assert typesafe.confidence_of(result["answers"], "route") == 0.88
    assert typesafe.noul_of(result["answers"], "live_data") == 0.93
    assert typesafe.probabilities_of(result["answers"], "route")["rain_probability"] == 0.9
    assert typesafe.score_of(result["answers"], "route") is None  # wrong primitive


def test_evaluate_retries_on_503_then_succeeds(monkeypatch):
    calls: list = []
    factory = _queue_client(
        calls, [{"status": 503}, {"status": 200, "body": _ok_body()}]
    )
    monkeypatch.setattr(typesafe, "_client_factory", factory)
    monkeypatch.setenv("TYPESAFE_RETRY_BACKOFF_SECONDS", "0")

    result = typesafe.evaluate("hello", {"a": typesafe.noul("x")})
    assert result is not None
    assert result["attempts"] == 2
    assert len(calls) == 2


def test_evaluate_fails_fast_on_400(monkeypatch):
    calls: list = []
    factory = _queue_client(calls, [{"status": 400}])
    monkeypatch.setattr(typesafe, "_client_factory", factory)

    assert typesafe.evaluate("hello", {"a": typesafe.noul("x")}) is None
    assert len(calls) == 1  # no retry on non-retryable client errors


def test_evaluate_gives_up_after_attempts(monkeypatch):
    calls: list = []
    factory = _queue_client(calls, [{"status": 500}, {"status": 500}, {"status": 500}])
    monkeypatch.setattr(typesafe, "_client_factory", factory)
    monkeypatch.setenv("TYPESAFE_RETRY_BACKOFF_SECONDS", "0")

    assert typesafe.evaluate("hello", {"a": typesafe.noul("x")}) is None
    assert len(calls) == 3


def test_evaluate_requires_state_and_questions(monkeypatch):
    assert typesafe.evaluate("", {"a": typesafe.noul("x")}) is None
    assert typesafe.evaluate("hello", {}) is None


# --------------------------------------------------------------------------- #
# Chat routing integration (run_chat consumes system_one_intent)
# --------------------------------------------------------------------------- #
def _intent_body(route="rain_probability", confidence=0.9, live=0.95, smalltalk=0.01):
    return {
        "model": "jev-latest",
        "answers": {
            "route": {
                "type": "choice",
                "choice": route,
                "probabilities": {route: confidence},
                "confidence": confidence,
            },
            "live_data": {"type": "noul", "noul": live},
            "smalltalk": {"type": "noul", "noul": smalltalk},
        },
        "usage": {},
    }


def test_run_chat_uses_system_one_and_fast_path(monkeypatch):
    import agent
    from schemas import ChatRequest
    from services.chat import run_chat

    monkeypatch.setattr(
        typesafe, "_client_factory",
        _queue_client([], [{"status": 200, "body": _intent_body()}]),
    )
    monkeypatch.setattr(agent, "run_deterministic_telemetry_fallback",
                        lambda *a, **k: "MOCK TELEMETRY")
    monkeypatch.setattr(agent, "has_llm", lambda: False)

    result = run_chat(ChatRequest(message="rain in anand today?"))
    assert result.path == "fast"
    assert result.intent == "rain_probability"
    assert result.intent_engine == "system-one"
    assert result.intent_confidence == pytest.approx(0.9)


def test_run_chat_low_confidence_falls_back_to_keywords(monkeypatch):
    import agent
    from schemas import ChatRequest
    from services.chat import run_chat

    monkeypatch.setattr(
        typesafe, "_client_factory",
        _queue_client([], [{"status": 200, "body": _intent_body(confidence=0.2)}]),
    )
    monkeypatch.setattr(agent, "run_deterministic_telemetry_fallback",
                        lambda *a, **k: "MOCK TELEMETRY")
    monkeypatch.setattr(agent, "has_llm", lambda: False)

    result = run_chat(ChatRequest(message="rain in anand today?"))
    assert result.path == "fast"  # keywords still fast-path this
    assert result.intent_engine == "keywords"


def test_run_chat_system_one_greeting(monkeypatch):
    import agent
    from schemas import ChatRequest
    from services.chat import run_chat

    monkeypatch.setattr(
        typesafe, "_client_factory",
        _queue_client([], [{"status": 200, "body": _intent_body(route="greeting",
                                                                confidence=0.95)}]),
    )
    monkeypatch.setattr(agent, "run_deterministic_telemetry_fallback",
                        lambda *a, **k: "SHOULD NOT BE CALLED")
    monkeypatch.setattr(agent, "has_llm", lambda: False)

    result = run_chat(ChatRequest(message="hey there, what's up?"))
    assert result.path == "greeting"


def test_run_chat_off_topic_never_fast_paths(monkeypatch):
    import agent
    from schemas import ChatRequest
    from services.chat import run_chat

    monkeypatch.setattr(
        typesafe, "_client_factory",
        _queue_client([], [{"status": 200, "body": _intent_body(route="unrelated",
                                                                confidence=0.9)}]),
    )
    captured = {}

    def _fake_agent(*args, **kwargs):
        captured["called"] = True
        return "AGENT"

    monkeypatch.setattr(agent, "run_deterministic_telemetry_fallback",
                        lambda *a, **k: "SHOULD NOT BE CALLED")
    monkeypatch.setattr(agent, "has_llm", lambda: True)
    monkeypatch.setattr(agent, "run_weather_agent", _fake_agent)

    result = run_chat(ChatRequest(message="write me a poem about rain"))
    assert result.path == "agent"
    assert captured.get("called") is True


def test_run_chat_without_key_keeps_keyword_behaviour(monkeypatch):
    import agent
    from schemas import ChatRequest
    from services.chat import run_chat

    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setattr(agent, "run_deterministic_telemetry_fallback",
                        lambda *a, **k: "MOCK TELEMETRY")
    monkeypatch.setattr(agent, "has_llm", lambda: False)

    result = run_chat(ChatRequest(message="temperature in Rajkot"))
    assert result.path == "fast"
    assert result.intent_engine == "keywords"
