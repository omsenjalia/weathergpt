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

from pydantic import BaseModel, Field, field_validator


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
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    client: str = ""  # optional hint: "web" | "mobile" | "app"

    @field_validator("message", "location", "language", "crop", "client", mode="before")
    @classmethod
    def normalize_text_fields(cls, value):
        # JSON nulls and non-string scalar values should not crash routing or .strip().
        return "" if value is None else str(value)

    @field_validator("messages", mode="before")
    @classmethod
    def normalize_messages(cls, value):
        if value is None:
            return []
        if not isinstance(value, list):
            return []
        # Keep only object-shaped history entries. Invalid entries are ignored rather
        # than causing a late 500 in the LLM adapter.
        return [item for item in value if isinstance(item, dict)]


class ChatResponse(BaseModel):
    response: str
    meta: dict | None = None


class SandboxRequest(BaseModel):
    prompt: str
    location: str = "New Delhi"
    language: str = "English"


ClientKind = Literal["web", "mobile", "unknown"]
