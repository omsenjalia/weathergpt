"""POST /chat (and /voice) — shared by the web app and both mobile apps.

Request (unknown fields ignored):
    message            latest user text (mobile)            messages   [{role, content}] history (web + mobile)
    location           place label                           lat, lon   device coordinates (mobile)
    language           ISO code ("hi") or name ("Hindi"); Accept-Language is used when absent/English
    mode               everyone | farmer | researcher (authoritative); farmer_mode is the legacy flag
    crop, growth_stage, soil, irrigation   farm context (used only in farmer mode)
    requested_source   auto | imd | weathernext | open_meteo (alias: source)
Response:
    {response: markdown, meta: {...}, card: {...} | null}
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, field_validator

from weathergpt.ai import chat as orchestrator
from weathergpt.api.common import resolve_mode, resolve_source

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    model_config = {"extra": "ignore"}

    message: str = ""
    messages: list[dict] = Field(default_factory=list)
    location: str = ""
    lat: Optional[float] = Field(default=None, ge=-90, le=90)
    lon: Optional[float] = Field(default=None, ge=-180, le=180)
    language: str = ""
    mode: Optional[str] = None
    farmer_mode: bool = False
    crop: str = ""
    growth_stage: str = ""
    soil: str = ""
    irrigation: str = ""
    requested_source: Optional[str] = None
    source: Optional[str] = None
    client: str = ""

    @field_validator("message", "location", "language", "crop", "growth_stage", "soil", "irrigation", "client",
                     mode="before")
    @classmethod
    def _strings(cls, v: Any) -> str:
        return "" if v is None else str(v)[:4000]

    @field_validator("messages", mode="before")
    @classmethod
    def _history(cls, v: Any) -> list[dict]:
        if not isinstance(v, list):
            return []
        out = []
        for item in v[-20:]:
            if isinstance(item, dict) and item.get("role") in ("user", "assistant") and item.get("content"):
                out.append({"role": item["role"], "content": str(item["content"])[:4000]})
        return out


def _client_kind(req: ChatRequest, user_agent: str) -> str:
    hint = req.client.strip().lower()
    if hint in ("web", "browser"):
        return "web"
    if hint in ("mobile", "app", "android", "ios"):
        return "mobile"
    if req.lat is not None and req.lon is not None:
        return "mobile"
    ua = user_agent.lower()
    if "okhttp" in ua or "expo" in ua or "reactnative" in ua or "dart" in ua:
        return "mobile"
    return "web" if "mozilla" in ua else "unknown"


def _turn(req: ChatRequest, http_request: Request) -> orchestrator.ChatTurn:
    mode = resolve_mode(req.mode, req.farmer_mode)
    farm = {"crop": req.crop.strip(), "growth_stage": req.growth_stage.strip(), "soil": req.soil.strip(),
            "irrigation": req.irrigation.strip()} if mode == "farmer" else {}
    return orchestrator.ChatTurn(
        message=req.message,
        history=req.messages,
        language=orchestrator.language_code(req.language, http_request.headers.get("accept-language")),
        location=req.location.replace("[Farmer Mode Active]", "").strip(),
        lat=req.lat, lon=req.lon, mode=mode,
        requested_source=resolve_source(req.requested_source, req.source),
        farm={k: v for k, v in farm.items() if v},
        client=_client_kind(req, http_request.headers.get("user-agent") or ""),
    )


async def _handle(req: ChatRequest, http_request: Request) -> dict:
    turn = _turn(req, http_request)
    out = await run_in_threadpool(orchestrator.run, turn)
    return {"response": out.response, "meta": orchestrator.meta_for(turn, out), "card": out.card}


@router.post("/chat")
@router.post("/chat/", include_in_schema=False)
async def chat(req: ChatRequest, http_request: Request) -> dict:
    return await _handle(req, http_request)


@router.post("/voice")
async def voice(req: ChatRequest, http_request: Request) -> dict:
    """Same pipeline as /chat; kept as a separate route so voice traffic is visible in logs."""
    return await _handle(req, http_request)
