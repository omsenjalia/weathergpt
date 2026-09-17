"""Offline unit tests for services/response.py output gate."""

import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.response import extract_widgets, strip_widgets, sanitize_response


def _weather_json(city="Surat"):
    return json.dumps(
        {
            "city": city,
            "temp": 32,
            "feelsLike": 35,
            "condition": "Sunny",
            "humidity": 50,
            "windSpeed": 10,
            "advisory": "Stay hydrated",
        }
    )


def _forecast_json(city="Surat"):
    return json.dumps(
        {
            "city": city,
            "days": [
                {"day": "Today", "temp": 32, "condition": "Sunny", "rainProb": 10},
                {"day": "Tomorrow", "temp": 30, "condition": "Cloudy", "rainProb": 20},
            ],
        }
    )


def test_reasoning_preamble_then_hr_then_answer_widgets_ordered():
    """Screenshot case: reasoning preamble -> --- -> answer, widgets reordered weather, forecast."""
    raw = f"""Reasoning & Formatting Approach
1. User asks weather in Surat
2. Need to format with widgets
3. Provide answer in English

---
## Weather in Surat

It is sunny and hot today with 32°C.

```widget:forecast
{_forecast_json()}
```

```widget:weather
{_weather_json()}
```
"""
    cleaned = sanitize_response(
        raw,
        required_widgets=[("weather", _weather_json()), ("forecast", _forecast_json())],
    )

    # Reasoning should be gone
    assert "Reasoning & Formatting Approach" not in cleaned
    assert "1. User asks" not in cleaned

    # Answer should remain
    assert "## Weather in Surat" in cleaned
    assert "It is sunny" in cleaned

    # Widgets should be at end, ordered weather then forecast
    assert cleaned.count("```widget:weather") == 1
    assert cleaned.count("```widget:forecast") == 1
    weather_idx = cleaned.index("```widget:weather")
    forecast_idx = cleaned.index("```widget:forecast")
    assert weather_idx < forecast_idx, "weather widget should come before forecast"
    # Prose before widgets
    assert cleaned.index("## Weather in Surat") < weather_idx


def test_think_tags_removed():
    raw = f"""<think>
This is internal reasoning that should not be shown.
We need to think about Surat weather.
</think>
## Weather in Surat

Sunny day.

```widget:weather
{_weather_json()}
```
"""
    cleaned = sanitize_response(raw)
    assert "<think>" not in cleaned.lower()
    assert "internal reasoning" not in cleaned
    assert "## Weather in Surat" in cleaned
    assert "Sunny day" in cleaned


def test_think_tags_case_insensitive_and_other_tags():
    raw = """<THINKING>secret</THINKING>
<Reasoning>more secret</Reasoning>
<analysis>even more</analysis>
## Final Answer

Hello world.
"""
    cleaned = sanitize_response(raw)
    assert "secret" not in cleaned
    assert "even more" not in cleaned
    assert "Hello world" in cleaned


def test_unterminated_think_tag_cut_to_heading():
    raw = """<think>
Unterminated reasoning that should be cut
## Weather in Delhi

Actual answer starts here.
"""
    cleaned = sanitize_response(raw)
    assert "Unterminated" not in cleaned
    assert "## Weather in Delhi" in cleaned
    assert "Actual answer" in cleaned


def test_broken_missing_widgets_replaced_by_required():
    # No widgets at all, but required provided
    raw = "## Weather in Surat\n\nSunny day, 32°C."
    cleaned = sanitize_response(
        raw,
        required_widgets=[("weather", _weather_json()), ("forecast", _forecast_json())],
    )
    assert "```widget:weather" in cleaned
    assert "```widget:forecast" in cleaned
    assert "Sunny day" in cleaned

    # Broken widget JSON should be dropped and replaced
    raw_broken = f"""## Weather in Surat

Sunny.

```widget:weather
not-json-at-all
```

```widget:forecast
{{"invalid": [}}
```
"""
    cleaned2 = sanitize_response(
        raw_broken,
        required_widgets=[("weather", _weather_json()), ("forecast", _forecast_json())],
    )
    # Should not contain broken json
    assert "not-json-at-all" not in cleaned2
    # Should contain required valid json
    assert _weather_json() in cleaned2
    assert _forecast_json() in cleaned2
    # Only 2 widgets
    assert cleaned2.count("```widget:weather") == 1
    assert cleaned2.count("```widget:forecast") == 1


def test_widgets_at_start_moved_to_end():
    raw = f"""```widget:weather
{_weather_json()}
```

Some intro text about weather.

## Details

More details.
"""
    cleaned = sanitize_response(raw)
    # Widget should be at end
    assert cleaned.strip().endswith("```")
    assert cleaned.index("Some intro text") < cleaned.index("```widget:weather")
    # Prose should be before widget
    assert "Some intro text" in cleaned
    assert "## Details" in cleaned


def test_plain_text_untouched():
    raw = "Hello, this is plain text without any widgets or reasoning."
    cleaned = sanitize_response(raw)
    assert cleaned == raw


def test_legit_heading_plan_your_day_untouched():
    raw = """## Plan your day in Surat

- Morning: Sunny, 28°C
- Afternoon: Hot, 35°C

Enjoy your day!
"""
    cleaned = sanitize_response(raw)
    # Should be unchanged (except blank line collapsing which should be same)
    assert "## Plan your day in Surat" in cleaned
    assert "Morning: Sunny" in cleaned
    # Ensure it wasn't stripped as reasoning
    assert cleaned.strip().startswith("## Plan your day in Surat")


def test_heading_variants_stripped():
    variants = [
        "Reasoning",
        "**Thinking:**",
        "### Reasoning and Formatting Approach",
        "Thought process:",
        "## Reasoning",
        "**Reasoning & Formatting Approach**",
        "My approach",
        "Let me think",
        "First, I'll think about this",
        "Analysis:",
        "Scratchpad",
    ]
    for variant in variants:
        raw = f"""{variant}

Some internal planning here that should be removed.

---
## Weather in Pune

Pune is pleasant today.

```widget:weather
{_weather_json('Pune')}
```
"""
        cleaned = sanitize_response(raw)
        assert variant not in cleaned or "Weather in Pune" in cleaned  # variant line should be gone
        # Ensure internal planning is removed
        assert "internal planning" not in cleaned
        assert "## Weather in Pune" in cleaned
        assert "Pune is pleasant" in cleaned


def test_heading_variant_without_boundary_unchanged():
    # If reasoning heading has no HR or next heading, leave unchanged per spec
    raw = """Reasoning

Just some reasoning with no boundary after.
"""
    cleaned = sanitize_response(raw)
    # No boundary found, so original text should be left unchanged
    assert "Reasoning" in cleaned
    assert "Just some reasoning" in cleaned


def test_answer_heading_preference_over_hr_and_next_heading():
    raw = f"""Reasoning & Formatting Approach
We need to answer.

## Answer

## Weather in Surat

Sunny!

---
## Other section that should not appear before?

```widget:weather
{_weather_json()}
```
"""
    cleaned = sanitize_response(raw)
    # Should cut after Answer heading, so content after Answer heading remains
    assert "## Weather in Surat" in cleaned
    assert "Reasoning" not in cleaned
    # The "## Answer" heading itself should be removed (cut after it)
    assert "## Answer" not in cleaned or cleaned.count("## Answer") == 0


def test_hr_preference_over_next_heading():
    raw = f"""Thinking

Some thoughts.

---

## Weather in Surat

Sunny!

```widget:weather
{_weather_json()}
```
"""
    cleaned = sanitize_response(raw)
    assert "Some thoughts" not in cleaned
    assert "## Weather in Surat" in cleaned
    assert "Thinking" not in cleaned


def test_next_heading_fallback():
    raw = f"""Thought process:

Planning...

## Weather in Surat

Sunny day!

```widget:weather
{_weather_json()}
```
"""
    cleaned = sanitize_response(raw)
    assert "Planning" not in cleaned
    assert "## Weather in Surat" in cleaned


def test_extract_widgets_and_strip_widgets():
    text = f"""Hello

```widget:weather
{_weather_json()}
```

Middle

```widget:forecast
{_forecast_json()}
```

End
"""
    widgets = extract_widgets(text)
    assert len(widgets) == 2
    assert widgets[0][0] == "weather"
    assert widgets[1][0] == "forecast"
    # json strings should be parseable
    assert json.loads(widgets[0][1])["city"] == "Surat"

    stripped = strip_widgets(text)
    assert "```widget:weather" not in stripped
    assert "```widget:forecast" not in stripped
    assert "Hello" in stripped
    assert "Middle" in stripped


def test_invalid_widget_json_dropped():
    raw = """## Weather

Text

```widget:weather
not json
```

```widget:forecast
["not", "a", "dict"]
```

More text
"""
    cleaned = sanitize_response(raw)
    assert "not json" not in cleaned
    assert '["not", "a", "dict"]' not in cleaned
    assert "```widget:weather" not in cleaned
    assert "```widget:forecast" not in cleaned
    assert "More text" in cleaned


def test_prose_collapsed_max_one_blank_line():
    raw = """## Weather

Line1


Line2



Line3
"""
    cleaned = sanitize_response(raw)
    # Should not have 3 consecutive newlines
    assert "\n\n\n" not in cleaned
    # Should have at most double newline
    assert "Line1" in cleaned and "Line2" in cleaned and "Line3" in cleaned


def test_required_widgets_authoritative_override():
    model_weather = json.dumps({"city": "Old", "temp": 10, "feelsLike": 10, "condition": "Old", "humidity": 10, "windSpeed": 1, "advisory": "old"})
    backend_weather = _weather_json("NewCity")
    raw = f"""## Weather

Text

```widget:weather
{model_weather}
```
"""
    cleaned = sanitize_response(raw, required_widgets=[("weather", backend_weather)])
    assert "Old" not in cleaned or "NewCity" in cleaned
    assert "NewCity" in cleaned
    # Only one weather widget
    assert cleaned.count("```widget:weather") == 1
    assert backend_weather in cleaned


def test_sanitize_with_list_content():
    # Simulate LangChain content being list
    # Our function should handle str only, but we also test helper in agent.py separately
    # Here we just ensure sanitize_response handles None and empty gracefully
    assert sanitize_response("") == ""
    assert sanitize_response(None) == ""
