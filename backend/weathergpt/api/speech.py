"""Bhashini speech for the mobile apps (keys stay on the server).

GET  /v2/speech/health  -> {configured, languages, ...}
POST /v2/speech/tts     {text, language, gender?}                              -> base64 WAV
POST /v2/speech/asr     {audio_base64, language, audio_format?, sampling_rate?} -> transcript

503 {code: speech_unavailable} = not configured / language not served (client falls back to on-device)
502 {code: speech_upstream_error} = Bhashini call failed; 422 = invalid input
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from weathergpt.runtime import log_event
from weathergpt.speech import bhashini

router = APIRouter(prefix="/v2/speech", tags=["speech"])


class TtsRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=8000)
    language: str = "en"
    gender: str = "female"


class AsrRequest(BaseModel):
    audio_base64: str = Field(..., min_length=16)
    language: str = "en"
    audio_format: str = "wav"
    sampling_rate: int | None = Field(default=None, ge=8000, le=48000)


def _unavailable(message: str) -> HTTPException:
    return HTTPException(status_code=503, detail={"code": "speech_unavailable", "message": message, "provider": "bhashini"})


def _upstream(message: str) -> HTTPException:
    return HTTPException(status_code=502, detail={"code": "speech_upstream_error", "message": message, "provider": "bhashini"})


@router.get("/health")
async def speech_health() -> dict:
    return {"provider": "bhashini", "configured": bhashini.is_configured(), "pipeline_id": bhashini.pipeline_id(),
            "languages": list(bhashini.SUPPORTED_LANGUAGES), "tasks": ["tts", "asr"]}


@router.post("/tts")
async def text_to_speech(req: TtsRequest) -> dict:
    try:
        return await run_in_threadpool(bhashini.synthesize, req.text, req.language, req.gender)
    except bhashini.SpeechUnavailable as exc:
        raise _unavailable(str(exc)) from exc
    except bhashini.SpeechUpstreamError as exc:
        log_event("WARN", "Bhashini TTS failed", {"language": req.language, "error": str(exc)})
        raise _upstream(str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/asr")
async def speech_to_text(req: AsrRequest) -> dict:
    try:
        return await run_in_threadpool(bhashini.transcribe, req.audio_base64, req.language, req.audio_format,
                                       req.sampling_rate)
    except bhashini.SpeechUnavailable as exc:
        raise _unavailable(str(exc)) from exc
    except bhashini.SpeechUpstreamError as exc:
        log_event("WARN", "Bhashini ASR failed", {"language": req.language, "error": str(exc)})
        raise _upstream(str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
