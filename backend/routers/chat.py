from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool

from schemas import ChatRequest, ChatResponse
from services.chat import detect_client, language_from_header, run_chat

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
@router.post("/chat/", response_model=ChatResponse, include_in_schema=False)
async def chat(request: ChatRequest, http_request: Request) -> ChatResponse:
    """Shared conversational endpoint.

    * Web:    `{ messages, location, language, farmer_mode, crop }`
    * Mobile: `{ message, messages?, location, lat, lon, language, farmer_mode, crop }`

    Always responds `{ "response": "<markdown>", "meta": {...} }` — `meta` is additive and
    ignored by older clients.
    """
    client = detect_client(request, http_request.headers.get("user-agent"))

    # Mobile Dio sets Accept-Language; use it when the body left language at default.
    if request.language in ("", "English", "en"):
        header_lang = language_from_header(http_request.headers.get("accept-language"))
        if header_lang and header_lang.lower() not in ("en", "en-us", "en-in", "en-gb"):
            request.language = header_lang

    result = await run_in_threadpool(run_chat, request, client=client)
    meta = {"path": result.path, "client": result.client, "language": result.language,
            "location": result.location, "intent": result.intent,
            "intent_engine": result.intent_engine}
    if result.intent_confidence is not None:
        meta["intent_confidence"] = round(result.intent_confidence, 3)
    return ChatResponse(response=result.response, meta=meta)
