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
import re
import struct
import threading
import time
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


def _parse_wav(data: bytes) -> tuple[bytes, bytes]:
    """Returns (fmt chunk body, sample data) from a RIFF/WAVE file.

    Parsed by hand rather than with `wave`, which rejects the IEEE-float
    (format tag 3) WAVs Bhashini TTS returns.
    """
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("not a RIFF/WAVE file")
    fmt = None
    pos = 12
    while pos + 8 <= len(data):
        chunk_id = data[pos:pos + 4]
        size = struct.unpack("<I", data[pos + 4:pos + 8])[0]
        body = data[pos + 8:pos + 8 + size]
        if chunk_id == b"fmt ":
            fmt = body
        elif chunk_id == b"data":
            if fmt is None or len(fmt) < 16:
                raise ValueError("WAV data chunk before a valid fmt chunk")
            return fmt, body
        pos += 8 + size + (size & 1)
    raise ValueError("WAV has no fmt/data chunks")


def _build_wav(fmt: bytes, frames: bytes) -> bytes:
    # A fmt body longer than 16 bytes (e.g. WAVE_FORMAT_EXTENSIBLE) is kept as-is.
    fmt_chunk = b"fmt " + struct.pack("<I", len(fmt)) + fmt + (b"\0" if len(fmt) & 1 else b"")
    data_chunk = b"data" + struct.pack("<I", len(frames)) + frames + (b"\0" if len(frames) & 1 else b"")
    return b"RIFF" + struct.pack("<I", 4 + len(fmt_chunk) + len(data_chunk)) + b"WAVE" + fmt_chunk + data_chunk


def concat_wavs(parts: list[bytes]) -> tuple[bytes, int]:
    """Joins WAV byte strings that share one format; returns (wav bytes, sample rate)."""
    fmt = None
    frames: list[bytes] = []
    for part in parts:
        try:
            part_fmt, part_frames = _parse_wav(part)
        except ValueError as exc:
            raise SpeechUpstreamError("Bhashini returned malformed audio") from exc
        # format tag, channels, sample rate, byte rate, block align, bits per sample
        if fmt is None:
            fmt = part_fmt
        elif part_fmt[:16] != fmt[:16]:
            raise SpeechUpstreamError("Bhashini returned audio chunks in different formats")
        frames.append(part_frames)
    if fmt is None:
        raise SpeechUpstreamError("Bhashini returned no audio")
    return _build_wav(fmt, b"".join(frames)), struct.unpack("<I", fmt[4:8])[0]


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
        fmt, _ = _parse_wav(data)
    except ValueError:
        return None
    return struct.unpack("<I", fmt[4:8])[0]


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
