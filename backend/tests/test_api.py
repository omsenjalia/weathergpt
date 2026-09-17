import pytest
from fastapi.testclient import TestClient
import sys
import os

# Ensure backend root is on Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from main import app

client = TestClient(app)

def test_health_endpoint():
    """Verify GET /health returns status ok."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "weathergpt-app" in data["clients"]

def test_dev_diagnostics_endpoint():
    """Verify GET /dev returns system metrics, LLM config, and endpoints."""
    response = client.get("/dev")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "system" in data
    assert "llm_config" in data
    assert "provider_keys_status" in data
    assert "registered_endpoints" in data
    assert "registered_ai_tools" in data
    assert "recent_logs" in data

def test_dev_sandbox_endpoint():
    """Verify POST /dev/sandbox executes prompt and returns latency profiling."""
    payload = {
        "prompt": "What is the weather in Jaipur?",
        "location": "Jaipur, Rajasthan",
        "language": "English"
    }
    response = client.post("/dev/sandbox", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "duration_ms" in data
    assert "response" in data
    assert data["prompt"] == payload["prompt"]

def test_chat_endpoint_schema():
    """Verify POST /chat responds appropriately for a conversation request."""
    payload = {
        "messages": [{"role": "user", "content": "What is the temperature in Mumbai?"}],
        "location": "Mumbai, India",
        "language": "English",
        "farmer_mode": False,
        "crop": ""
    }
    response = client.post("/chat", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "response" in data
    assert isinstance(data["response"], str)

def test_non_weather_guardrail():
    """Verify non-weather messages receive domain boundary refusal."""
    payload = {
        "messages": [{"role": "user", "content": "Can you write a Python script to sort a list?"}],
        "location": "New Delhi",
        "language": "English",
        "farmer_mode": False,
        "crop": ""
    }
    response = client.post("/chat", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "response" in data
    assert "weather" in data["response"].lower() or "sorry" in data["response"].lower()



def test_weather_requires_coords():
    """GET /weather without lat/lon should fail validation."""
    response = client.get("/weather")
    assert response.status_code == 422


def test_weather_rejects_out_of_range_coordinates():
    for params in ({"lat": 91, "lon": 72}, {"lat": 23, "lon": -181}, {"lat": "nan", "lon": 72}):
        response = client.get("/weather", params=params)
        assert response.status_code == 422


def test_comparison_skips_invalid_coordinates():
    response = client.get("/comparison", params={"locations": "Bad,91,72"})
    assert response.status_code == 400


def test_weather_endpoint_schema():
    """GET /weather returns fields expected by the Flutter home screens."""
    response = client.get("/weather", params={"lat": 23.0225, "lon": 72.5714})
    # Upstream Open-Meteo must be reachable in CI; allow 200 or upstream error codes
    assert response.status_code in (200, 502, 504)
    if response.status_code == 200:
        data = response.json()
        for key in (
            "temperature_c",
            "condition",
            "high_c",
            "low_c",
            "rain_probability",
            "wind_kmh",
            "humidity",
            "pressure_hpa",
        ):
            assert key in data, f"missing {key}"


def test_advisory_endpoint_shape():
    response = client.get(
        "/advisory", params={"lat": 23.02, "lon": 72.57, "crop": "wheat", "days": 3}
    )
    assert response.status_code in (200, 502, 504)
    if response.status_code == 200:
        data = response.json()
        assert "windows" in data
        assert "summary" in data


def test_chat_mobile_shape_and_accept_language():
    """Mobile payload (message + lat/lon + ISO language code) must be accepted."""
    payload = {
        "message": "hello",
        "location": "Ahmedabad, Gujarat",
        "lat": 23.02,
        "lon": 72.57,
        "language": "en",
        "farmer_mode": False,
        "crop": "",
    }
    response = client.post("/chat", json=payload, headers={"Accept-Language": "hi"})
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data["response"], str) and data["response"]
    assert data["meta"]["client"] == "mobile"
    assert data["meta"]["language"] == "Hindi"
    assert data["meta"]["path"] == "greeting"


def test_chat_web_greeting_meta():
    payload = {"messages": [{"role": "user", "content": "hi"}], "location": "Delhi", "language": "Gujarati"}
    response = client.post("/chat", json=payload, headers={"User-Agent": "Mozilla/5.0"})
    assert response.status_code == 200
    meta = response.json()["meta"]
    assert meta["client"] == "web"
    assert meta["language"] == "Gujarati"


def test_root_lists_both_clients():
    data = client.get("/").json()
    assert set(data["clients"]) == {"web", "mobile"}
    assert data["fusion_priority"][:2] == ["Open-Meteo (ECMWF)", "AccuWeather"]


def test_fusion_endpoint_requires_coords():
    assert client.get("/fusion").status_code == 422


def test_fusion_endpoint_shape():
    response = client.get("/fusion", params={"lat": 23.02, "lon": 72.57})
    assert response.status_code in (200, 502, 504)
    if response.status_code == 200:
        data = response.json()
        assert data["weights"]["Open-Meteo (ECMWF)"] == 2.0
        assert "temperature_2m" in data and "providers" in data
