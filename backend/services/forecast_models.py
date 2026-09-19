"""Normalized forecast models and provenance for WeatherNext integration.

This module defines:
- Normalized units (Celsius, mm, km/h, hPa, %, m/s internally where needed)
- Time handling with UTC and timezone awareness
- Provenance tracking: requested_source, selected_source, selection_policy_version, run_id, etc.
- Coverage and freshness metadata
- Product definitions and capability metadata

Scientific correctness rules from plan section 6 are enforced here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

# ---------------------------------------------------------------------------
# Enums and constants
# ---------------------------------------------------------------------------

class ProviderName(str, Enum):
    IMD = "imd"
    WEATHERNEXT = "weathernext"
    ACCUWEATHER = "accuweather"
    OPEN_METEO = "open_meteo"
    UNAVAILABLE = "unavailable"

class ProductType(str, Enum):
    FORECAST = "forecast"
    CURRENT = "current"
    HOURLY = "hourly"
    DAILY = "daily"
    AIR_QUALITY = "air_quality"
    UV = "uv"
    ASTRONOMY = "astronomy"
    ENSEMBLE = "ensemble"
    PROFILE = "profile"

class FreshnessStatus(str, Enum):
    FRESH = "fresh"
    STALE = "stale"
    EXPIRED = "expired"
    UNKNOWN = "unknown"

# Selection policy version - bump when logic changes
SELECTION_POLICY_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Unit conversion utilities (section 6.01)
# ---------------------------------------------------------------------------

def kelvin_to_celsius(k: float) -> float:
    return k - 273.15

def meters_to_mm(m: float) -> float:
    return m * 1000.0

def ms_to_kmh(ms: float) -> float:
    return ms * 3.6

def pa_to_hpa(pa: float) -> float:
    return pa / 100.0

def fraction_to_percent(frac: float) -> float:
    return frac * 100.0

def j_per_m2_to_w_per_m2(j: float, interval_seconds: int) -> float:
    if interval_seconds <= 0:
        return 0.0
    return j / interval_seconds

def geopotential_to_height(geopotential: float) -> float:
    return geopotential / 9.80665

def uv_component_to_speed(u: float, v: float) -> float:
    return math.sqrt(u*u + v*v)

def uv_to_direction(u: float, v: float) -> Optional[float]:
    """Wind from direction: (270 - degrees(atan2(v,u))) mod 360, calm undefined."""
    speed = uv_component_to_speed(u, v)
    if speed < 0.1:
        return None  # calm
    deg = math.degrees(math.atan2(v, u))
    return (270.0 - deg) % 360.0

# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def is_finite(value: Any) -> bool:
    try:
        f = float(value)
        return math.isfinite(f)
    except (TypeError, ValueError):
        return False

def bounded(value: Any, low: float | None = None, high: float | None = None) -> float | None:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(num):
        return None
    if low is not None and num < low:
        return None
    if high is not None and num > high:
        return None
    return num

# ---------------------------------------------------------------------------
# Provenance and metadata
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ForecastProvenance:
    requested_source: str  # what user asked for (auto, weathernext, etc.)
    selected_source: ProviderName
    selection_policy_version: str = SELECTION_POLICY_VERSION
    product: ProductType = ProductType.FORECAST
    model: Optional[str] = None  # e.g., weathernext_3_0_0
    model_version: Optional[str] = None
    run_id: Optional[str] = None  # init_time + version
    init_time_utc: Optional[datetime] = None
    ingested_at_utc: Optional[datetime] = None
    served_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    validity_start_utc: Optional[datetime] = None
    validity_end_utc: Optional[datetime] = None
    resolution_deg: Optional[float] = None  # 0.1, 0.05, etc.
    sampled_lat: Optional[float] = None
    sampled_lon: Optional[float] = None
    requested_lat: Optional[float] = None
    requested_lon: Optional[float] = None
    spatial_method: Optional[str] = None  # nearest, bilinear, etc.
    distance_km: Optional[float] = None
    is_stale: bool = False
    freshness_status: FreshnessStatus = FreshnessStatus.UNKNOWN
    fallback_reasons: list[dict] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    expected_member_count: Optional[int] = None
    valid_member_count: Optional[int] = None
    coverage_completeness: Optional[float] = None  # 0..1
    # Additive metadata (all optional, safe for existing clients)
    horizon_hours: Optional[int] = None            # forecast horizon actually present in this payload
    surface: Optional[str] = None                  # bigquery, gcs_statistics, gcs_ensemble, earth_engine
    table: Optional[str] = None                    # BigQuery table / dataset identifier the data came from
    bucket: Optional[str] = None                   # GCS bucket/root when applicable
    is_ensemble: bool = False
    query_diagnostics: Optional[dict] = None       # bytes billed/processed, cache hit, job id (no secrets)
    methods: dict = field(default_factory=dict)    # how derived fields were computed (honest labelling)

    def to_dict(self) -> dict:
        return {
            "requested_source": self.requested_source,
            "selected_source": self.selected_source.value,
            "selection_policy_version": self.selection_policy_version,
            "product": self.product.value,
            "model": self.model,
            "model_version": self.model_version,
            "run_id": self.run_id,
            "init_time_utc": self.init_time_utc.isoformat() if self.init_time_utc else None,
            "ingested_at_utc": self.ingested_at_utc.isoformat() if self.ingested_at_utc else None,
            "served_at_utc": self.served_at_utc.isoformat(),
            "validity_start_utc": self.validity_start_utc.isoformat() if self.validity_start_utc else None,
            "validity_end_utc": self.validity_end_utc.isoformat() if self.validity_end_utc else None,
            "resolution_deg": self.resolution_deg,
            "sampled_coordinates": {"lat": self.sampled_lat, "lon": self.sampled_lon} if self.sampled_lat is not None else None,
            "requested_coordinates": {"lat": self.requested_lat, "lon": self.requested_lon} if self.requested_lat is not None else None,
            "spatial_method": self.spatial_method,
            "distance_km": self.distance_km,
            "is_stale": self.is_stale,
            "freshness_status": self.freshness_status.value,
            "fallback_reasons": self.fallback_reasons,
            "sources": self.sources,
            "expected_member_count": self.expected_member_count,
            "valid_member_count": self.valid_member_count,
            "coverage_completeness": self.coverage_completeness,
            "horizon_hours": self.horizon_hours,
            "surface": self.surface,
            "table": self.table,
            "bucket": self.bucket,
            "is_ensemble": self.is_ensemble,
            "query_diagnostics": self.query_diagnostics,
            "methods": self.methods,
        }

@dataclass
class ForecastPoint:
    """Single time point with nullable values and missing reasons."""
    time_utc: datetime
    temperature_c: Optional[float] = None
    feels_like_c: Optional[float] = None
    humidity_percent: Optional[float] = None
    wind_speed_kmh: Optional[float] = None
    wind_direction_deg: Optional[float] = None
    wind_gust_kmh: Optional[float] = None
    pressure_hpa: Optional[float] = None  # surface or MSL with explicit label
    pressure_type: str = "surface"  # surface vs msl
    precipitation_mm: Optional[float] = None
    precipitation_probability: Optional[float] = None
    weather_code: Optional[int] = None
    condition: Optional[str] = None
    cloud_cover_percent: Optional[float] = None
    uv_index: Optional[float] = None
    # Ensemble support
    member_id: Optional[int] = None
    is_ensemble_mean: bool = False
    ensemble_members: Optional[list[float]] = None  # raw member values for this variable
    # Missing data
    missing_reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "time_utc": self.time_utc.isoformat(),
            "temperature_c": self.temperature_c,
            "feels_like_c": self.feels_like_c,
            "humidity_percent": self.humidity_percent,
            "wind_speed_kmh": self.wind_speed_kmh,
            "wind_direction_deg": self.wind_direction_deg,
            "wind_gust_kmh": self.wind_gust_kmh,
            "pressure_hpa": self.pressure_hpa,
            "pressure_type": self.pressure_type,
            "precipitation_mm": self.precipitation_mm,
            "precipitation_probability": self.precipitation_probability,
            "weather_code": self.weather_code,
            "condition": self.condition,
            "cloud_cover_percent": self.cloud_cover_percent,
            "uv_index": self.uv_index,
            "member_id": self.member_id,
            "is_ensemble_mean": self.is_ensemble_mean,
            "missing_reason": self.missing_reason,
        }

@dataclass
class NormalizedForecast:
    """Complete normalized forecast with provenance."""
    location: dict  # lat, lon, timezone, name
    current: Optional[ForecastPoint] = None
    hourly: list[ForecastPoint] = field(default_factory=list)
    daily: list[dict] = field(default_factory=list)  # daily aggregates
    provenance: ForecastProvenance = field(default_factory=lambda: ForecastProvenance(requested_source="auto", selected_source=ProviderName.UNAVAILABLE))
    # Additional products
    air_quality: Optional[dict] = None
    uv: Optional[dict] = None
    astronomy: Optional[dict] = None
    alerts: list[dict] = field(default_factory=list)  # official warnings separate from model guidance
    # Raw ensemble data for researcher mode (bounded)
    ensemble: Optional[dict] = None
    # Metadata
    schema_version: str = "2.0.0"
    mode: str = "everyone"  # everyone, farmer, researcher
    # Per-field attribution when secondary providers filled null fields
    # (services.forecast_supplement). Empty when nothing was supplemented.
    field_sources: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "mode": self.mode,
            "field_sources": self.field_sources,
            "location": self.location,
            "current": self.current.to_dict() if self.current else None,
            "hourly": [p.to_dict() for p in self.hourly],
            "daily": self.daily,
            "provenance": self.provenance.to_dict(),
            "air_quality": self.air_quality,
            "uv": self.uv,
            "astronomy": self.astronomy,
            "alerts": self.alerts,
            "ensemble": self.ensemble,
        }

# ---------------------------------------------------------------------------
# Capability metadata
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CapabilityField:
    variable_id: str
    native_units: str
    display_units: str
    description: str
    resolution_deg: Optional[float] = None
    available_statistics: list[str] = field(default_factory=list)  # mean, p10, etc.
    is_ensemble: bool = False
    product: str = "surface"  # surface, station_head, upper_air, etc.
    level: Optional[int] = None  # pressure level hPa

@dataclass(frozen=True)
class ProviderCapability:
    provider: ProviderName
    products: list[ProductType]
    fields: list[CapabilityField]
    max_forecast_days: int
    has_ensemble: bool
    ensemble_members: Optional[int] = None
    freshness_budget_hours: float = 6.0  # how old can data be before considered stale
    requires_credentials: bool = False

# ---------------------------------------------------------------------------
# Predefined capabilities (from verified scope)
# ---------------------------------------------------------------------------

# Documented WeatherNext variables
WEATHERNEXT_VARIABLES = [
    # Surface
    ("temperature_2m", "K", "C", "2m temperature", 0.1),
    ("dewpoint_temperature_2m", "K", "C", "2m dewpoint", 0.1),
    ("station_head_temperature_2m", "K", "C", "Station head 2m temp", 0.05),
    ("station_head_dewpoint_temperature_2m", "K", "C", "Station head dewpoint", 0.05),
    ("wind_speed_10m", "m/s", "km/h", "10m wind speed", 0.1),
    ("u_component_of_wind_10m", "m/s", "km/h", "10m U wind", 0.1),
    ("v_component_of_wind_10m", "m/s", "km/h", "10m V wind", 0.1),
    ("wind_speed_100m", "m/s", "km/h", "100m wind speed", 0.1),
    ("surface_solar_radiation_downwards_1hr", "J/m²", "W/m²", "Solar down 1hr", 0.1),
    ("total_precipitation_1hr", "m", "mm", "Total precip 1hr", 0.1),
    ("total_precipitation_6hr", "m", "mm", "Total precip 6hr", 0.1),
    ("imerg_tp_1hr", "m", "mm", "IMERG-trained precip", 0.1),
    ("experimental_tp_1hr", "m", "mm", "Experimental precip", 0.1),
    ("total_cloud_cover", "0-1", "%", "Total cloud cover", 0.1),
    ("mean_sea_level_pressure", "Pa", "hPa", "MSL pressure", 0.1),
    ("sea_surface_temperature", "K", "C", "Sea surface temp", 0.1),
]

PRESSURE_LEVELS = [50, 100, 150, 200, 250, 300, 400, 500, 600, 700, 850, 925, 1000]

def get_weathernest_capability() -> ProviderCapability:
    fields = []
    for var_id, native_u, display_u, desc, res in WEATHERNEXT_VARIABLES:
        fields.append(CapabilityField(
            variable_id=var_id,
            native_units=native_u,
            display_units=display_u,
            description=desc,
            resolution_deg=res,
            available_statistics=["mean", "p10", "p25", "p50", "p75", "p90"] if "temperature" in var_id or "precipitation" in var_id else [],
            is_ensemble=True,
            product="surface",
        ))
    # Upper air
    for level in PRESSURE_LEVELS:
        for base in ["temperature", "geopotential", "specific_humidity", "u_component_of_wind", "v_component_of_wind", "vertical_velocity"]:
            fields.append(CapabilityField(
                variable_id=f"{base}_{level}",
                native_units="K" if "temperature" in base else "m²/s²" if "geopotential" in base else "kg/kg" if "humidity" in base else "m/s" if "wind" in base else "Pa/s",
                display_units="C" if "temperature" in base else "m" if "geopotential" in base else "kg/kg",
                description=f"{base} at {level}hPa",
                resolution_deg=0.25,
                is_ensemble=True,
                product="upper_air",
                level=level,
            ))
    # WeatherNext runs reach BigQuery ~7 h after init and only the 6-hourly
    # synoptic cycles carry the 15-day horizon, so the newest usable run is
    # routinely 7-13 h old. The budget is therefore config-driven
    # (WEATHERNEXT_FRESHNESS_HOURS, default 24 h) rather than a fixed 6 h.
    try:
        from services.config import get_config
        freshness_hours = float(get_config().weathernext.run_policy.freshness_hours)
    except Exception:  # pragma: no cover - config import problems must never break capability lookup
        freshness_hours = 24.0
    return ProviderCapability(
        provider=ProviderName.WEATHERNEXT,
        products=[ProductType.FORECAST, ProductType.HOURLY, ProductType.DAILY, ProductType.ENSEMBLE, ProductType.PROFILE],
        fields=fields,
        max_forecast_days=15,
        has_ensemble=True,
        ensemble_members=64,
        freshness_budget_hours=freshness_hours,
        requires_credentials=True,
    )

def get_open_meteo_capability() -> ProviderCapability:
    return ProviderCapability(
        provider=ProviderName.OPEN_METEO,
        products=[ProductType.FORECAST, ProductType.HOURLY, ProductType.DAILY, ProductType.CURRENT, ProductType.AIR_QUALITY, ProductType.UV, ProductType.ASTRONOMY],
        fields=[
            CapabilityField("temperature_2m", "C", "C", "2m temperature", 0.1),
            CapabilityField("precipitation", "mm", "mm", "Precipitation", 0.1),
            CapabilityField("wind_speed_10m", "km/h", "km/h", "Wind speed", 0.1),
        ],
        max_forecast_days=16,
        has_ensemble=False,
        freshness_budget_hours=3.0,
        requires_credentials=False,
    )

def get_imd_capability() -> ProviderCapability:
    return ProviderCapability(
        provider=ProviderName.IMD,
        products=[ProductType.FORECAST, ProductType.CURRENT],
        fields=[
            CapabilityField("temperature_2m", "C", "C", "2m temperature"),
            CapabilityField("precipitation", "mm", "mm", "Precipitation"),
        ],
        max_forecast_days=7,
        has_ensemble=False,
        freshness_budget_hours=3.0,
        requires_credentials=True,
    )

def get_accuweather_capability() -> ProviderCapability:
    return ProviderCapability(
        provider=ProviderName.ACCUWEATHER,
        products=[ProductType.FORECAST, ProductType.CURRENT, ProductType.HOURLY, ProductType.DAILY],
        fields=[
            CapabilityField("temperature_2m", "C", "C", "2m temperature"),
            CapabilityField("precipitation", "mm", "mm", "Precipitation"),
        ],
        max_forecast_days=15,
        has_ensemble=False,
        freshness_budget_hours=6.0,
        requires_credentials=True,
    )
