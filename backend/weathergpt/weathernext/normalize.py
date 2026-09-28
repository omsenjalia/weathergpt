"""Raw WeatherNext point extraction -> ``Forecast`` (pure, no I/O).

Scientific rules:
- native units converted once (K->°C, m->mm, m/s->km/h, Pa->hPa, fraction->%)
- only the ensemble *mean* is summed (it is linear); quantiles are never summed
- rain probability is an explicit *lower bound* read from precomputed quantiles
- every derived field is named in ``provenance.methods``
"""

from __future__ import annotations

import math
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from weathergpt.weather.models import DayPoint, Forecast, HourPoint, Provenance
from weathergpt.weathernext.bigquery import ENSEMBLE_MEMBERS, PointForecastResult

STATISTICS = ("mean", "p10", "p25", "p50", "p75", "p90")
RAIN_THRESHOLD_MM = 0.1

_K = lambda v: v - 273.15  # noqa: E731
_MM = lambda v: v * 1000.0  # noqa: E731
_KMH = lambda v: v * 3.6  # noqa: E731
_PCT = lambda v: v * 100.0  # noqa: E731

UNITS: dict[str, tuple[str, Any]] = {
    "temperature_2m": ("C", _K), "dewpoint_temperature_2m": ("C", _K),
    "station_head_temperature_2m": ("C", _K), "station_head_dewpoint_temperature_2m": ("C", _K),
    "total_precipitation_1hr": ("mm", _MM), "total_precipitation_6hr": ("mm", _MM),
    "wind_speed_10m": ("km/h", _KMH), "u_component_of_wind_10m": ("km/h", _KMH),
    "v_component_of_wind_10m": ("km/h", _KMH),
    "mean_sea_level_pressure": ("hPa", lambda v: v / 100.0), "total_cloud_cover": ("%", _PCT),
}
WN2_ALIASES = {
    "2m_temperature": "temperature_2m", "2m_dewpoint_temperature": "dewpoint_temperature_2m",
    "10m_u_component_of_wind": "u_component_of_wind_10m", "10m_v_component_of_wind": "v_component_of_wind_10m",
}


def _finite(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def column_map(columns: tuple[str, ...]) -> "OrderedDict[str, dict[str, str]]":
    out: "OrderedDict[str, dict[str, str]]" = OrderedDict()
    for col in columns:
        base, stat = col, "mean"
        for s in STATISTICS:
            if col.endswith(f"_{s}"):
                base, stat = col[: -len(s) - 1], s
                break
        out.setdefault(WN2_ALIASES.get(base, base), {})[stat] = col
    return out


def _values(step: dict, variable: str, keys: dict[str, str]) -> dict[str, float]:
    units, convert = UNITS.get(variable, ("native", lambda v: v))
    out = {}
    for stat, key in keys.items():
        raw = _finite(step.get(key))
        if raw is None:
            continue
        value = convert(raw)
        if units == "mm" and value < 0:
            value = 0.0  # tiny negative accumulations are numerical noise
        out[stat] = round(value, 3)
    return out


def humidity_from_dewpoint(t: Optional[float], td: Optional[float]) -> Optional[float]:
    if t is None or td is None:
        return None
    a, b = 17.625, 243.04
    rh = 100.0 * math.exp(a * td / (b + td)) / math.exp(a * t / (b + t))
    return round(max(0.0, min(100.0, rh)), 1)


def derive_condition(rate_mm: Optional[float], cloud_pct: Optional[float]) -> tuple[Optional[int], Optional[str]]:
    if rate_mm is not None:
        if rate_mm >= 10.0:
            return 65, "Heavy rain"
        if rate_mm >= 2.5:
            return 63, "Moderate rain"
        if rate_mm >= 0.5:
            return 61, "Slight rain"
        if rate_mm >= RAIN_THRESHOLD_MM:
            return 51, "Light drizzle"
    if cloud_pct is None:
        return None, None
    if cloud_pct < 12.5:
        return 0, "Clear sky"
    if cloud_pct < 50.0:
        return 1, "Mainly clear"
    if cloud_pct < 87.5:
        return 2, "Partly cloudy"
    return 3, "Overcast"


def rain_probability_lower_bound(q: dict[str, Optional[float]]) -> Optional[float]:
    """If the p-th percentile >= threshold, at least (100-p)% of members are wet."""
    order = (("p10", 90.0), ("p25", 75.0), ("p50", 50.0), ("p75", 25.0), ("p90", 10.0))
    available = [(n, p) for n, p in order if q.get(n) is not None]
    if not available:
        return None
    for name, prob in available:
        if q[name] >= RAIN_THRESHOLD_MM:
            return prob
    return 0.0


def local_offset_seconds(lat: float, lon: float) -> tuple[int, str]:
    if 6.0 <= lat <= 37.6 and 67.0 <= lon <= 98.0:
        return 19800, "Asia/Kolkata"
    hours = int(round(lon / 15.0))
    return hours * 3600, f"UTC{hours:+d} (solar approximation)"


def normalize(result: PointForecastResult, *, lat: float, lon: float, forecast_days: int,
              freshness_hours: float, now: Optional[datetime] = None) -> Forecast:
    now = now or datetime.now(timezone.utc)
    cmap = column_map(result.columns)
    derive_speed = "wind_speed_10m" not in cmap and {"u_component_of_wind_10m", "v_component_of_wind_10m"} <= set(cmap)
    hourly: list[HourPoint] = []
    series: "OrderedDict[str, dict]" = OrderedDict()
    temp_q: dict[datetime, dict] = {}

    for step in result.steps:
        t: datetime = step["time"]
        per = {v: _values(step, v, keys) for v, keys in cmap.items()}
        temp, dew = per.get("temperature_2m", {}), per.get("dewpoint_temperature_2m", {})
        precip, wind = per.get("total_precipitation_1hr", {}), per.get("wind_speed_10m", {})
        u, v = per.get("u_component_of_wind_10m", {}), per.get("v_component_of_wind_10m", {})
        cloud, mslp = per.get("total_cloud_cover", {}), per.get("mean_sea_level_pressure", {})

        wind_mean = wind.get("mean")
        direction = None
        if u.get("mean") is not None and v.get("mean") is not None:
            if math.hypot(u["mean"], v["mean"]) >= 0.36:
                direction = round((270.0 - math.degrees(math.atan2(v["mean"], u["mean"]))) % 360.0, 1)
            if wind_mean is None and derive_speed:
                wind_mean = math.hypot(u["mean"], v["mean"])
        code, condition = derive_condition(precip.get("mean"), cloud.get("mean"))
        t_mean = temp.get("mean")
        hourly.append(HourPoint(
            time_utc=t,
            temperature_c=round(t_mean, 1) if t_mean is not None else None,
            humidity_percent=humidity_from_dewpoint(t_mean, dew.get("mean")),
            wind_speed_kmh=round(wind_mean, 1) if wind_mean is not None else None,
            wind_direction_deg=direction,
            pressure_hpa=round(mslp["mean"], 1) if mslp.get("mean") is not None else None,
            pressure_type="msl" if mslp.get("mean") is not None else None,
            precipitation_mm=round(precip["mean"], 2) if precip.get("mean") is not None else None,
            precipitation_probability=rain_probability_lower_bound(precip),
            weather_code=code, condition=condition,
            cloud_cover_percent=round(cloud["mean"], 1) if cloud.get("mean") is not None else None,
            is_ensemble_mean=True,
            missing_reason=("temperature_2m_mean_missing" if t_mean is None
                            else "cloud_cover_not_selected" if condition is None else None),
        ))
        if temp:
            temp_q[t] = temp
        for name, values in per.items():
            if not values:
                continue
            entry = series.setdefault(name, {"units": UNITS.get(name, ("native",))[0], "statistics": [], "values": []})
            for s in values:
                if s not in entry["statistics"]:
                    entry["statistics"].append(s)
            entry["values"].append({"time_utc": t.isoformat(), **values})

    if not hourly:
        raise ValueError("WeatherNext run returned no forecast steps")

    offset, tz_label = local_offset_seconds(lat, lon)
    daily = _daily(hourly, temp_q, offset, forecast_days, now)
    age_h = (now - result.init_time).total_seconds() / 3600.0
    freshness = "fresh" if age_h <= freshness_hours else "stale" if age_h <= 2 * freshness_hours else "expired"
    current = min(hourly, key=lambda p: abs((p.time_utc - now).total_seconds()))

    provenance = Provenance(
        source="weathernext", model=result.model_id, model_version=result.model_version, run_id=result.run_id,
        init_time_utc=result.init_time, issued_at_utc=result.init_time, freshness_status=freshness,
        resolution_deg=result.resolution_deg, requested_lat=lat, requested_lon=lon,
        sampled_lat=round(result.cell_lat, 4), sampled_lon=round(result.cell_lon, 4),
        distance_km=result.distance_km, spatial_method="nearest_cell_centre", is_ensemble=True,
        expected_member_count=ENSEMBLE_MEMBERS,
        coverage_completeness=round(min(1.0, len(hourly) / result.horizon_hours), 3) if result.horizon_hours else None,
        horizon_hours=len(hourly), surface="bigquery", table=result.table,
        validity_start_utc=hourly[0].time_utc, validity_end_utc=hourly[-1].time_utc,
        sources=[f"weathernext_bigquery:{result.table}"],
        query_diagnostics={**result.diagnostics.to_dict(), "attempted_runs": result.attempted_runs,
                           "credential_source": result.credential_source, "columns": list(result.columns)},
        methods={
            "current": "nearest forecast step to now (model guidance, not an observation)",
            "temperature": "ensemble mean",
            "humidity": "Magnus formula from 2 m temperature and dew-point means",
            "wind_direction": "direction of the mean u/v vector",
            "wind_speed": "magnitude of mean u/v vector" if derive_speed else "ensemble mean",
            "condition": "WMO class from mean precipitation rate and cloud cover",
            "precipitation_probability": f"lower bound from quantiles (>= {RAIN_THRESHOLD_MM} mm/h)",
            "daily_extremes": "min/max of hourly ensemble means (p10/p90 envelope reported separately)",
            "day_boundary": tz_label,
        },
    )
    ensemble = {
        "members": ENSEMBLE_MEMBERS, "member_data": False, "run_id": result.run_id,
        "statistics": sorted({s for e in series.values() for s in e["statistics"]}, key=STATISTICS.index),
        "series": {name: {**e, "values": e["values"][:360]} for name, e in series.items()},
        "note": "Precomputed ensemble statistics from the BigQuery surface table.",
    }
    return Forecast(
        location={"lat": lat, "lon": lon, "timezone": tz_label, "utc_offset_seconds": offset,
                  "timezone_source": "weathernext_approx",
                  "grid_cell": {"lat": round(result.cell_lat, 4), "lon": round(result.cell_lon, 4),
                                "resolution_deg": result.resolution_deg}},
        provenance=provenance, current=current, current_kind="model", hourly=hourly, daily=daily, ensemble=ensemble,
    )


def _daily(hourly: list[HourPoint], temp_q: dict, offset: int, forecast_days: int, now: datetime) -> list[DayPoint]:
    shift = timedelta(seconds=offset)
    buckets: "OrderedDict[str, list[HourPoint]]" = OrderedDict()
    for p in hourly:
        buckets.setdefault((p.time_utc + shift).date().isoformat(), []).append(p)
    today = (now + shift).date().isoformat()
    out: list[DayPoint] = []
    for date, pts in buckets.items():
        if date < today or len(out) >= forecast_days:
            continue
        temps = [p.temperature_c for p in pts if p.temperature_c is not None]
        rains = [p.precipitation_mm for p in pts if p.precipitation_mm is not None]
        winds = [p.wind_speed_kmh for p in pts if p.wind_speed_kmh is not None]
        pops = [p.precipitation_probability for p in pts if p.precipitation_probability is not None]
        codes = [p.weather_code for p in pts if p.weather_code is not None]
        p10 = [temp_q[p.time_utc]["p10"] for p in pts if "p10" in temp_q.get(p.time_utc, {})]
        p90 = [temp_q[p.time_utc]["p90"] for p in pts if "p90" in temp_q.get(p.time_utc, {})]
        code = max(codes) if codes else None
        out.append(DayPoint(
            date=date,
            high_c=round(max(temps), 1) if temps else None, low_c=round(min(temps), 1) if temps else None,
            high_p90_c=round(max(p90), 1) if p90 else None, low_p10_c=round(min(p10), 1) if p10 else None,
            rain_probability=max(pops) if pops else None,
            precipitation_mm=round(sum(rains), 2) if rains else None,
            wind_kmh_max=round(max(winds), 1) if winds else None,
            weather_code=code, condition=next((p.condition for p in pts if p.weather_code == code), None),
            hours_covered=len(pts), covers_full_day=len(pts) >= 24,
            precipitation_interval="24h" if len(pts) >= 24 else f"{len(pts)}h",
            statistic="ensemble_mean", source="weathernext",
        ))
    return out
