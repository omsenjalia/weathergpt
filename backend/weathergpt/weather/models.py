"""Normalized forecast model shared by every provider.

Rules:
- Units: °C, mm, km/h, hPa, %.
- ``time_utc`` is always timezone-aware UTC. Daily ``date`` is the *location-local*
  calendar date. Sunrise/sunset are naive location-local ``YYYY-MM-DDTHH:MM``.
- Missing values are ``None``, never 0 — ``weather_code`` 0 means "clear sky".
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from typing import Any, Optional

SCHEMA_VERSION = "3.0.0"
SELECTION_POLICY_VERSION = "3.0.0"


def finite(value: Any, low: Optional[float] = None, high: Optional[float] = None) -> Optional[float]:
    """Float within ``[low, high]`` or None (for None, NaN, inf, junk, out of range)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(num):
        return None
    if (low is not None and num < low) or (high is not None and num > high):
        return None
    return num


def as_int(value: Any) -> Optional[int]:
    num = finite(value)
    return int(num) if num is not None else None


def iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.astimezone(timezone.utc).isoformat() if dt else None


@dataclass
class HourPoint:
    time_utc: datetime
    temperature_c: Optional[float] = None
    feels_like_c: Optional[float] = None
    humidity_percent: Optional[float] = None
    wind_speed_kmh: Optional[float] = None
    wind_direction_deg: Optional[float] = None
    wind_gust_kmh: Optional[float] = None
    pressure_hpa: Optional[float] = None
    pressure_type: Optional[str] = None          # "msl" | "surface"
    precipitation_mm: Optional[float] = None
    precipitation_probability: Optional[float] = None
    weather_code: Optional[int] = None
    condition: Optional[str] = None
    cloud_cover_percent: Optional[float] = None
    uv_index: Optional[float] = None
    is_ensemble_mean: bool = False
    missing_reason: Optional[str] = None

    FILLABLE = (
        "temperature_c", "feels_like_c", "humidity_percent", "wind_speed_kmh", "wind_direction_deg",
        "wind_gust_kmh", "pressure_hpa", "precipitation_mm", "precipitation_probability",
        "cloud_cover_percent", "uv_index",
    )

    def to_dict(self) -> dict:
        return {f.name: (iso(getattr(self, f.name)) if f.name == "time_utc" else getattr(self, f.name))
                for f in fields(self)}


@dataclass
class DayPoint:
    date: str
    high_c: Optional[float] = None
    low_c: Optional[float] = None
    high_p90_c: Optional[float] = None
    low_p10_c: Optional[float] = None
    rain_probability: Optional[float] = None
    precipitation_mm: Optional[float] = None
    wind_kmh_max: Optional[float] = None
    weather_code: Optional[int] = None
    condition: Optional[str] = None
    sunrise: Optional[str] = None
    sunset: Optional[str] = None
    uv_index_max: Optional[float] = None
    hours_covered: Optional[int] = None
    covers_full_day: Optional[bool] = None
    precipitation_interval: Optional[str] = None
    statistic: Optional[str] = None
    source: Optional[str] = None
    forecast_text: Optional[str] = None          # IMD's own words for the day
    field_sources: dict = field(default_factory=dict)

    FILLABLE = ("high_c", "low_c", "rain_probability", "precipitation_mm", "wind_kmh_max",
                "sunrise", "sunset", "uv_index_max")

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Provenance:
    source: str
    model: Optional[str] = None
    model_version: Optional[str] = None
    product: str = "forecast"
    run_id: Optional[str] = None
    init_time_utc: Optional[datetime] = None
    issued_at_utc: Optional[datetime] = None
    observed_at_utc: Optional[datetime] = None
    freshness_status: str = "unknown"             # fresh | stale | expired | unknown
    resolution_deg: Optional[float] = None
    requested_lat: Optional[float] = None
    requested_lon: Optional[float] = None
    sampled_lat: Optional[float] = None
    sampled_lon: Optional[float] = None
    distance_km: Optional[float] = None
    spatial_method: Optional[str] = None
    station: Optional[dict] = None                 # IMD station that answered
    is_ensemble: bool = False
    expected_member_count: Optional[int] = None
    coverage_completeness: Optional[float] = None
    horizon_hours: Optional[int] = None
    surface: Optional[str] = None
    table: Optional[str] = None
    validity_start_utc: Optional[datetime] = None
    validity_end_utc: Optional[datetime] = None
    sources: list = field(default_factory=list)
    methods: dict = field(default_factory=dict)
    query_diagnostics: Optional[dict] = None
    notes: list = field(default_factory=list)

    @property
    def is_stale(self) -> bool:
        return self.freshness_status in ("stale", "expired")

    def to_dict(self) -> dict:
        out: dict[str, Any] = {}
        for f in fields(self):
            value = getattr(self, f.name)
            out[f.name] = iso(value) if isinstance(value, datetime) else value
        out["is_stale"] = self.is_stale
        out["sampled_coordinates"] = (
            {"lat": self.sampled_lat, "lon": self.sampled_lon} if self.sampled_lat is not None else None
        )
        return out


@dataclass
class Forecast:
    location: dict
    provenance: Provenance
    current: Optional[HourPoint] = None
    current_kind: Optional[str] = None             # "observation" (IMD station) | "model"
    hourly: list[HourPoint] = field(default_factory=list)
    daily: list[DayPoint] = field(default_factory=list)
    air_quality: Optional[dict] = None
    ensemble: Optional[dict] = None                 # WeatherNext statistic series (researcher)
    field_sources: dict = field(default_factory=dict)

    @property
    def utc_offset_seconds(self) -> Optional[int]:
        return as_int(self.location.get("utc_offset_seconds"))


@dataclass
class ProviderResult:
    ok: bool
    forecast: Optional[Forecast] = None
    reason: Optional[str] = None           # stable code, e.g. not_configured, auth_rejected
    message: Optional[str] = None
    transient: bool = False                # counts toward the circuit breaker
    extra: dict = field(default_factory=dict)
    latency_ms: Optional[float] = None

    def fallback_reason(self, provider: str) -> dict:
        out = {"provider": provider, "reason": self.reason or "unknown"}
        if self.message:
            out["message"] = self.message[:300]
        out.update(self.extra)
        return out
