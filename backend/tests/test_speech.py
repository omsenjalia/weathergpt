import base64
import io
import json
import os
import sys
import wave

import httpx
import pytest
import struct
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from main import app  # noqa: E402
from services import bhashini  # noqa: E402

CALLBACK = "https://dhruva-api.bhashini.gov.in/services/inference/pipeline"


def _wav(frames: int, rate: int = 22050) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x01\x00" * frames)
    return buf.getvalue()


class FakeBhashini:
    """Records calls and answers like the ULCA config + Dhruva compute endpoints."""

    def __init__(self, *, config_status=200, compute_status=200, languages=("hi", "en", "gu")):
        self.calls: list[tuple[str, dict, dict]] = []
        self.config_status = config_status
        self.compute_status = compute_status
        self.languages = languages

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        self.calls.append((str(request.url), dict(request.headers), body))
        if str(request.url) == bhashini.CONFIG_URL:
            if self.config_status != 200:
                return httpx.Response(self.config_status, json={"message": "no"})
            task = body["pipelineTasks"][0]["taskType"]
            lang = body["pipelineTasks"][0]["config"]["language"]["sourceLanguage"]
            options = [
                {"serviceId": f"svc-{task}-{lang}", "language": {"sourceLanguage": lang}}
            ] if lang in self.languages else []
            return httpx.Response(200, json={
                "pipelineResponseConfig": [{"taskType": task, "config": options}],
                "pipelineInferenceAPIEndPoint": {
                    "callbackUrl": CALLBACK,
                    "inferenceApiKey": {"name": "Authorization", "value": "inference-key"},
                },
            })
        if self.compute_status != 200:
            return httpx.Response(self.compute_status, json={"detail": "boom"})
        task = body["pipelineTasks"][0]["taskType"]
        if task == "tts":
            text = body["inputData"]["input"][0]["source"]
            audio = base64.b64encode(_wav(len(text))).decode()
            return httpx.Response(200, json={"pipelineResponse": [{"taskType": "tts", "audio": [{"audioContent": audio}]}]})
        return httpx.Response(200, json={"pipelineResponse": [{"taskType": "asr", "output": [{"source": " कल बारिश होगी? "}]}]})

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setenv("BHASHINI_USER_ID", "user-1")
    monkeypatch.setenv("BHASHINI_ULCA_API_KEY", "ulca-key")
    monkeypatch.delenv("BHASHINI_PIPELINE_ID", raising=False)
    bhashini.clear_cache()
    yield
    bhashini.clear_cache()


def test_tts_uses_config_then_compute_with_returned_key():
    fake = FakeBhashini()
    result = bhashini.synthesize("नमस्ते। आज मौसम साफ है।", "hi", client=fake.client())

    config_url, config_headers, config_body = fake.calls[0]
    assert config_url == bhashini.CONFIG_URL
    assert config_headers["userid"] == "user-1"
    assert config_headers["ulcaapikey"] == "ulca-key"
    assert config_body["pipelineRequestConfig"]["pipelineId"] == bhashini.DEFAULT_PIPELINE_ID

    compute_url, compute_headers, compute_body = fake.calls[1]
    assert compute_url == CALLBACK
    assert compute_headers["authorization"] == "inference-key"
    task = compute_body["pipelineTasks"][0]
    assert task["config"] == {"language": {"sourceLanguage": "hi"}, "serviceId": "svc-tts-hi", "gender": "female"}

    assert result["provider"] == "bhashini"
    assert result["audio_format"] == "wav"
    assert result["sample_rate"] == 22050
    with wave.open(io.BytesIO(base64.b64decode(result["audio_base64"])), "rb") as w:
        assert w.getnframes() > 0


def test_config_is_cached_per_task_and_language():
    fake = FakeBhashini()
    client = fake.client()
    bhashini.synthesize("one", "hi", client=client)
    bhashini.synthesize("two", "hi", client=client)
    config_calls = [c for c in fake.calls if c[0] == bhashini.CONFIG_URL]
    assert len(config_calls) == 1
    bhashini.synthesize("three", "en", client=client)
    assert len([c for c in fake.calls if c[0] == bhashini.CONFIG_URL]) == 2


def test_long_text_is_chunked_and_wavs_are_joined():
    fake = FakeBhashini()
    sentence = "Rain is likely in the evening, so plan field work for the morning. "
    result = bhashini.synthesize(sentence * 20, "en", client=fake.client())
    compute_calls = [c for c in fake.calls if c[0] == CALLBACK]
    assert result["chunks"] == len(compute_calls) > 1
    for _, _, body in compute_calls:
        assert len(body["inputData"]["input"][0]["source"]) <= bhashini.TTS_CHUNK_CHARS
    total = sum(len(body["inputData"]["input"][0]["source"]) for _, _, body in compute_calls)
    with wave.open(io.BytesIO(base64.b64decode(result["audio_base64"])), "rb") as w:
        assert w.getnframes() == total


def _float_wav(samples: int, rate: int = 22050) -> bytes:
    """IEEE-float (format tag 3) mono WAV, the format Bhashini TTS actually returns."""
    fmt = struct.pack("<HHIIHH", 3, 1, rate, rate * 4, 4, 32)
    data = struct.pack(f"<{samples}f", *([0.25] * samples))
    return (
        b"RIFF" + struct.pack("<I", 4 + 8 + len(fmt) + 8 + len(data)) + b"WAVE"
        + b"fmt " + struct.pack("<I", len(fmt)) + fmt
        + b"data" + struct.pack("<I", len(data)) + data
    )


def test_float_wavs_are_joined_and_report_their_sample_rate():
    joined, rate = bhashini.concat_wavs([_float_wav(100), _float_wav(50)])
    assert rate == 22050
    fmt, frames = bhashini._parse_wav(joined)
    assert struct.unpack("<HHIIHH", fmt[:16]) == (3, 1, 22050, 88200, 4, 32)
    assert len(frames) == 150 * 4
    assert bhashini._wav_rate(_float_wav(10, rate=16000)) == 16000


def test_mismatched_wav_formats_are_an_upstream_error():
    with pytest.raises(bhashini.SpeechUpstreamError):
        bhashini.concat_wavs([_float_wav(10), _wav(10)])


def test_split_keeps_indic_sentences_and_hard_wraps_run_ons():
    assert bhashini.split_for_tts("पहला वाक्य। दूसरा वाक्य।", limit=12) == ["पहला वाक्य।", "दूसरा वाक्य।"]
    chunks = bhashini.split_for_tts("word " * 200, limit=50)
    assert all(len(c) <= 50 for c in chunks)
    assert bhashini.split_for_tts("   ") == []


def test_asr_returns_trimmed_transcript_and_sample_rate_from_wav():
    fake = FakeBhashini()
    audio = base64.b64encode(_wav(1600, rate=16000)).decode()
    result = bhashini.transcribe(audio, "hi-IN", client=fake.client())
    task = fake.calls[1][2]["pipelineTasks"][0]
    assert task["config"]["audioFormat"] == "wav"
    assert task["config"]["samplingRate"] == 16000
    assert fake.calls[1][2]["inputData"]["audio"][0]["audioContent"] == audio
    assert result["transcript"] == "कल बारिश होगी?"
    assert result["language"] == "hi"


def test_unconfigured_is_reported_not_guessed(monkeypatch):
    monkeypatch.delenv("BHASHINI_USER_ID")
    assert not bhashini.is_configured()
    with pytest.raises(bhashini.SpeechUnavailable):
        bhashini.synthesize("hello", "en", client=FakeBhashini().client())


def test_unserved_language_and_bad_credentials_are_unavailable():
    with pytest.raises(bhashini.SpeechUnavailable):
        bhashini.synthesize("hello", "ta", client=FakeBhashini(languages=("hi",)).client())
    bhashini.clear_cache()
    with pytest.raises(bhashini.SpeechUnavailable):
        bhashini.synthesize("hello", "hi", client=FakeBhashini(config_status=401).client())
    with pytest.raises(bhashini.SpeechUnavailable):
        bhashini.normalize_language("fr")


def test_invalid_audio_is_rejected_before_any_call():
    fake = FakeBhashini()
    with pytest.raises(ValueError):
        bhashini.transcribe("not base64!!", "hi", client=fake.client())
    with pytest.raises(ValueError):
        bhashini.transcribe(base64.b64encode(b"x").decode(), "hi", audio_format="ogg", client=fake.client())
    assert fake.calls == []


# ---------------------------------------------------------------------------
# HTTP layer

client = TestClient(app)


def test_health_reports_configuration_without_secrets():
    data = client.get("/v2/speech/health").json()
    assert data["configured"] is True
    assert "hi" in data["languages"]
    assert "ulca-key" not in json.dumps(data)


def test_tts_endpoint_maps_errors(monkeypatch):
    def unavailable(*_a, **_k):
        raise bhashini.SpeechUnavailable("not configured")

    def upstream(*_a, **_k):
        raise bhashini.SpeechUpstreamError("HTTP 500")

    monkeypatch.setattr(bhashini, "synthesize", unavailable)
    resp = client.post("/v2/speech/tts", json={"text": "hi", "language": "hi"})
    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "speech_unavailable"

    monkeypatch.setattr(bhashini, "synthesize", upstream)
    resp = client.post("/v2/speech/tts", json={"text": "hi", "language": "hi"})
    assert resp.status_code == 502
    assert resp.json()["detail"]["code"] == "speech_upstream_error"

    assert client.post("/v2/speech/tts", json={"text": "", "language": "hi"}).status_code == 422


def test_asr_endpoint_success(monkeypatch):
    monkeypatch.setattr(bhashini, "transcribe", lambda *a, **k: {"transcript": "rain?", "language": "en", "provider": "bhashini"})
    resp = client.post("/v2/speech/asr", json={"audio_base64": "A" * 32, "language": "en"})
    assert resp.status_code == 200
    assert resp.json()["transcript"] == "rain?"
