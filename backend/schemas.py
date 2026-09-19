"""Pydantic request/response models shared by every router.

One contract, two clients:

* **Web** (`weathergpt/frontend`, axios) sends `messages` history + `location` string +
  a full language *name* ("Hindi").
* **Mobile** (`weathergpt-app`, Flutter/Dio) sends `message` (+ `messages`), `location`,
  `lat`/`lon`, an ISO language *code* ("hi") and an `Accept-Language` header.

Extended with:
- Mode contract: everyone, farmer, researcher with legacy farmer_mode compatibility
- Source constraints: auto, imd, weathernext, accuweather, open_meteo
- Optional typed weather/forecast evidence or structured cards in ChatResponse

Unknown fields are ignored so either client can evolve independently.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

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
    # New mode contract (validated, with legacy farmer_mode compat)
    mode: str = Field(default="everyone", description="everyone|farmer|researcher")
    # Source constraints (explicit researcher/source queries bypass auto substitution)
    requested_source: str = Field(default="auto", description="auto|imd|weathernext|accuweather|open_meteo")
    source: str = Field(default="auto", description="Legacy alias for requested_source")

    @field_validator("message", "location", "language", "crop", "client", "mode", "requested_source", "source", mode="before")
    @classmethod
    def normalize_text_fields(cls, value):
        return "" if value is None else str(value)

    @field_validator("messages", mode="before")
    @classmethod
    def normalize_messages(cls, value):
        if value is None:
            return []
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]

    @field_validator("mode", mode="after")
    @classmethod
    def validate_mode(cls, value):
        v = (value or "").strip().lower()
        if not v:
            return "everyone"
        if v in ("everyone", "farmer", "researcher"):
            return v
        # Legacy farmer_mode boolean mapping
        return "everyone"

    @field_validator("requested_source", "source", mode="after")
    @classmethod
    def validate_source(cls, value):
        v = (value or "").strip().lower()
        if not v:
            return "auto"
        # Normalize variants
        if v in ("open-meteo", "openmeteo"):
            v = "open_meteo"
        allowed = {"auto", "imd", "weathernext", "accuweather", "open_meteo"}
        if v in allowed:
            return v
        return "auto"


class ChatResponse(BaseModel):
    response: str
    meta: dict | None = None
    # New optional typed evidence for structured clients (preserves response/meta for old clients)
    weather_evidence: Optional[dict] = None
    forecast_evidence: Optional[list[dict]] = None
    decision_evidence: Optional[list[dict]] = None
    provenance: Optional[dict] = None
    mode: Optional[str] = None
    requested_source: Optional[str] = None
    selected_source: Optional[str] = None


class SandboxRequest(BaseModel):
    prompt: str
    location: str = "New Delhi"
    language: str = "English"
    mode: str = "everyone"
    requested_source: str = "auto"


class WeatherV2Request(BaseModel):
    model_config = {"extra": "ignore"}
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    mode: str = Field("everyone")
    requested_source: str = Field("auto")
    model: str = Field("weathernext_3")
    forecast_days: int = Field(3, ge=1, le=15)
    language: str = "en"


class DecisionEvaluateRequest(BaseModel):
    model_config = {"extra": "ignore"}
    feature_id: str
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    mode: str = Field("farmer")
    activity_id: Optional[str] = None
    crop: Optional[str] = None
    growth_stage: Optional[str] = None
    soil: Optional[str] = None
    irrigation: Optional[str] = None
    date: Optional[str] = None
    requested_source: str = Field("auto")
    timezone: str = Field("Asia/Kolkata")


ClientKind = Literal["web", "mobile", "unknown"]
ModeKind = Literal["everyone", "farmer", "researcher"]
SourceKind = Literal["auto", "imd", "weathernext", "accuweather", "open_meteo"]
