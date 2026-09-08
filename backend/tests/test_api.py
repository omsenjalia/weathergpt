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

def test_imd_features_catalog():
    """Verify GET /api/imd/features catalog contains 28 official IMD features."""
    response = client.get("/api/imd/features")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["total"] == 28
    assert isinstance(data["features"], list)
    assert len(data["features"]) == 28

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

