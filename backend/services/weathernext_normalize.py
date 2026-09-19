"""Normalise a raw WeatherNext BigQuery point extraction into ``NormalizedForecast``.

Pure functions - no I/O - so the science can be unit-tested offline.

Scientific rules honoured (integration plan section 6):
- native units preserved on the wire, converted once here (K->C, m->mm, m/s->km/h,
  Pa->hPa, cloud fraction->%)
- ensemble statistics are *precomputed* per lead time; we never mix runs, never
  sum quantiles (only the ensemble mean is summed - it is linear), and any
  probability we report is an explicit *lower bound* derived from quantiles
- every derived field is labelled in ``provenance.methods``
- values that cannot be derived are ``None`` with a reason, never fabricated
"""

from __future__ import annotations

import math
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from services.forecast_models import (
    ForecastPoint,
    ForecastProvenance,
    FreshnessStatus,
    NormalizedForecast,
    ProductType,
    ProviderName,
    kelvin_to_celsius,
    meters_to_mm,
    ms_to_kmh,
    pa_to_hpa,
    uv_to_direction,
)
from services.weathernext_bigquery import ENSEMBLE_MEMBERS, MODEL_ID, MODEL_VERSION, PointForecastResult

STATISTICS = ("mean", "p10", "p25", "p50", "p75", "p90")
RAIN_THRESHOLD_MM_PER_HOUR = 0.1

# variable -> (display units, converter from native)
VARIABLE_UNITS: dict[str, tuple[str, Any]] = {
    "temperature_2m": ("C", kelvin_to_celsius),
    "dewpoint_temperature_2m": ("C", kelvin_to_celsius),
    "station_head_temperature_2m": ("C", kelvin_to_celsius),
    "station_head_dewpoint_temperature_2m": ("C", kelvin_to_celsius),
    "sea_surface_temperature": ("C", kelvin_to_celsius),
    "total_precipitation_1hr": ("mm", meters_to_mm),
    "imerg_tp_1hr": ("mm", meters_to_mm),
    "experimental_tp_1hr": ("mm", meters_to_mm),
    "wind_speed_10m": ("km/h", ms_to_kmh),
    "wind_speed_100m": ("km/h", ms_to_kmh),
    "u_component_of_wind_10m": ("km/h", ms_to_kmh),
    "v_component_of_wind_10m": ("km/h", ms_to_kmh),
    "mean_sea_level_pressure": ("hPa", pa_to_hpa),
    "total_cloud_cover": ("%", lambda f: f * 100.0),
    "low_cloud_cover": ("%", lambda f: f * 100.0),
    "medium_cloud_cover": ("%", lambda f: f * 100.0),
    "high_cloud_cover": ("%", lambda f: f * 100.0),
    "surface_solar_radiation_downwards_1hr": ("W/m2", lambda j: j / 3600.0),
}


def split_column(column: str) -> Optional[tuple[str, str]]:
    """``temperature_2m_p90`` -> ``("temperature_2m", "p90")``."""
    for stat in STATISTICS:
        suffix = f"_{stat}"
        if column.endswith(suffix):
            return column[: -len(suffix)], stat
    return None


def _finite(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num if math.isfinite(num) else None


def relative_humidity_from_dewpoint(temp_c: Optional[float], dewpoint_c: Optional[float]) -> Optional[float]:
    """Magnus formula (Alduchov & Eskridge coefficients), clamped to 0..100 %."""
    if temp_c is None or dewpoint_c is None:
        return None
    a, b = 17.625, 243.04
    try:
        rh = 100.0 * math.exp(a * dewpoint_c / (b + dewpoint_c)) / math.exp(a * temp_c / (b + temp_c))
    except (OverflowError, ZeroDivisionError):
        return None
    return round(max(0.0, min(100.0, rh)), 1)


def derive_condition(precip_mm_per_hour: Optional[float], cloud_cover_percent: Optional[float]) -> tuple[Optional[int], Optional[str]]:
    """WMO-style code from ensemble-mean precipitation rate and cloud cover.

    WeatherNext surface statistics carry no precipitation *type* or convective
    flags, so only rain/drizzle and sky-cover classes are derivable.
    """
    if precip_mm_per_hour is not None:
        if precip_mm_per_hour >= 10.0:
            return 65, "Heavy rain"
        if precip_mm_per_hour >= 2.5:
            return 63, "Moderate rain"
        if precip_mm_per_hour >= 0.5:
            return 61, "Slight rain"
        if precip_mm_per_hour >= RAIN_THRESHOLD_MM_PER_HOUR:
            return 51, "Light drizzle"
    if cloud_cover_percent is None:
        return None, None
    if cloud_cover_percent < 12.5:
        return 0, "Clear sky"
    if cloud_cover_percent < 50.0:
        return 1, "Mainly clear"
    if cloud_cover_percent < 87.5:
        return 2, "Partly cloudy"
    return 3, "Overcast"


def rain_probability_lower_bound(quantiles_mm: dict[str, Optional[float]], threshold_mm: float = RAIN_THRESHOLD_MM_PER_HOUR) -> Optional[float]:
    """Lower bound on P(precip >= threshold) from precomputed quantiles.

    If the p-th percentile is >= threshold then at least (100-p) % of members
    exceed it. Returns the tightest bound the available quantiles support, 0
    when even p90 is dry (i.e. < 10 % of members wet), or None when no
    quantile is available at all.
    """
    order = (("p10", 90.0), ("p25", 75.0), ("p50", 50.0), ("p75", 25.0), ("p90", 10.0))
    available = [(name, prob) for name, prob in order if quantiles_mm.get(name) is not None]
    if not available:
        return None
    for name, prob in available:
        value = quantiles_mm[name]
        if value is not None and value >= threshold_mm:
            return prob
    return 0.0


def approx_utc_offset_hours(lon: float) -> int:
    """Solar-time approximation of the local UTC offset (15 deg per hour)."""
    return int(round(lon / 15.0))


def _step_values(step: dict, variable: str) -> dict[str, Optional[float]]:
    """Display-unit values for every statistic of ``variable`` present in the step."""
    units, convert = VARIABLE_UNITS.get(variable, ("native", lambda v: v))
    out: dict[str, Optional[float]] = {}
    for stat in STATISTICS:
        raw = _finite(step.get(f"{variable}_{stat}"))
        if raw is None:
            continue
        value = convert(raw)
        if variable.endswith("_1hr") and units == "mm" and value < 0:
            value = 0.0  # tiny negative accumulations are numerical noise
        out[stat] = round(value, 3)
    return out


def normalize_point_forecast(
    result: PointForecastResult,
    *,
    lat: float,
    lon: float,
    requested_source: str = "auto",
    mode: str = "everyone",
    forecast_days: int = 7,
    freshness_hours: float = 24.0,
    now: Optional[datetime] = None,
) -> NormalizedForecast:
    now = now or datetime.now(timezone.utc)
    variables = _variables_in(result.columns)

    hourly: list[ForecastPoint] = []
    series: "OrderedDict[str, dict]" = OrderedDict()
    temp_quantiles: list[dict] = []

    for step in result.steps:
        t: datetime = step["time"]
        per_var = {v: _step_values(step, v) for v in variables}

        temp = per_var.get("temperature_2m", {})
        dew = per_var.get("dewpoint_temperature_2m", {})
        precip = per_var.get("total_precipitation_1hr", {})
        wind = per_var.get("wind_speed_10m", {})
        u = per_var.get("u_component_of_wind_10m", {})
        v = per_var.get("v_component_of_wind_10m", {})
        cloud = per_var.get("total_cloud_cover", {})
        mslp = per_var.get("mean_sea_level_pressure", {})

        temperature_c = temp.get("mean")
        precipitation_mm = precip.get("mean")
        cloud_pct = cloud.get("mean")
        humidity = relative_humidity_from_dewpoint(temperature_c, dew.get("mean"))
        wind_dir = None
        if u.get("mean") is not None and v.get("mean") is not None:
            wind_dir = uv_to_direction(u["mean"], v["mean"])
            wind_dir = round(wind_dir, 1) if wind_dir is not None else None
        code, condition = derive_condition(precipitation_mm, cloud_pct)
        pop = rain_probability_lower_bound({k: precip.get(k) for k in ("p10", "p25", "p50", "p75", "p90")})

        missing = None
        if temperature_c is None:
            missing = "temperature_2m_mean_missing"
        elif condition is None:
            missing = "cloud_cover_not_selected"

        hourly.append(ForecastPoint(
            time_utc=t,
            temperature_c=round(temperature_c, 1) if temperature_c is not None else None,
            humidity_percent=humidity,
            wind_speed_kmh=round(wind["mean"], 1) if wind.get("mean") is not None else None,
            wind_direction_deg=wind_dir,
            pressure_hpa=round(mslp["mean"], 1) if mslp.get("mean") is not None else None,
            pressure_type="msl",
            precipitation_mm=round(precipitation_mm, 2) if precipitation_mm is not None else None,
            precipitation_probability=pop,
            weather_code=code,
            condition=condition,
            cloud_cover_percent=round(cloud_pct, 1) if cloud_pct is not None else None,
            is_ensemble_mean=True,
            missing_reason=missing,
        ))

        if temp:
            temp_quantiles.append({"time_utc": t, **temp})

        for var_name, values in per_var.items():
            if not values:
                continue
            entry = series.setdefault(var_name, {
                "units": VARIABLE_UNITS.get(var_name, ("native", None))[0],
                "statistics": [],
                "values": [],
            })
            for stat in values:
                if stat not in entry["statistics"]:
                    entry["statistics"].append(stat)
            entry["values"].append({"time_utc": t.isoformat(), **values})

    if not hourly:
        raise ValueError("WeatherNext run returned no forecast steps")

    current = _nearest_point(hourly, now)
    offset_h = approx_utc_offset_hours(lon)
    daily = _aggregate_daily(hourly, temp_quantiles, offset_h, forecast_days, now)

    init_time = result.init_time.astimezone(timezone.utc)
    age_h = (now - init_time).total_seconds() / 3600.0
    if age_h <= freshness_hours:
        freshness = FreshnessStatus.FRESH
    elif age_h <= freshness_hours * 2:
        freshness = FreshnessStatus.STALE
    else:
        freshness = FreshnessStatus.EXPIRED

    expected_steps = result.horizon_hours
    completeness = round(min(1.0, len(hourly) / expected_steps), 3) if expected_steps else None

    methods = {
        "current": "nearest_forecast_step_to_now (model guidance, not an observation)",
        "temperature": "ensemble_mean",
        "humidity": "magnus_from_2m_temperature_and_dewpoint_means" if "dewpoint_temperature_2m" in variables else "unavailable_dewpoint_not_selected",
        "wind_direction": "direction_of_mean_uv_vector" if {"u_component_of_wind_10m", "v_component_of_wind_10m"} <= set(variables) else "unavailable_uv_not_selected",
        "pressure": "mean_sea_level_pressure_ensemble_mean",
        "condition": "wmo_class_from_mean_precip_rate_and_cloud_cover",
        "precipitation": "ensemble_mean_1h_accumulation_summed_over_intervals",
        "precipitation_probability": f"lower_bound_from_quantiles_threshold_{RAIN_THRESHOLD_MM_PER_HOUR}mm_per_h",
        "daily_extremes": "min_max_of_ensemble_mean_hourly (p10/p90 envelope reported separately)",
        "daily_rain_probability": "lower_bound_max_of_hourly_bounds",
        "day_boundary": f"solar_local_approx_utc{offset_h:+d}",
    }

    provenance = ForecastProvenance(
        requested_source=requested_source,
        selected_source=ProviderName.WEATHERNEXT,
        product=ProductType.FORECAST,
        model=getattr(result, "model_id", MODEL_ID),
        model_version=getattr(result, "model_version", MODEL_VERSION),
        run_id=result.run_id,
        init_time_utc=init_time,
        served_at_utc=now,
        validity_start_utc=hourly[0].time_utc,
        validity_end_utc=hourly[-1].time_utc,
        resolution_deg=result.resolution_deg,
        sampled_lat=round(result.cell_lat, 4),
        sampled_lon=round(result.cell_lon, 4),
        requested_lat=lat,
        requested_lon=lon,
        spatial_method="nearest_cell_centre",
        distance_km=result.distance_km,
        is_stale=freshness != FreshnessStatus.FRESH,
        freshness_status=freshness,
        sources=[f"weathernext_{getattr(result, 'surface', 'bigquery')}:{result.table}"],
        expected_member_count=ENSEMBLE_MEMBERS,
        valid_member_count=None,  # statistics are precomputed upstream; member validity is not exposed
        coverage_completeness=completeness,
        horizon_hours=len(hourly),
        surface=getattr(result, "surface", "bigquery"),
        table=result.table if getattr(result, "surface", "bigquery") == "bigquery" else None,
        bucket=result.table.split("/", 3)[2] if getattr(result, "surface", "bigquery").startswith("gcs") and result.table.startswith("gs://") else None,
        is_ensemble=True,
        query_diagnostics={
            **result.diagnostics.to_dict(),
            "attempted_runs": result.attempted_inits,
            "credential_source": result.credential_source,
            "columns": list(result.columns),
        },
        methods=methods,
    )

    ensemble = {
        "members": ENSEMBLE_MEMBERS,
        "member_data": False,
        "statistics": sorted({s for e in series.values() for s in e["statistics"]}, key=STATISTICS.index),
        "note": "Precomputed ensemble statistics from the BigQuery surface table; raw members live only on GCS Zarr.",
        "run_id": result.run_id,
        "series": {name: {**entry, "values": entry["values"][:168]} for name, entry in series.items()},
    }

    return NormalizedForecast(
        location={
            "lat": lat,
            "lon": lon,
            "timezone": f"UTC{offset_h:+d} (solar approximation)",
            "utc_offset_hours_approx": offset_h,
            "grid_cell": {"lat": round(result.cell_lat, 4), "lon": round(result.cell_lon, 4), "resolution_deg": result.resolution_deg},
        },
        current=current,
        hourly=hourly,
        daily=daily,
        provenance=provenance,
        ensemble=ensemble,
        mode=mode,
    )


def _variables_in(columns: tuple[str, ...]) -> list[str]:
    seen: list[str] = []
    for col in columns:
        split = split_column(col)
        if split and split[0] not in seen:
            seen.append(split[0])
    return seen


def _nearest_point(hourly: list[ForecastPoint], now: datetime) -> ForecastPoint:
    return min(hourly, key=lambda p: abs((p.time_utc - now).total_seconds()))


def _aggregate_daily(
    hourly: list[ForecastPoint],
    temp_quantiles: list[dict],
    offset_h: int,
    forecast_days: int,
    now: datetime,
) -> list[dict]:
    offset = timedelta(hours=offset_h)
    q_by_time = {q["time_utc"]: q for q in temp_quantiles}
    buckets: "OrderedDict[str, list[ForecastPoint]]" = OrderedDict()
    for p in hourly:
        local_date = (p.time_utc + offset).date().isoformat()
        buckets.setdefault(local_date, []).append(p)

    today_local = (now + offset).date().isoformat()
    daily: list[dict] = []
    for date, points in buckets.items():
        if date < today_local:
            continue
        if len(daily) >= forecast_days:
            break
        temps = [p.temperature_c for p in points if p.temperature_c is not None]
        rains = [p.precipitation_mm for p in points if p.precipitation_mm is not None]
        winds = [p.wind_speed_kmh for p in points if p.wind_speed_kmh is not None]
        pops = [p.precipitation_probability for p in points if p.precipitation_probability is not None]
        codes = [p.weather_code for p in points if p.weather_code is not None]
        p10s = [q_by_time[p.time_utc].get("p10") for p in points if p.time_utc in q_by_time and q_by_time[p.time_utc].get("p10") is not None]
        p90s = [q_by_time[p.time_utc].get("p90") for p in points if p.time_utc in q_by_time and q_by_time[p.time_utc].get("p90") is not None]

        # Representative condition: the wettest hour if any rain class, else the
        # cloudiest daytime class; both are max() over the small WMO code set used.
        code = max(codes) if codes else None
        condition = None
        if code is not None:
            condition = next((p.condition for p in points if p.weather_code == code), None)

        daily.append({
            "date": date,
            "high_c": round(max(temps), 1) if temps else None,
            "low_c": round(min(temps), 1) if temps else None,
            "high_p90_c": round(max(p90s), 1) if p90s else None,
            "low_p10_c": round(min(p10s), 1) if p10s else None,
            "rain_probability": max(pops) if pops else None,
            "rain_mm": round(sum(rains), 2) if rains else None,
            "precipitation_mm": round(sum(rains), 2) if rains else None,
            "wind_kmh_max": round(max(winds), 1) if winds else None,
            "condition": condition,
            "weather_code": code,
            "sunrise": None,
            "sunset": None,
            "hours_covered": len(points),
            "covers_full_day": len(points) >= 24,
            "precipitation_interval": f"{len(points)}h" if len(points) < 24 else "24h",
            "source": "weathernext",
            "statistic": "ensemble_mean",
        })
    return daily
