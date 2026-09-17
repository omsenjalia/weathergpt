"""Offline unit tests for the shared chat routing policy."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from schemas import ChatRequest
from services.chat import (
    detect_client,
    is_greeting_or_meta,
    is_simple_weather_query,
    normalize_language,
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


def test_greeting_and_simple_heuristics():
    assert is_greeting_or_meta("Hello!")
    assert is_greeting_or_meta("who are you?")
    assert not is_greeting_or_meta("weather in delhi")
    assert is_simple_weather_query("weather in delhi", False)
    assert not is_simple_weather_query("should I irrigate wheat tomorrow?", False)
    assert not is_simple_weather_query("weather in delhi", True)  # farmer mode → agent
    assert not is_simple_weather_query("compare mumbai and pune rainfall", False)
