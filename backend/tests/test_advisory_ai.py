"""Offline tests for hourly advisory bands and the TypeSafe overlay merge."""

import os
import sys

import httpx
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services import advisory, typesafe  # noqa: E402


# --------------------------------------------------------------------------- #
# Deterministic hourly bands
# --------------------------------------------------------------------------- #
def test_hour_band_spraying_rules():
    calm = dict(pop=10, rain_mm=0.0, wind_kmh=8, temp_c=25, code=0)
    assert advisory.hour_band("spraying", **calm) == "good"
    assert advisory.hour_band("spraying", **dict(calm, wind_kmh=18)) == "caution"
    assert advisory.hour_band("spraying", **dict(calm, wind_kmh=28)) == "avoid"
    assert advisory.hour_band("spraying", **dict(calm, pop=70)) == "avoid"
    assert advisory.hour_band("spraying", **dict(calm, rain_mm=0.8)) == "avoid"
    assert advisory.hour_band("spraying", **dict(calm, temp_c=42)) == "avoid"
    assert advisory.hour_band("spraying", **dict(calm, temp_c=3)) == "avoid"
    assert advisory.hour_band("spraying", **dict(calm, code=95)) == "avoid"


def test_hour_band_irrigation_ignores_thunder():
    wet = dict(pop=80, rain_mm=0.0, wind_kmh=8, temp_c=25, code=95)
    assert advisory.hour_band("irrigation", **wet) == "avoid"  # rain, not thunder
    ok = dict(pop=10, rain_mm=0.0, wind_kmh=10, temp_c=25, code=95)
    assert advisory.hour_band("irrigation", **ok) == "good"


def test_worse_and_band_from_score():
    assert advisory.worse("good", "caution") == "caution"
    assert advisory.worse("avoid", "good") == "avoid"
    assert advisory.worse("good", "good") == "good"
    assert advisory.band_from_score(0.4) == "avoid"
    assert advisory.band_from_score(1.5) == "caution"
    assert advisory.band_from_score(2.9) == "good"


def _two_day_hourly():
    """Two cloud-free days; day 2 gets a windy, wet afternoon."""

    def stamp(day, hour):
        return f"2026-09-1{day}T{hour:02d}:00"

    time, pop, rain, wind, temp, code = [], [], [], [], [], []
    for day in (0, 1):
        for hour in range(24):
            time.append(stamp(day, hour))
            if day == 1 and 12 <= hour <= 17:
                pop.append(80); rain.append(1.5); wind.append(30); temp.append(24); code.append(95)
            else:
                pop.append(5); rain.append(0.0); wind.append(9); temp.append(27); code.append(0)
    return {
        "time": time,
        "precipitation_probability": pop,
        "precipitation": rain,
        "wind_speed_10m": wind,
        "temperature_2m": temp,
        "weather_code": code,
    }


def test_build_hourly_by_date_limits_days_and_bands():
    hourly = _two_day_hourly()
    dates = ["2026-09-10", "2026-09-11"]
    out = advisory.build_hourly_by_date(hourly, dates, hourly_days=2)
    assert set(out.keys()) == set(dates)
    assert set(out[dates[0]].keys()) == {"irrigation", "spraying", "field_work"}
    day0 = out[dates[0]]["spraying"]
    assert len(day0) == 24
    assert day0[9]["suitability"] == "good"
    # Day 2 afternoon must be degraded by wind/rain/thunder rules.
    day1 = out[dates[1]]["spraying"]
    assert all(cell["suitability"] == "avoid" for cell in day1[12:18])
    assert day1[6]["suitability"] == "good"


def test_daily_stats_aggregates():
    stats = advisory.daily_stats(_two_day_hourly(), "2026-09-11")
    assert stats is not None
    assert stats["pop_max"] == 80
    assert stats["thunder_hours"] == 6
    assert stats["rain_sum"] == pytest.approx(9.0)


def test_build_questions_fan_out():
    questions = advisory.build_questions(["d1", "d2"])
    assert set(questions) == {
        "d0_spray", "d0_irrigation", "d0_fieldwork", "d0_overall",
        "d1_spray", "d1_irrigation", "d1_fieldwork", "d1_overall",
    }
    assert questions["d0_spray"]["type"] == "score"
    assert questions["d0_overall"]["type"] == "choice"


# --------------------------------------------------------------------------- #
# Overlay merge policy
# --------------------------------------------------------------------------- #
def _answers(per_day):
    """per_day: {index: {key: (value, confidence)}} — mirrors the System One answers dict."""
    answers = {}
    for index, spec in per_day.items():
        for key, value in spec.items():
            if key == "overall":
                choice, conf = value
                answers[f"d{index}_overall"] = {
                    "type": "choice", "choice": choice, "confidence": conf,
                    "probabilities": {choice: conf},
                }
            else:
                score, conf = value
                answers[f"d{index}_{key}"] = {
                    "type": "score", "score": score, "confidence": conf,
                }
    return answers


def test_overlay_high_confidence_avoid_degrades_day_and_hourly():
    hourly = advisory.build_hourly_by_date(_two_day_hourly(), ["2026-09-10"])
    windows = [{"date": "2026-09-10", "suitability": "good",
                "summary": "Good day for field work.", "best_window": "Best: 6–10 AM"}]
    answers = _answers({0: {
        "spray": (0.2, 0.9), "irrigation": (3.0, 0.8), "fieldwork": (3.5, 0.85),
        "overall": ("avoid", 0.9),
    }})
    meta = advisory.apply_typesafe_overlay(windows, hourly, answers, min_confidence=0.55,
                                           model="jev-latest")
    assert meta["applied"] is True
    assert meta["overall_verdict"] == "avoid"
    assert windows[0]["suitability"] == "poor"  # daily vocabulary stays backward-compatible
    assert "unsafe" in windows[0]["summary"].lower()
    # Safety floor: every spraying hour is now avoid.
    assert all(c["suitability"] == "avoid" for c in hourly["2026-09-10"]["spraying"])
    # Irrigation hours stay threshold-based (only the day verdict changed).
    assert hourly["2026-09-10"]["irrigation"][9]["suitability"] == "good"


def test_overlay_low_confidence_is_transparent_only():
    hourly: dict = {}
    windows = [{"date": "2026-09-10", "suitability": "good",
                "summary": "Good day for field work.", "best_window": "Best: 6–10 AM"}]
    answers = _answers({0: {"overall": ("avoid", 0.3)}})
    meta = advisory.apply_typesafe_overlay(windows, hourly, answers, min_confidence=0.55)
    assert meta["applied"] is False
    assert windows[0]["suitability"] == "good"
    assert windows[0]["ai"]["overall"]["choice"] == "avoid"  # recorded, not acted on


def test_overlay_cannot_improve_a_day():
    windows = [{"date": "2026-09-10", "suitability": "poor",
                "summary": "Heavy rain likely — avoid spraying and limit field work.",
                "best_window": "Indoor / planning tasks"}]
    answers = _answers({0: {"overall": ("good", 0.99)}})
    meta = advisory.apply_typesafe_overlay(windows, {}, answers)
    assert windows[0]["suitability"] == "poor"  # model may never clear a bad day
    assert meta["applied"] is False


# --------------------------------------------------------------------------- #
# Router-level integration (fully offline: Open-Meteo and TypeSafe both mocked)
# --------------------------------------------------------------------------- #
def test_advisory_endpoint_includes_ai_fields(monkeypatch):
    from fastapi.testclient import TestClient
    from main import app
    import routers.mobile as mobile

    hourly = _two_day_hourly()
    forecast_payload = {
        "daily": {
            "time": ["2026-09-10", "2026-09-11"],
            "temperature_2m_max": [32.0, 31.0],
            "temperature_2m_min": [24.0, 23.5],
            "precipitation_probability_max": [10, 80],
            "rain_sum": [0.0, 12.0],
            "wind_speed_10m_max": [14.0, 32.0],
            "weather_code": [1, 95],
        },
        "hourly": hourly,
    }

    def _fake_get_json(url, params, timeout=12.0):
        return forecast_payload

    monkeypatch.setattr(mobile, "_get_json", _fake_get_json)
    monkeypatch.setenv("TYPESAFE_API_KEY", "tsk_test_key")

    answers = _answers(
        {
            0: {"spray": (3.6, 0.88), "irrigation": (3.1, 0.82),
                "fieldwork": (3.8, 0.9), "overall": ("good", 0.91)},
            1: {"spray": (0.3, 0.87), "irrigation": (1.2, 0.7),
                "fieldwork": (0.5, 0.85), "overall": ("avoid", 0.93)},
        }
    )

    def _factory(timeout: float) -> httpx.Client:
        return httpx.Client(
            base_url="https://mock.typesafe.test/v1",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={
                    "model": "jev-latest", "answers": answers, "usage": {}})
            ),
        )

    monkeypatch.setattr(typesafe, "_client_factory", _factory)

    client = TestClient(app)
    response = client.get("/advisory", params={"lat": 22.56, "lon": 72.95, "days": 2})
    assert response.status_code == 200
    data = response.json()
    assert data["advisory_engine"] == "system-one+thresholds"
    assert data["ai"]["enabled"] is True
    assert data["ai"]["overall_verdict"] in {"good", "caution", "avoid"}
    assert len(data["windows"]) == 2
    # Day 0 stays good; day 1 was already poor by thresholds and AI agrees.
    assert data["windows"][0]["suitability"] == "good"
    assert data["windows"][1]["suitability"] == "poor"
    assert data["windows"][0]["ai"]["overall"]["choice"] == "good"
    # Hourly bars are attached to the first two windows.
    assert len(data["windows"][0]["hourly"]["irrigation"]) == 24
    assert len(data["windows"][1]["hourly"]["spraying"]) == 24
    # High-confidence "Unsafe" spraying on day 1 floors every spraying hour.
    assert all(c["suitability"] == "avoid" for c in data["windows"][1]["hourly"]["spraying"])


def test_advisory_endpoint_without_key_stays_threshold_based(monkeypatch):
    from fastapi.testclient import TestClient
    from main import app
    import routers.mobile as mobile

    forecast_payload = {
        "daily": {
            "time": ["2026-09-10"],
            "temperature_2m_max": [32.0],
            "temperature_2m_min": [24.0],
            "precipitation_probability_max": [10],
            "rain_sum": [0.0],
            "wind_speed_10m_max": [14.0],
            "weather_code": [1],
        },
        "hourly": _two_day_hourly(),
    }

    monkeypatch.setattr(mobile, "_get_json", lambda url, params, timeout=12.0: forecast_payload)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)

    client = TestClient(app)
    response = client.get("/advisory", params={"lat": 22.56, "lon": 72.95, "days": 1})
    assert response.status_code == 200
    data = response.json()
    assert data["advisory_engine"] == "thresholds"
    assert data["ai"]["enabled"] is False
    assert "hourly" in data["windows"][0]


# --------------------------------------------------------------------------- #
# Farm context in the System One state
# --------------------------------------------------------------------------- #
def test_build_state_includes_farm_context():
    stats = [{"pop_max": 10, "rain_sum": 0.0, "wind_max": 9.0, "temp_min": 24.0,
              "temp_max": 32.0, "thunder_hours": 0}]
    state = advisory.build_state(
        "Wheat", 22.56, 72.95, ["2026-09-10"], stats,
        farm={"growth_stage": "Flowering", "soil": "Loamy", "irrigation": ""},
    )
    assert "Crop: Wheat" in state
    assert "growth stage: Flowering" in state
    assert "soil: Loamy" in state
    assert "irrigation:" not in state  # empty context values are omitted
    assert "rain chance 10%" in state  # forecast sketch still present


def test_build_state_sanitizes_farm_values():
    stats = [{"pop_max": 10, "rain_sum": 0.0, "wind_max": 9.0, "temp_min": 24.0,
              "temp_max": 32.0, "thunder_hours": 0}]
    state = advisory.build_state(
        "Wheat", 22.56, 72.95, ["2026-09-10"], stats,
        farm={"growth_stage": "  weird\nmulti  space  value that is far too long to be useful  "},
    )
    assert "growth stage: weird multi space value that is far too" in state


def test_advisory_endpoint_forwards_farm_context_to_system_one(monkeypatch):
    from fastapi.testclient import TestClient
    from main import app
    import routers.mobile as mobile

    forecast_payload = {
        "daily": {
            "time": ["2026-09-10"],
            "temperature_2m_max": [32.0],
            "temperature_2m_min": [24.0],
            "precipitation_probability_max": [10],
            "rain_sum": [0.0],
            "wind_speed_10m_max": [14.0],
            "weather_code": [1],
        },
        "hourly": _two_day_hourly(),
    }
    monkeypatch.setattr(mobile, "_get_json",
                        lambda url, params, timeout=12.0: forecast_payload)
    monkeypatch.setenv("TYPESAFE_API_KEY", "tsk_test_key")

    captured_states: list[str] = []

    def _factory(timeout: float) -> httpx.Client:
        def handler(request: httpx.Request) -> httpx.Response:
            import json as _json
            captured_states.append(_json.loads(request.content)["state"])
            return httpx.Response(200, json={
                "model": "jev-latest",
                "answers": _answers({0: {"overall": ("good", 0.9)}}),
                "usage": {},
            })
        return httpx.Client(base_url="https://mock.typesafe.test/v1",
                            transport=httpx.MockTransport(handler))

    monkeypatch.setattr(typesafe, "_client_factory", _factory)

    client = TestClient(app)
    response = client.get("/advisory", params={
        "lat": 22.56, "lon": 72.95, "crop": "Wheat", "days": 1,
        "growth_stage": "Flowering", "soil": "Loamy", "irrigation": "Borewell",
    })
    assert response.status_code == 200
    assert captured_states, "System One must have been called"
    assert "growth stage: Flowering" in captured_states[0]
    assert "soil: Loamy" in captured_states[0]
    assert "irrigation: Borewell" in captured_states[0]
