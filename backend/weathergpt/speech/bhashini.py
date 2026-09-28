"""Bhashini (MeitY ULCA / Dhruva) speech services — TTS and ASR for the mobile app.

Flow (https://bhashini.gitbook.io/bhashini-apis/):
    1. Pipeline config call  POST {config_url}   headers: userID, ulcaApiKey
       body: {"pipelineTasks": [{"taskType": "tts"|"asr", "config": {"language": {"sourceLanguage": "hi"}}}],
              "pipelineRequestConfig": {"pipelineId": ...}}
       -> serviceId per task/language + pipelineInferenceAPIEndPoint {callbackUrl, inferenceApiKey{name,value}}
    2. Pipeline compute call POST {callbackUrl}  header: {inferenceApiKey.name: inferenceApiKey.value}
       TTS -> pipelineResponse[0].audio[0].audioContent (base64 WAV)
       ASR -> pipelineResponse[0].output[0].source (transcript)

Credentials stay server-side (env): BHASHINI_USER_ID, BHASHINI_ULCA_API_KEY and optionally
BHASHINI_PIPELINE_ID. Config responses are cached per (task, language) so a warm instance makes
one config call per language, not one per utterance.
"""

from __future__ import annotations

import base64
import io
import re
import threading
import time
import wave
from dataclasses import dataclass

from weathergpt import http
from weathergpt.config import settings

CONFIG_URL = "https://meity-auth.ulcacontrib.org/ulca/apis/v0/model/getModelsPipeline"
# MeitY's public ASR / NMT / TTS pipeline.
DEFAULT_PIPELINE_ID = "64392f96daac500b55c543cd"
CONFIG_TTL_S = 60 * 60
TIMEOUT_S = 25.0

# Languages the app ships (ISO-639-1, as Bhashini expects).
SUPPORTED_LANGUAGES = ("en", "hi", "gu", "mr", "ta", "te", "kn", "ml", "bn")

# TTS models degrade on long inputs; long answers are split and the WAVs concatenated.
TTS_CHUNK_CHARS = 380
TTS_MAX_CHARS = 2400
# Vercel caps request bodies at ~4.5 MB; 16 kHz mono PCM is ~32 KB/s.
ASR_MAX_BYTES = 3_000_000


class SpeechUnavailable(RuntimeError):
    """Bhashini is not configured, or does not serve this task/language."""


class SpeechUpstreamError(RuntimeError):
    """Bhashini was reached but the call failed."""


@dataclass(frozen=True)
class _Service:
    service_id: str
    callback_url: str
    auth_name: str
    auth_value: str
    expires_at: float


def _credentials() -> tuple[str, str] | None:
    cfg = settings()
    if not cfg.bhashini_user_id or not cfg.bhashini_api_key:
        return None
    return cfg.bhashini_user_id, cfg.bhashini_api_key


def is_configured() -> bool:
    return _credentials() is not None


def pipeline_id() -> str:
    return settings().bhashini_pipeline_id or DEFAULT_PIPELINE_ID


def normalize_language(language: str | None) -> str:
    code = (language or "en").strip().lower().replace("_", "-").split("-")[0]
    if code not in SUPPORTED_LANGUAGES:
        raise SpeechUnavailable(f"language '{language}' is not supported")
    return code


_cache: dict[tuple[str, str], _Service] = {}
_cache_lock = threading.Lock()


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _resolve_service(task: str, language: str) -> _Service:
    now = time.time()
    with _cache_lock:
        hit = _cache.get((task, language))
        if hit is not None and hit.expires_at > now:
            return hit

    creds = _credentials()
    if creds is None:
        raise SpeechUnavailable("Bhashini credentials are not configured")
    user, key = creds
    body = {
        "pipelineTasks": [{"taskType": task, "config": {"language": {"sourceLanguage": language}}}],
        "pipelineRequestConfig": {"pipelineId": pipeline_id()},
    }
    try:
        resp = http.send("POST", CONFIG_URL, body=body, headers={"userID": user, "ulcaApiKey": key}, timeout=TIMEOUT_S)
    except http.UpstreamError as exc:
        raise SpeechUpstreamError(f"Bhashini config call failed: {exc.reason}") from exc
    if resp.status in (401, 403):
        raise SpeechUnavailable("Bhashini rejected the configured credentials")
    if resp.status >= 400:
        raise SpeechUpstreamError(f"Bhashini config call returned HTTP {resp.status}")
    data = resp.json()

    service_id = None
    for task_cfg in data.get("pipelineResponseConfig") or []:
        if task_cfg.get("taskType") != task:
            continue
        for option in task_cfg.get("config") or []:
            if (option.get("language") or {}).get("sourceLanguage") == language and option.get("serviceId"):
                service_id = option["serviceId"]
                break
    endpoint = data.get("pipelineInferenceAPIEndPoint") or {}
    api_key = endpoint.get("inferenceApiKey") or {}
    if not service_id or not endpoint.get("callbackUrl") or not api_key.get("value"):
        raise SpeechUnavailable(f"Bhashini has no {task} service for '{language}'")

    service = _Service(
        service_id=service_id,
        callback_url=endpoint["callbackUrl"],
        auth_name=api_key.get("name") or "Authorization",
        auth_value=api_key["value"],
        expires_at=now + CONFIG_TTL_S,
    )
    with _cache_lock:
        _cache[(task, language)] = service
    return service


def _compute(service: _Service, payload: dict) -> dict:
    try:
        resp = http.send("POST", service.callback_url, body=payload,
                         headers={service.auth_name: service.auth_value}, timeout=TIMEOUT_S)
    except http.UpstreamError as exc:
        raise SpeechUpstreamError(f"Bhashini inference failed: {exc.reason}") from exc
    if resp.status >= 400:
        raise SpeechUpstreamError(f"Bhashini inference returned HTTP {resp.status}")
    return resp.json()


# ---------------------------------------------------------------------------
# TTS


def split_for_tts(text: str, limit: int = TTS_CHUNK_CHARS) -> list[str]:
    """Sentence-aware chunks no longer than `limit` (Indic danda counts as a stop)."""
    clean = re.sub(r"\s+", " ", text).strip()
    if not clean:
        return []
    sentences = re.split(r"(?<=[.!?।॥])\s+", clean)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        while len(sentence) > limit:  # a single run-on sentence: hard wrap on a space
            cut = sentence.rfind(" ", 0, limit)
            cut = cut if cut > limit // 2 else limit
            piece, sentence = sentence[:cut].strip(), sentence[cut:].strip()
            if current:
                chunks.append(current)
                current = ""
            chunks.append(piece)
        if not sentence:
            continue
        if current and len(current) + 1 + len(sentence) > limit:
            chunks.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        chunks.append(current)
    return chunks


def concat_wavs(parts: list[bytes]) -> tuple[bytes, int]:
    """Joins WAV byte strings that share one format; returns (wav bytes, sample rate)."""
    out = io.BytesIO()
    params = None
    with wave.open(out, "wb") as writer:
        for part in parts:
            with wave.open(io.BytesIO(part), "rb") as reader:
                p = reader.getparams()
                if params is None:
                    params = p
                    writer.setnchannels(p.nchannels)
                    writer.setsampwidth(p.sampwidth)
                    writer.setframerate(p.framerate)
                elif (p.nchannels, p.sampwidth, p.framerate) != (params.nchannels, params.sampwidth, params.framerate):
                    raise SpeechUpstreamError("Bhashini returned audio chunks in different formats")
                writer.writeframes(reader.readframes(reader.getnframes()))
    if params is None:
        raise SpeechUpstreamError("Bhashini returned no audio")
    return out.getvalue(), params.framerate


def synthesize(text: str, language: str, gender: str = "female") -> dict:
    lang = normalize_language(language)
    voice = gender if gender in ("male", "female") else "female"
    chunks = split_for_tts(text[:TTS_MAX_CHARS])
    if not chunks:
        raise ValueError("text is empty")

    service = _resolve_service("tts", lang)
    wavs: list[bytes] = []
    for chunk in chunks:
        data = _compute(service, {
            "pipelineTasks": [{
                "taskType": "tts",
                "config": {"language": {"sourceLanguage": lang}, "serviceId": service.service_id, "gender": voice},
            }],
            "inputData": {"input": [{"source": chunk}], "audio": [{"audioContent": None}]},
        })
        try:
            content = data["pipelineResponse"][0]["audio"][0]["audioContent"]
            wavs.append(base64.b64decode(content))
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise SpeechUpstreamError("Bhashini TTS response had no audio") from exc

    audio, rate = (wavs[0], _wav_rate(wavs[0])) if len(wavs) == 1 else concat_wavs(wavs)
    return {
        "audio_base64": base64.b64encode(audio).decode("ascii"),
        "audio_format": "wav",
        "sample_rate": rate,
        "language": lang,
        "gender": voice,
        "chunks": len(chunks),
        "truncated": len(text) > TTS_MAX_CHARS,
        "provider": "bhashini",
        "service_id": service.service_id,
    }


def _wav_rate(data: bytes) -> int | None:
    try:
        with wave.open(io.BytesIO(data), "rb") as reader:
            return reader.getframerate()
    except (wave.Error, EOFError):
        return None


# ---------------------------------------------------------------------------
# ASR


def transcribe(audio_base64: str, language: str, audio_format: str = "wav", sampling_rate: int | None = None) -> dict:
    lang = normalize_language(language)
    fmt = (audio_format or "wav").lower()
    if fmt not in ("wav", "flac", "mp3"):
        raise ValueError(f"audio_format '{audio_format}' is not supported (wav, flac, mp3)")
    try:
        raw = base64.b64decode(audio_base64, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("audio_base64 is not valid base64") from exc
    if not raw:
        raise ValueError("audio is empty")
    if len(raw) > ASR_MAX_BYTES:
        raise ValueError("audio is too long; keep questions under ~45 seconds")
    rate = sampling_rate or (_wav_rate(raw) if fmt == "wav" else None) or 16000

    service = _resolve_service("asr", lang)
    data = _compute(service, {
        "pipelineTasks": [{
            "taskType": "asr",
            "config": {
                "language": {"sourceLanguage": lang},
                "serviceId": service.service_id,
                "audioFormat": fmt,
                "samplingRate": rate,
            },
        }],
        "inputData": {"audio": [{"audioContent": audio_base64}]},
    })
    try:
        transcript = (data["pipelineResponse"][0]["output"][0]["source"] or "").strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise SpeechUpstreamError("Bhashini ASR response had no transcript") from exc
    return {
        "transcript": transcript,
        "language": lang,
        "sampling_rate": rate,
        "provider": "bhashini",
        "service_id": service.service_id,
    }
