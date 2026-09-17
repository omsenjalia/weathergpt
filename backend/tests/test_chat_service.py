"""Offline unit tests for the shared chat routing policy."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from schemas import ChatRequest
from services.chat import (
    detect_client,
    is_greeting_or_meta,
    is_simple_weather_query,
    is_weather_related,
    classify_intent,
    normalize_language,
    resolve_weather_context,
    resolve_history,
)


def test_normalize_language_codes_and_names():
    assert normalize_language("hi") == "Hindi"
    assert normalize_language("gu-IN") == "Gujarati"
    assert normalize_language("Hindi") == "Hindi"
    assert normalize_language("") == "English"
    assert normalize_language("marathi") == "Marathi"


def test_detect_client():
    assert detect_client(ChatRequest(message="x", lat=1.0, lon=2.0)) == "mobile"
    assert detect_client(ChatRequest(messages=[{"role": "user", "content": "x"}]), "Mozilla/5.0") == "web"
    assert detect_client(ChatRequest(message="x"), "Dart/3.3 (dart:io)") == "mobile"
    assert detect_client(ChatRequest(message="x", client="web"), "Dart/3.3") == "web"


def test_resolve_history_web_and_mobile():
    web = ChatRequest(messages=[{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"},
                                {"role": "user", "content": "rain in pune?"}])
    payload, last = resolve_history(web)
    assert isinstance(payload, list) and last == "rain in pune?"
    mobile = ChatRequest(message="temp in surat")
    assert resolve_history(mobile) == ("temp in surat", "temp in surat")


def test_resolve_weather_context_preserves_recent_user_location():
    request = ChatRequest(messages=[
        {"role": "user", "content": "What is the weather in Anand?"},
        {"role": "assistant", "content": "Weather in Anand is clear."},
        {"role": "user", "content": "What about tomorrow?"},
    ])
    context = resolve_weather_context(request, "What about tomorrow?")
    assert "Anand" in context
    assert "tomorrow" in context


def test_greeting_and_simple_heuristics():
    assert is_greeting_or_meta("Hello!")
    assert is_greeting_or_meta("who are you?")
    assert not is_greeting_or_meta("weather in delhi")
    assert not is_greeting_or_meta("no i am talking about chances of raining")
    assert is_simple_weather_query("no i am talking about chances of raining", False)
    assert is_simple_weather_query("weather in delhi", False)
    assert not is_simple_weather_query("should I irrigate wheat tomorrow?", False)
    assert not is_simple_weather_query("weather in delhi", True)  # farmer mode → agent
    assert not is_simple_weather_query("compare mumbai and pune rainfall", False)


def test_weather_domain_allows_conversation_and_research():
    assert is_weather_related("No, I mean chances of raining")
    assert is_weather_related("Explain why the forecast changed")
    assert is_weather_related("Compare Mumbai and Pune rainfall historically")
    assert is_weather_related("Should I carry an umbrella?")


def test_unrelated_requests_do_not_take_weather_fast_path():
    assert not is_simple_weather_query("write Python code for a weather app", False)
    assert not is_weather_related("Help me study for my exam")


def test_intent_labels_support_conversation_and_research():
    assert classify_intent("No, I mean chances of raining") == "rain_probability"
    assert classify_intent("Compare rainfall with last year") == "historical_weather"
    assert classify_intent("Why did the forecast change?") == "weather_explanation"
    assert classify_intent("write Python code for a weather app") == "unrelated"
