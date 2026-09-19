"""Typed configuration loader for WeatherNext and Jev expansion.

This module centralizes all environment handling with validation, precedence
(production env vars > local .env), and explicit failure modes. It implements
the contracts described in weathernext_3_integration_plan.md section 4a and
jev_backend_plan.md section 6.

Security:
- No secrets are logged.
- GOOGLE_APPLICATION_CREDENTIALS is a file path, not JSON.
- OAuth requires client_id + secret + refresh_token; client_id alone fails validation.
- Placeholder values starting with "your_" are treated as unset.
- Disabled mode performs no Google authentication.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_placeholder(value: str | None) -> bool:
    if not value:
        return True
    v = value.strip()
    if not v:
        return True
    if v.startswith("your_"):
        return True
    if v.lower() in {"replace-me", "replace", "placeholder"}:
        return True
    return False

def _get_env(key: str, default: str | None = None) -> str | None:
    val = os.getenv(key, default)
    if val is None:
        return None
    if _is_placeholder(val):
        return None
    return val.strip()

def _get_env_raw(key: str, default: str | None = None) -> str | None:
    """Get env without placeholder filtering (for explicit placeholder detection)."""
    val = os.getenv(key, default)
    if val is None:
        return None
    return val.strip() or None

def _bool_env(key: str, default: bool) -> bool:
    val = os.getenv(key)
    if val is None:
        return default
    return val.strip() not in ("0", "false", "False", "")

def _int_env(key: str, default: int) -> int:
    val = _get_env(key)
    if val is None:
        return default
    try:
        return int(val)
    except ValueError:
        return default

# ---------------------------------------------------------------------------
# WeatherNext config
# ---------------------------------------------------------------------------

WeatherNextAuthMode = Literal["adc", "oauth"]
WeatherNextSurface = Literal["bigquery", "gcs_statistics"]

@dataclass(frozen=True)
class WeatherNextBQConfig:
    location: str = "US"
    surface_table: Optional[str] = None
    station_table: Optional[str] = None
    max_bytes_billed: int = 100_000_000

@dataclass(frozen=True)
class WeatherNextGCSConfig:
    ensemble_root: str = "gs://weathernext3_spatial/weathernext_3_0_0/zarr/"
    statistics_root: str = "gs://weathernext3_statistics_spatial/weathernext_3_0_0_statistics/zarr/"
    user_project: Optional[str] = None

@dataclass(frozen=True)
class GoogleOAuthConfig:
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    refresh_token: Optional[str] = None
    redirect_uri: Optional[str] = None

@dataclass(frozen=True)
class WeatherNextConfig:
    enabled: bool = False
    auth_mode: WeatherNextAuthMode = "adc"
    surface: WeatherNextSurface = "bigquery"
    project: Optional[str] = None
    quota_project: Optional[str] = None
    bq: WeatherNextBQConfig = field(default_factory=WeatherNextBQConfig)
    gcs: WeatherNextGCSConfig = field(default_factory=WeatherNextGCSConfig)
    ee_project: Optional[str] = None
    google_application_credentials: Optional[str] = None
    oauth: GoogleOAuthConfig = field(default_factory=GoogleOAuthConfig)

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.enabled:
            return errors  # disabled mode performs no validation of Google settings
        if self.auth_mode not in ("adc", "oauth"):
            errors.append(f"WEATHERNEXT_AUTH_MODE must be 'adc' or 'oauth', got '{self.auth_mode}'")
        if self.surface not in ("bigquery", "gcs_statistics"):
            errors.append(f"WEATHERNEXT_SURFACE must be 'bigquery' or 'gcs_statistics', got '{self.surface}'")
        # Project IDs are required when enabled
        if not self.project:
            errors.append("GOOGLE_CLOUD_PROJECT is required when WEATHERNEXT_ENABLED=1")
        if not self.quota_project:
            # quota project may be same as project, but warn if missing
            pass
        # BQ validation
        if self.surface == "bigquery":
            if not self.bq.surface_table:
                errors.append("WEATHERNEXT_BQ_SURFACE_TABLE is required for BigQuery surface")
            if self.bq.max_bytes_billed <= 0:
                errors.append("WEATHERNEXT_BQ_MAX_BYTES_BILLED must be positive")
        # GCS validation
        if self.gcs.ensemble_root and not self.gcs.ensemble_root.startswith("gs://"):
            errors.append("WEATHERNEXT_GCS_ENSEMBLE_ROOT must start with gs://")
        if self.gcs.statistics_root and not self.gcs.statistics_root.startswith("gs://"):
            errors.append("WEATHERNEXT_GCS_STATISTICS_ROOT must start with gs://")
        # Auth mode specific
        if self.auth_mode == "adc":
            # GOOGLE_APPLICATION_CREDENTIALS if set must be a file path, not JSON
            if self.google_application_credentials:
                cred = self.google_application_credentials
                if cred.strip().startswith("{"):
                    errors.append("GOOGLE_APPLICATION_CREDENTIALS must be a file path, not JSON contents")
                elif not Path(cred).is_absolute() and not cred.startswith("/run/"):
                    # allow relative for testing, but warn if looks like placeholder
                    pass
        elif self.auth_mode == "oauth":
            if not self.oauth.client_id:
                errors.append("GOOGLE_OAUTH_CLIENT_ID is required for oauth mode")
            if not self.oauth.client_secret:
                errors.append("GOOGLE_OAUTH_CLIENT_SECRET is required for oauth mode")
            if not self.oauth.refresh_token:
                errors.append("GOOGLE_OAUTH_REFRESH_TOKEN is required for oauth mode (client_id+secret alone insufficient)")
            # Redirect URI should be HTTPS and match authorized URI
            if self.oauth.redirect_uri and not self.oauth.redirect_uri.startswith("https://"):
                errors.append("GOOGLE_OAUTH_REDIRECT_URI must be https://")
        return errors

def load_weathernext_config() -> WeatherNextConfig:
    enabled = os.getenv("WEATHERNEXT_ENABLED", "0") == "1"
    auth_mode_raw = _get_env("WEATHERNEXT_AUTH_MODE", "adc") or "adc"
    auth_mode: WeatherNextAuthMode = "adc" if auth_mode_raw not in ("adc", "oauth") else auth_mode_raw  # type: ignore
    surface_raw = _get_env("WEATHERNEXT_SURFACE", "bigquery") or "bigquery"
    surface: WeatherNextSurface = "bigquery" if surface_raw not in ("bigquery", "gcs_statistics") else surface_raw  # type: ignore

    project = _get_env("GOOGLE_CLOUD_PROJECT")
    quota_project = _get_env("GOOGLE_CLOUD_QUOTA_PROJECT") or project

    bq_location = _get_env("WEATHERNEXT_BQ_LOCATION", "US") or "US"
    bq_surface_table = _get_env("WEATHERNEXT_BQ_SURFACE_TABLE")
    bq_station_table = _get_env("WEATHERNEXT_BQ_STATION_TABLE")
    bq_max_bytes = _int_env("WEATHERNEXT_BQ_MAX_BYTES_BILLED", 100_000_000)

    gcs_ensemble = _get_env("WEATHERNEXT_GCS_ENSEMBLE_ROOT", "gs://weathernext3_spatial/weathernext_3_0_0/zarr/") or "gs://weathernext3_spatial/weathernext_3_0_0/zarr/"
    gcs_stats = _get_env("WEATHERNEXT_GCS_STATISTICS_ROOT", "gs://weathernext3_statistics_spatial/weathernext_3_0_0_statistics/zarr/") or "gs://weathernext3_statistics_spatial/weathernext_3_0_0_statistics/zarr/"
    gcs_user_project = _get_env("WEATHERNEXT_GCS_USER_PROJECT") or quota_project

    ee_project = _get_env("WEATHERNEXT_EE_PROJECT")

    google_creds_path = _get_env_raw("GOOGLE_APPLICATION_CREDENTIALS")
    if google_creds_path and _is_placeholder(google_creds_path):
        google_creds_path = None

    oauth = GoogleOAuthConfig(
        client_id=_get_env("GOOGLE_OAUTH_CLIENT_ID"),
        client_secret=_get_env("GOOGLE_OAUTH_CLIENT_SECRET"),
        refresh_token=_get_env("GOOGLE_OAUTH_REFRESH_TOKEN"),
        redirect_uri=_get_env("GOOGLE_OAUTH_REDIRECT_URI"),
    )

    return WeatherNextConfig(
        enabled=enabled,
        auth_mode=auth_mode,
        surface=surface,
        project=project,
        quota_project=quota_project,
        bq=WeatherNextBQConfig(
            location=bq_location,
            surface_table=bq_surface_table,
            station_table=bq_station_table,
            max_bytes_billed=bq_max_bytes,
        ),
        gcs=WeatherNextGCSConfig(
            ensemble_root=gcs_ensemble,
            statistics_root=gcs_stats,
            user_project=gcs_user_project,
        ),
        ee_project=ee_project,
        google_application_credentials=google_creds_path,
        oauth=oauth,
    )

# ---------------------------------------------------------------------------
# Provider priority config
# ---------------------------------------------------------------------------

ProviderName = Literal["imd", "weathernext", "accuweather", "open_meteo"]

DEFAULT_PROVIDER_PRIORITY: list[ProviderName] = ["imd", "weathernext", "accuweather", "open_meteo"]

def load_provider_priority() -> tuple[list[ProviderName], list[str]]:
    """Returns (priority list, errors). Validates without duplicates/unknowns."""
    raw = _get_env("WEATHER_PROVIDER_PRIORITY", ",".join(DEFAULT_PROVIDER_PRIORITY)) or ",".join(DEFAULT_PROVIDER_PRIORITY)
    parts = [p.strip().lower() for p in raw.split(",") if p.strip()]
    # Normalize open-meteo variants
    normalized: list[str] = []
    for p in parts:
        if p in ("open_meteo", "open-meteo", "openmeteo"):
            normalized.append("open_meteo")
        else:
            normalized.append(p)
    errors: list[str] = []
    allowed = {"imd", "weathernext", "accuweather", "open_meteo"}
    seen = set()
    result: list[ProviderName] = []
    for name in normalized:
        if name not in allowed:
            errors.append(f"Unknown provider in WEATHER_PROVIDER_PRIORITY: {name}")
            continue
        if name in seen:
            errors.append(f"Duplicate provider in WEATHER_PROVIDER_PRIORITY: {name}")
            continue
        seen.add(name)
        result.append(name)  # type: ignore
    # If errors or empty, fall back to default but report errors
    if not result:
        result = DEFAULT_PROVIDER_PRIORITY.copy()
    # Ensure all required are present? The spec says required order imd,weathernext,accuweather,open_meteo
    # We allow custom order but must contain those 4 for default behavior
    return result, errors

# ---------------------------------------------------------------------------
# Jev / TypeSafe extended config
# ---------------------------------------------------------------------------

JevWeatherNextMode = Literal["off", "shadow", "enforce"]

@dataclass(frozen=True)
class JevConfig:
    # Existing settings (preserved)
    enabled: bool = True
    model: str = "jev-latest"
    base_url: str = "https://api.typesafe.ai/v1"
    timeout_seconds: float = 4.0
    max_attempts: int = 3
    retry_backoff_seconds: float = 0.4
    chat_routing: bool = True
    intent_min_confidence: float = 0.55
    advisory_min_confidence: float = 0.55
    abuse_min_probability: float = 0.85
    reply_check: bool = False
    reply_min_probability: float = 0.15
    reply_timeout_seconds: float = 3.0
    log_calls: bool = False
    # New expansion controls
    weathernext_mode: JevWeatherNextMode = "off"
    decision_features: list[str] = field(default_factory=list)
    total_budget_ms: int = 4000
    max_calls_per_request: int = 2
    max_questions_per_call: int = 24
    max_state_chars: int = 7000
    decision_audit_enabled: bool = True
    decision_audit_retention_days: int = 7
    decision_log_raw_payloads: bool = False

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.weathernext_mode not in ("off", "shadow", "enforce"):
            errors.append(f"TYPESAFE_WEATHERNEXT_MODE must be off|shadow|enforce, got {self.weathernext_mode}")
        if self.total_budget_ms <= 0:
            errors.append("TYPESAFE_TOTAL_BUDGET_MS must be positive")
        if self.max_calls_per_request <= 0:
            errors.append("TYPESAFE_MAX_CALLS_PER_REQUEST must be positive")
        if self.max_questions_per_call <= 0 or self.max_questions_per_call > 100:
            errors.append("TYPESAFE_MAX_QUESTIONS_PER_CALL must be 1..100")
        if self.max_state_chars <= 0 or self.max_state_chars > 15000:
            errors.append("TYPESAFE_MAX_STATE_CHARS must be 1..15000")
        if self.decision_log_raw_payloads and not self.decision_audit_enabled:
            errors.append("TYPESAFE_DECISION_LOG_RAW_PAYLOADS requires audit enabled")
        # Decision features must be known IDs - validation done against registry at runtime
        return errors

def load_jev_config() -> JevConfig:
    enabled = os.getenv("TYPESAFE_ENABLED", "1") != "0"
    model = _get_env("TYPESAFE_MODEL", "jev-latest") or "jev-latest"
    base_url = _get_env("TYPESAFE_BASE_URL", "https://api.typesafe.ai/v1") or "https://api.typesafe.ai/v1"
    timeout = float(os.getenv("TYPESAFE_TIMEOUT_SECONDS", "4") or "4")
    max_attempts = _int_env("TYPESAFE_MAX_ATTEMPTS", 3)
    backoff = float(os.getenv("TYPESAFE_RETRY_BACKOFF_SECONDS", "0.4") or "0.4")
    chat_routing = os.getenv("TYPESAFE_CHAT_ROUTING", "1") != "0"
    intent_min = float(os.getenv("TYPESAFE_INTENT_MIN_CONFIDENCE", "0.55") or "0.55")
    advisory_min = float(os.getenv("TYPESAFE_ADVISORY_MIN_CONFIDENCE", "0.55") or "0.55")
    abuse_min = float(os.getenv("TYPESAFE_ABUSE_MIN_PROBABILITY", "0.85") or "0.85")
    reply_check = os.getenv("TYPESAFE_REPLY_CHECK", "0") == "1"
    reply_min = float(os.getenv("TYPESAFE_REPLY_MIN_PROBABILITY", "0.15") or "0.15")
    reply_timeout = float(os.getenv("TYPESAFE_REPLY_TIMEOUT_SECONDS", "3") or "3")
    log_calls = os.getenv("TYPESAFE_LOG_CALLS", "0") == "1"

    weathernext_mode_raw = _get_env("TYPESAFE_WEATHERNEXT_MODE", "off") or "off"
    weathernext_mode: JevWeatherNextMode = weathernext_mode_raw if weathernext_mode_raw in ("off", "shadow", "enforce") else "off"  # type: ignore

    decision_features_raw = _get_env("TYPESAFE_DECISION_FEATURES", "") or ""
    decision_features = [f.strip() for f in decision_features_raw.split(",") if f.strip()] if decision_features_raw else []

    total_budget = _int_env("TYPESAFE_TOTAL_BUDGET_MS", 4000)
    max_calls = _int_env("TYPESAFE_MAX_CALLS_PER_REQUEST", 2)
    max_questions = _int_env("TYPESAFE_MAX_QUESTIONS_PER_CALL", 24)
    max_state = _int_env("TYPESAFE_MAX_STATE_CHARS", 7000)
    audit_enabled = os.getenv("TYPESAFE_DECISION_AUDIT_ENABLED", "1") != "0"
    audit_retention = _int_env("TYPESAFE_DECISION_AUDIT_RETENTION_DAYS", 7)
    log_raw = os.getenv("TYPESAFE_DECISION_LOG_RAW_PAYLOADS", "0") == "1"

    return JevConfig(
        enabled=enabled,
        model=model,
        base_url=base_url,
        timeout_seconds=timeout,
        max_attempts=max_attempts,
        retry_backoff_seconds=backoff,
        chat_routing=chat_routing,
        intent_min_confidence=intent_min,
        advisory_min_confidence=advisory_min,
        abuse_min_probability=abuse_min,
        reply_check=reply_check,
        reply_min_probability=reply_min,
        reply_timeout_seconds=reply_timeout,
        log_calls=log_calls,
        weathernext_mode=weathernext_mode,
        decision_features=decision_features,
        total_budget_ms=total_budget,
        max_calls_per_request=max_calls,
        max_questions_per_call=max_questions,
        max_state_chars=max_state,
        decision_audit_enabled=audit_enabled,
        decision_audit_retention_days=audit_retention,
        decision_log_raw_payloads=log_raw,
    )

# ---------------------------------------------------------------------------
# Combined config singleton
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AppConfig:
    weathernext: WeatherNextConfig
    provider_priority: list[ProviderName]
    provider_priority_errors: list[str]
    jev: JevConfig

def load_app_config() -> AppConfig:
    wn = load_weathernext_config()
    priority, errors = load_provider_priority()
    jev = load_jev_config()
    return AppConfig(
        weathernext=wn,
        provider_priority=priority,
        provider_priority_errors=errors,
        jev=jev,
    )

# Global cached config (reloadable for tests)
_config_cache: Optional[AppConfig] = None

def get_config() -> AppConfig:
    global _config_cache
    if _config_cache is None:
        _config_cache = load_app_config()
    return _config_cache

def reload_config() -> AppConfig:
    global _config_cache
    _config_cache = load_app_config()
    return _config_cache
