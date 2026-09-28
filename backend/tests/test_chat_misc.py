import base64
import io
import time
import wave

from weathergpt.ai import chat as orchestrator
from weathergpt.ai import intent, place


def test_intents():
    assert intent.classify("hello") == "greeting"
    assert intent.classify("नमस्ते") == "greeting"
    assert intent.classify("will it rain tomorrow in pune") == "rain_probability"
    assert intent.classify("Mumbai ma varsad padse?") == "rain_probability"
    assert intent.classify("should I spray my cotton tomorrow") == "farm_advice"
    assert intent.classify("write python code for a calculator") == "unrelated"
    assert intent.classify("any red alert for heat wave") == "weather_alerts"
    assert intent.classify("Ahmedabad tomorrow") == "weather_current_or_forecast"


def test_place_candidates():
    assert place.candidates("will it rain in Pune tomorrow") == ["Pune"]
    assert place.candidates("Ahmedabad ma varsad") == ["Ahmedabad"]
    assert place.candidates("दिल्ली में मौसम कैसा है") == ["दिल्ली"]
    assert place.candidates("will it rain tomorrow") == []


def test_language_resolution():
    assert orchestrator.language_code("hi") == "hi"
    assert orchestrator.language_code("Gujarati") == "gu"
    assert orchestrator.language_code("", "ta-IN,en;q=0.8") == "ta"
    assert orchestrator.language_code("klingon") == "en"


def test_chat_fast_path_card_uses_live_numbers(client, upstreams):
    r = client.post("/chat", json={"message": "will it rain tomorrow in Pune?", "location": "Ahmedabad",
                                   "lat": 23.02, "lon": 72.57, "language": "en"})
    body = r.json()
    assert r.status_code == 200
    assert body["meta"]["path"] == "fast" and body["meta"]["location"] == "Pune"
    assert body["meta"]["selected_source"] == "open_meteo"
    card = body["card"]
    assert card["label"] == "Rain Forecast"
    assert card["stats"][0] == {"label": "Chance of rain (24 h)", "value": "10%", "tone": "good"}
    assert card["forecast"][0]["day"] == "Today"
    assert "```widget:weather" in body["response"]


def test_chat_uses_device_location_when_no_place_named(client, upstreams):
    body = client.post("/chat", json={"message": "weather now", "location": "Ahmedabad, Gujarat",
                                      "lat": 23.02, "lon": 72.57}).json()
    assert body["meta"]["location"] == "Ahmedabad" and body["meta"]["lat"] == 23.02


def test_chat_greeting_is_localised(client, upstreams):
    body = client.post("/chat", json={"message": "hello", "language": "gu"}).json()
    assert body["meta"]["path"] == "greeting" and "હું" in body["response"]
    assert body["card"] is None
    assert upstreams.calls == []


def test_chat_pin_is_not_substituted(client, upstreams):
    body = client.post("/chat", json={"message": "weather now", "location": "Ahmedabad", "lat": 23, "lon": 72,
                                      "requested_source": "imd"}).json()
    assert body["meta"]["path"] == "pinned"
    assert "trouble reaching" in body["response"] and "IMD" in body["response"]


def test_farmer_mode_is_authoritative_and_context_reaches_agent(client, upstreams, monkeypatch):
    from weathergpt.ai import agent
    from weathergpt.config import reset_settings

    monkeypatch.setenv("GROQ_API_KEY", "test")
    reset_settings()
    seen = {}

    def fake_run(prompt, history, **kw):
        seen["prompt"] = prompt
        return "**Spray early tomorrow morning.**"

    monkeypatch.setattr(agent, "run", fake_run)
    body = client.post("/chat", json={"message": "Should I spray cotton tomorrow?", "mode": "farmer",
                                      "crop": "Cotton", "soil": "Clay", "lat": 23.02, "lon": 72.57,
                                      "location": "Ahmedabad"}).json()
    assert body["meta"]["path"] == "agent" and body["meta"]["mode"] == "farmer"
    assert body["response"].startswith("**Spray early")
    assert "soil: Clay" in seen["prompt"] and "LIVE DATA for Ahmedabad" in seen["prompt"]
    everyone = client.post("/chat", json={"message": "hello", "mode": "everyone", "farmer_mode": True}).json()
    assert everyone["meta"]["mode"] == "everyone"


def test_agent_timeout_serves_deterministic_answer_quickly(client, upstreams, monkeypatch):
    from weathergpt.ai import agent
    from weathergpt.config import reset_settings

    monkeypatch.setenv("GROQ_API_KEY", "test")
    monkeypatch.setenv("CHAT_TIMEOUT_SECONDS", "0.2")
    reset_settings()
    monkeypatch.setattr(agent, "run", lambda *a, **k: time.sleep(2) or "late")
    started = time.monotonic()
    body = client.post("/chat", json={"message": "explain why it is humid", "lat": 23.02, "lon": 72.57,
                                      "location": "Ahmedabad"}).json()
    assert time.monotonic() - started < 1.5
    assert body["meta"]["path"] == "fallback" and "Weather for Ahmedabad" in body["response"]


def test_research_endpoints(client, upstreams):
    r = client.get("/historical", params={"lat": 23, "lon": 72, "start_year": 2020, "end_year": 2021})
    assert r.status_code == 200 and r.json()["points"] == [{"year": 2020, "value": 730.0, "days": 365},
                                                           {"year": 2021, "value": 730.0, "days": 365}]
    r = client.get("/comparison", params={"locations": "Ahmedabad, Gujarat, India,23,72;Pune,18.5,73.8",
                                           "start_year": 2020, "end_year": 2021})
    assert [l["name"] for l in r.json()["locations"]] == ["Ahmedabad, Gujarat, India", "Pune"]
    assert client.get("/historical", params={"lat": 23, "lon": 72, "metric": "snow"}).status_code == 400


def test_speech_health_and_tts(client, upstreams, monkeypatch):
    from weathergpt import http
    from weathergpt.config import reset_settings
    from weathergpt.speech import bhashini

    assert client.get("/v2/speech/health").json()["configured"] is False
    assert client.post("/v2/speech/tts", json={"text": "hi"}).status_code == 503

    monkeypatch.setenv("BHASHINI_USER_ID", "u")
    monkeypatch.setenv("BHASHINI_ULCA_API_KEY", "k")
    reset_settings()
    bhashini.clear_cache()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(22050), w.writeframes(b"\x00\x00" * 100)
    audio = base64.b64encode(buf.getvalue()).decode()

    def transport(method, url, params, headers, body, timeout):
        import json
        if "getModelsPipeline" in url:
            data = {"pipelineResponseConfig": [{"taskType": "tts", "config": [{"language": {"sourceLanguage": "hi"},
                                                                                "serviceId": "svc"}]}],
                    "pipelineInferenceAPIEndPoint": {"callbackUrl": "https://dhruva/infer",
                                                     "inferenceApiKey": {"name": "Authorization", "value": "x"}}}
        else:
            data = {"pipelineResponse": [{"audio": [{"audioContent": audio}]}]}
        return http.Reply(200, {"content-type": "application/json"}, json.dumps(data).encode())

    http.set_transport(transport)
    r = client.post("/v2/speech/tts", json={"text": "नमस्ते। " * 80, "language": "hi"})
    assert r.status_code == 200, r.text
    assert r.json()["chunks"] > 1 and r.json()["sample_rate"] == 22050


def test_dev_routes(client, upstreams, monkeypatch):
    d = client.get("/dev").json()
    assert d["status"] == "ok" and "get_imd_product" in d["registered_ai_tools"]
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/dev/imd/probe").status_code == 403
    monkeypatch.setenv("ADMIN_TOKEN", "s3cret")
    assert client.get("/dev/imd/probe", headers={"X-Admin-Token": "nope"}).status_code == 401
    assert client.get("/dev/imd/probe", headers={"X-Admin-Token": "s3cret"}).json()["status"] == "not_configured"


def test_vercel_entrypoint():
    import json
    from pathlib import Path
    from api.index import app
    assert app.title == "WeatherGPT API"
    cfg = json.loads((Path(__file__).parents[1] / "vercel.json").read_text())
    assert cfg["rewrites"][0]["destination"] == "/api/index"
