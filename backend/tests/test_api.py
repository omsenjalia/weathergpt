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
    assert data == {"status": "ok"}

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
