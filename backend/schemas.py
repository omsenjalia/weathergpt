"""Pydantic request/response models shared by every router.

One contract, two clients:

* **Web** (`weathergpt/frontend`, axios) sends `messages` history + `location` string +
  a full language *name* ("Hindi").
* **Mobile** (`weathergpt-app`, Flutter/Dio) sends `message` (+ `messages`), `location`,
  `lat`/`lon`, an ISO language *code* ("hi") and an `Accept-Language` header.

Unknown fields are ignored so either client can evolve independently.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model_config = {"extra": "ignore"}

    message: str = ""
    messages: list[dict] = Field(default_factory=list)
    location: str = ""
    language: str = "English"
    farmer_mode: bool = False
    crop: str = ""
    lat: float | None = None
    lon: float | None = None
    client: str = ""  # optional hint: "web" | "mobile" | "app"


class ChatResponse(BaseModel):
    response: str
    meta: dict | None = None


class SandboxRequest(BaseModel):
    prompt: str
    location: str = "New Delhi"
    language: str = "English"


ClientKind = Literal["web", "mobile", "unknown"]
