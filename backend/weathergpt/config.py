"""Typed settings read from the environment.

Every module reads configuration through ``settings()`` so tests can change env
vars and call ``reset_settings()``. Placeholder values (``your_*``, ``replace-me``)
count as unset, so a copied ``.env.example`` never looks configured.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from typing import Optional

PROVIDERS: tuple[str, ...] = ("imd", "weathernext", "open_meteo")
DEFAULT_PRIORITY: tuple[str, ...] = PROVIDERS
MODES: tuple[str, ...] = ("everyone", "farmer", "researcher")


def _clean(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    v = value.strip()
    if not v or v.startswith("your_") or v.lower() in {"replace-me", "replace", "placeholder", "changeme"}:
        return None
    return v


def env(key: str, default: Optional[str] = None) -> Optional[str]:
    return _clean(os.getenv(key)) or default


def env_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off")


def env_int(key: str, default: int) -> int:
    try:
        return int(env(key) or default)
    except ValueError:
        return default


def env_float(key: str, default: float) -> float:
    try:
        return float(env(key) or default)
    except ValueError:
        return default


def _hours(key: str, default: tuple[int, ...]) -> tuple[int, ...]:
    raw = env(key)
    if not raw:
        return default
    try:
        hours = sorted({int(p) for p in raw.split(",") if p.strip()})
    except ValueError:
        return default
    return tuple(h for h in hours if 0 <= h <= 23) or default


# ---------------------------------------------------------------------------
# IMD


@dataclass(frozen=True)
class IMDSettings:
    """IMD API gateway (https://api.imd.gov.in).

    The gateway rejects a request unless it carries BOTH ``X-API-Key`` and
    ``Authorization: Bearer <JWT>`` (verified against the live gateway: a key
    alone returns ``Authorization header missing or invalid``). Access is also
    IP-whitelisted by IMD, so the deployment's egress IP must be registered.

    Relay mode (``IMD_RELAY_TOKEN`` set): ``IMD_BASE_URL`` points at a relay on a host
    with a fixed, whitelisted IP (``relay/imd_relay.py``). The relay holds the key and
    account and mints JWTs itself; the backend sends only the shared secret.
    """

    api_key: Optional[str] = None
    jwt_token: Optional[str] = None
    # Registered account: the backend mints JWTs itself (they last 1 h) and renews them.
    email: Optional[str] = None
    password: Optional[str] = None
    relay_token: Optional[str] = None
    base_url: str = "https://api.imd.gov.in/api/v1"
    token_url: str = "https://api.imd.gov.in/api/oauth/token.php"
    # IMD terms prohibit redistributing its data: the raw /v2/imd/{endpoint} passthrough
    # needs X-Admin-Token unless this is explicitly enabled.
    public_proxy: bool = False
    timeout_seconds: float = 8.0
    max_station_km: float = 50.0          # auto: nearest city-forecast station must be this close
    pinned_max_station_km: float = 150.0  # requested_source=imd: accept a more distant station (labelled)
    observation_max_km: float = 35.0      # synop / AWS station used for "now" must be this close
    observation_max_age_hours: float = 4.0   # synoptic reports are 3-hourly and arrive late
    enabled: bool = True

    @property
    def relay(self) -> bool:
        return bool(self.relay_token)

    @property
    def can_mint(self) -> bool:
        return not self.relay and bool(self.email and self.password)

    @property
    def configured(self) -> bool:
        return self.enabled and (self.relay or bool(self.api_key and (self.jwt_token or self.can_mint)))

    def missing(self) -> list[str]:
        out = []
        if self.relay:
            return out
        if not self.api_key:
            out.append("IMD_API_KEY")
        if not self.jwt_token and not self.can_mint:
            out.append("IMD_EMAIL + IMD_PASSWORD (or IMD_JWT_TOKEN)")
        return out


# ---------------------------------------------------------------------------
# WeatherNext (BigQuery)

DEFAULT_BQ_MAX_BYTES_BILLED = 100 * 1024 ** 3

BQ_COLUMN_PROFILES: dict[str, tuple[str, ...]] = {
    "minimal": (
        "temperature_2m_mean", "temperature_2m_p10", "temperature_2m_p90",
        "total_precipitation_1hr_mean", "total_precipitation_1hr_p90",
        "wind_speed_10m_mean",
    ),
    "standard": (
        "temperature_2m_mean", "temperature_2m_p10", "temperature_2m_p90",
        "dewpoint_temperature_2m_mean",
        "total_precipitation_1hr_mean", "total_precipitation_1hr_p50", "total_precipitation_1hr_p90",
        "wind_speed_10m_mean", "total_cloud_cover_mean", "mean_sea_level_pressure_mean",
    ),
    "extended": (
        "temperature_2m_mean", "temperature_2m_p10", "temperature_2m_p25",
        "temperature_2m_p50", "temperature_2m_p75", "temperature_2m_p90",
        "dewpoint_temperature_2m_mean",
        "total_precipitation_1hr_mean", "total_precipitation_1hr_p10", "total_precipitation_1hr_p25",
        "total_precipitation_1hr_p50", "total_precipitation_1hr_p75", "total_precipitation_1hr_p90",
        "wind_speed_10m_mean", "wind_speed_10m_p90",
        "u_component_of_wind_10m_mean", "v_component_of_wind_10m_mean",
        "total_cloud_cover_mean", "mean_sea_level_pressure_mean",
    ),
}

# WN2 tables use ERA5-style leaf names and the mean table has no statistic suffix.
BQ_COLUMNS_WN2: tuple[str, ...] = (
    "2m_temperature", "2m_dewpoint_temperature", "total_precipitation_1hr",
    "10m_u_component_of_wind", "10m_v_component_of_wind",
    "total_cloud_cover", "mean_sea_level_pressure",
)

# The WN3 0.05 deg table only carries station-head temperature / dew point.
BQ_COLUMNS_STATION: tuple[str, ...] = (
    "station_head_temperature_2m_mean", "station_head_temperature_2m_p10", "station_head_temperature_2m_p90",
    "station_head_dewpoint_temperature_2m_mean", "station_head_dewpoint_temperature_2m_p10",
    "station_head_dewpoint_temperature_2m_p90",
)

WN3_ALIASES = {"weathernext_3", "weathernext_3_0_0", "wn3", "3", "3.0.0"}
WN2_ALIASES = {"weathernext_2", "weathernext_2_0_0", "wn2", "2", "2.0.0"}


def normalize_wn_model(model: Optional[str]) -> str:
    m = (model or "weathernext_3").strip().lower().replace("-", "_")
    if m in WN3_ALIASES:
        return "weathernext_3"
    if m in WN2_ALIASES:
        return "weathernext_2"
    raise ValueError("model must be weathernext_3 or weathernext_2")


@dataclass(frozen=True)
class WeatherNextSettings:
    enabled: bool = False
    mock_data: bool = False
    project: Optional[str] = None
    quota_project: Optional[str] = None
    location: str = "US"
    table_3: Optional[str] = None
    table_3_station: Optional[str] = None
    table_2: Optional[str] = None
    column_profile: str = "standard"
    max_bytes_billed: int = DEFAULT_BQ_MAX_BYTES_BILLED
    query_timeout_seconds: float = 25.0
    nearest_radius_km: float = 9.0
    run_hours: tuple[int, ...] = (0, 6, 12, 18)
    delivery_latency_hours: float = 7.0
    max_run_attempts: int = 3
    freshness_hours: float = 24.0
    cache_ttl_seconds: int = 3600
    max_horizon_hours: int = 360
    credentials_path: Optional[str] = None
    has_service_account_json: bool = False
    oauth_client_id: Optional[str] = None
    oauth_client_secret: Optional[str] = None
    oauth_refresh_token: Optional[str] = None

    @property
    def columns(self) -> tuple[str, ...]:
        return BQ_COLUMN_PROFILES.get(self.column_profile, BQ_COLUMN_PROFILES["standard"])

    def columns_for(self, model: str, *, station: bool = False) -> tuple[str, ...]:
        if normalize_wn_model(model) == "weathernext_2":
            return BQ_COLUMNS_WN2
        return BQ_COLUMNS_STATION if station else self.columns

    def table_for(self, model: str, *, high_resolution: bool = False) -> Optional[str]:
        if normalize_wn_model(model) == "weathernext_2":
            return self.table_2
        return self.table_3_station if high_resolution else self.table_3

    @property
    def has_oauth(self) -> bool:
        return bool(self.oauth_client_id and self.oauth_client_secret and self.oauth_refresh_token)

    def credential_sources(self) -> list[str]:
        sources = []
        if self.has_service_account_json:
            sources.append("service_account_json")
        if self.credentials_path:
            sources.append("credentials_file")
        if self.has_oauth:
            sources.append("oauth_refresh_token")
        return sources

    def problems(self) -> list[str]:
        """Configuration errors that make the provider ineligible (empty when fine)."""
        if not self.enabled or self.mock_data:
            return []
        errors = []
        if not self.project:
            errors.append("GOOGLE_CLOUD_PROJECT is required")
        if not self.table_3:
            errors.append("WEATHERNEXT_TABLE_3 is required")
        elif self.table_3.count(".") != 2:
            errors.append("WEATHERNEXT_TABLE_3 must be project.dataset.table")
        if self.credentials_path and self.credentials_path.lstrip().startswith("{"):
            errors.append("GOOGLE_APPLICATION_CREDENTIALS must be a path; put JSON in GOOGLE_APPLICATION_CREDENTIALS_JSON")
        if self.column_profile not in BQ_COLUMN_PROFILES:
            errors.append(f"WEATHERNEXT_BQ_COLUMN_PROFILE must be one of {sorted(BQ_COLUMN_PROFILES)}")
        return errors


# ---------------------------------------------------------------------------
# App


@dataclass(frozen=True)
class Settings:
    provider_priority: tuple[str, ...] = DEFAULT_PRIORITY
    supplement_enabled: bool = True
    alerts_enabled: bool = True
    imd: IMDSettings = field(default_factory=IMDSettings)
    weathernext: WeatherNextSettings = field(default_factory=WeatherNextSettings)
    groq_api_key: Optional[str] = None
    groq_model: str = "openai/gpt-oss-120b"
    groq_fallback_models: tuple[str, ...] = ("openai/gpt-oss-20b",)
    chat_timeout_seconds: float = 22.0
    chat_fast_path: bool = True
    bhashini_user_id: Optional[str] = None
    bhashini_api_key: Optional[str] = None
    bhashini_pipeline_id: str = "64392f96daac500b55c543cd"
    nominatim_user_agent: str = "WeatherGPT/3.0 (+https://github.com/omsenjalia/weathergpt)"
    # Shared secret the apps must send as X-Backend-Secret. Unset = open (local development).
    backend_secret: Optional[str] = None

    @property
    def has_llm(self) -> bool:
        return bool(self.groq_api_key)


def parse_priority(raw: Optional[str]) -> tuple[str, ...]:
    """Parse WEATHER_PROVIDER_PRIORITY. Unknown names are dropped; order is kept.

    Providers left out of the variable are *not* re-appended: an operator who
    writes ``open_meteo`` alone gets Open-Meteo alone.
    """
    if not raw:
        return DEFAULT_PRIORITY
    out: list[str] = []
    for part in raw.split(","):
        name = part.strip().lower().replace("-", "_")
        if name == "openmeteo":
            name = "open_meteo"
        if name in PROVIDERS and name not in out:
            out.append(name)
    return tuple(out) or DEFAULT_PRIORITY


def load_settings() -> Settings:
    sa_json = (os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON") or "").strip()
    project = env("GOOGLE_CLOUD_PROJECT")
    fallbacks = env("GROQ_FALLBACK_MODELS")
    return Settings(
        provider_priority=parse_priority(env("WEATHER_PROVIDER_PRIORITY")),
        supplement_enabled=env_bool("WEATHER_SUPPLEMENT_ENABLED", True),
        alerts_enabled=env_bool("WEATHER_ALERTS_ENABLED", True),
        imd=IMDSettings(
            api_key=env("IMD_API_KEY"),
            jwt_token=env("IMD_JWT_TOKEN"),
            email=env("IMD_EMAIL"),
            password=os.getenv("IMD_PASSWORD") or None,
            relay_token=os.getenv("IMD_RELAY_TOKEN") or None,
            token_url=env("IMD_TOKEN_URL") or "https://api.imd.gov.in/api/oauth/token.php",
            public_proxy=env_bool("IMD_PUBLIC_PROXY", False),
            base_url=(env("IMD_BASE_URL") or "https://api.imd.gov.in/api/v1").rstrip("/"),
            timeout_seconds=env_float("IMD_TIMEOUT_SECONDS", 8.0),
            max_station_km=env_float("IMD_MAX_STATION_KM", 50.0),
            pinned_max_station_km=env_float("IMD_PINNED_MAX_STATION_KM", 150.0),
            observation_max_km=env_float("IMD_OBSERVATION_MAX_KM", 35.0),
            observation_max_age_hours=env_float("IMD_OBSERVATION_MAX_AGE_HOURS", 4.0),
            enabled=env_bool("IMD_ENABLED", True),
        ),
        weathernext=WeatherNextSettings(
            enabled=env_bool("WEATHERNEXT_ENABLED", False),
            mock_data=env_bool("WEATHERNEXT_MOCK_DATA", False),
            project=project,
            quota_project=env("GOOGLE_CLOUD_QUOTA_PROJECT") or project,
            location=env("WEATHERNEXT_BQ_LOCATION", "US") or "US",
            table_3=env("WEATHERNEXT_TABLE_3") or env("WEATHERNEXT_BQ_SURFACE_TABLE") or env("WEATHERNEXT_TABLE"),
            table_3_station=env("WEATHERNEXT_TABLE_3_HR") or env("WEATHERNEXT_BQ_STATION_TABLE"),
            table_2=env("WEATHERNEXT_TABLE_2"),
            column_profile=(env("WEATHERNEXT_BQ_COLUMN_PROFILE", "standard") or "standard").lower(),
            max_bytes_billed=env_int("WEATHERNEXT_BQ_MAX_BYTES_BILLED", DEFAULT_BQ_MAX_BYTES_BILLED),
            query_timeout_seconds=env_float("WEATHERNEXT_QUERY_TIMEOUT_SECONDS", 25.0),
            nearest_radius_km=env_float("WEATHERNEXT_NEAREST_RADIUS_KM", 9.0),
            run_hours=_hours("WEATHERNEXT_RUN_HOURS", (0, 6, 12, 18)),
            delivery_latency_hours=env_float("WEATHERNEXT_DELIVERY_LATENCY_HOURS", 7.0),
            max_run_attempts=max(1, env_int("WEATHERNEXT_MAX_RUN_ATTEMPTS", 3)),
            freshness_hours=env_float("WEATHERNEXT_FRESHNESS_HOURS", 24.0),
            cache_ttl_seconds=env_int("WEATHERNEXT_CACHE_TTL_SECONDS", 3600),
            max_horizon_hours=env_int("WEATHERNEXT_MAX_HORIZON_HOURS", 360),
            credentials_path=env("GOOGLE_APPLICATION_CREDENTIALS"),
            has_service_account_json=sa_json.startswith("{"),
            oauth_client_id=env("GOOGLE_OAUTH_CLIENT_ID"),
            oauth_client_secret=env("GOOGLE_OAUTH_CLIENT_SECRET"),
            oauth_refresh_token=env("GOOGLE_OAUTH_REFRESH_TOKEN"),
        ),
        groq_api_key=env("GROQ_API_KEY"),
        groq_model=env("GROQ_MODEL", "openai/gpt-oss-120b") or "openai/gpt-oss-120b",
        groq_fallback_models=tuple(m.strip() for m in fallbacks.split(",") if m.strip()) if fallbacks else ("openai/gpt-oss-20b",),
        chat_timeout_seconds=env_float("CHAT_TIMEOUT_SECONDS", 22.0),
        chat_fast_path=env_bool("CHAT_FAST_PATH", True),
        bhashini_user_id=env("BHASHINI_USER_ID"),
        bhashini_api_key=env("BHASHINI_ULCA_API_KEY") or env("BHASHINI_API_KEY"),
        bhashini_pipeline_id=env("BHASHINI_PIPELINE_ID") or "64392f96daac500b55c543cd",
        nominatim_user_agent=env("NOMINATIM_USER_AGENT") or "WeatherGPT/3.0 (+https://github.com/omsenjalia/weathergpt)",
        backend_secret=env("BACKEND_SECRET"),
    )


_settings: Optional[Settings] = None
_lock = threading.Lock()


def settings() -> Settings:
    global _settings
    with _lock:
        if _settings is None:
            _settings = load_settings()
        return _settings


def reset_settings() -> None:
    global _settings
    with _lock:
        _settings = None
