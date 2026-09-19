"""Member-first daily/risk calculations and scientific aggregation.

Implements section 6 scientific correctness rules:
- Daily uncertainty: sum rain within each member first, then quantiles
- Wind: compute speed from U/V before averaging
- Precipitation: member exceedance counts for probability
- Coherent trajectories: don't mix runs or member identities
- Solar: J/m² divided by interval seconds for W/m²
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from services.forecast_models import (
    ForecastPoint,
    bounded,
    is_finite,
    uv_component_to_speed,
    uv_to_direction,
)


@dataclass
class DailyAggregate:
    date: str
    temp_min_c: Optional[float] = None
    temp_max_c: Optional[float] = None
    rain_sum_mm: Optional[float] = None
    rain_probability: Optional[float] = None
    wind_max_kmh: Optional[float] = None
    # Ensemble stats
    rain_p10_mm: Optional[float] = None
    rain_p50_mm: Optional[float] = None
    rain_p90_mm: Optional[float] = None
    temp_min_p10: Optional[float] = None
    temp_max_p90: Optional[float] = None
    valid_member_count: int = 0
    expected_member_count: int = 0
    coverage: float = 1.0
    missing_reason: Optional[str] = None


def aggregate_daily_member_first(
    hourly_by_member: dict[int, list[ForecastPoint]],
    date: str,
    timezone_str: str = "UTC",
) -> DailyAggregate:
    """Aggregate daily stats member-first, then quantiles.

    hourly_by_member: {member_id: [ForecastPoint]}
    For each member, sum rain over local day, then compute quantiles across members.

    This is correct: sum rain within each member first, then quantiles.
    Wrong: summing hourly p90 rainfall is not daily p90.
    """
    if not hourly_by_member:
        return DailyAggregate(date=date, missing_reason="no_members")

    # Group by member
    member_sums = []
    member_mins = []
    member_maxs = []
    member_wind_max = []

    for member_id, points in hourly_by_member.items():
        # Filter points for this date (simplified - should use local timezone)
        day_points = [p for p in points if p.time_utc.date().isoformat() == date]
        if not day_points:
            continue

        # Per-member daily sum/min/max
        rains = [p.precipitation_mm for p in day_points if p.precipitation_mm is not None and is_finite(p.precipitation_mm)]
        temps = [p.temperature_c for p in day_points if p.temperature_c is not None and is_finite(p.temperature_c)]
        winds = [p.wind_speed_kmh for p in day_points if p.wind_speed_kmh is not None and is_finite(p.wind_speed_kmh)]

        if rains:
            member_sums.append(sum(rains))
        if temps:
            member_mins.append(min(temps))
            member_maxs.append(max(temps))
        if winds:
            member_wind_max.append(max(winds))

    if not member_sums and not member_mins:
        return DailyAggregate(date=date, missing_reason="no_valid_data_for_date")

    def quantile(data: list[float], q: float) -> Optional[float]:
        if not data:
            return None
        sorted_data = sorted(data)
        idx = q * (len(sorted_data) - 1)
        lower = math.floor(idx)
        upper = math.ceil(idx)
        if lower == upper:
            return sorted_data[int(idx)]
        weight = idx - lower
        return sorted_data[lower] * (1 - weight) + sorted_data[upper] * weight

    agg = DailyAggregate(date=date)
    if member_sums:
        agg.rain_sum_mm = quantile(member_sums, 0.5)  # median
        agg.rain_p10_mm = quantile(member_sums, 0.1)
        agg.rain_p50_mm = quantile(member_sums, 0.5)
        agg.rain_p90_mm = quantile(member_sums, 0.9)
        agg.valid_member_count = len(member_sums)
        agg.expected_member_count = len(hourly_by_member)

    if member_mins:
        agg.temp_min_c = quantile(member_mins, 0.1)  # conservative min
    if member_maxs:
        agg.temp_max_c = quantile(member_maxs, 0.9)  # conservative max
    if member_wind_max:
        agg.wind_max_kmh = quantile(member_wind_max, 0.9)

    # Coverage
    if agg.expected_member_count > 0:
        agg.coverage = agg.valid_member_count / agg.expected_member_count

    return agg


def calculate_precipitation_probability(
    member_precip: list[float],
    threshold_mm: float = 0.1,
) -> tuple[float, int, int]:
    """Calculate rain probability from member exceedance counts.

    Returns (probability 0..100, valid_count, expected_count)
    """
    if not member_precip:
        return 0.0, 0, 0

    valid = [p for p in member_precip if is_finite(p)]
    if not valid:
        return 0.0, 0, len(member_precip)

    exceed = sum(1 for p in valid if p >= threshold_mm)
    prob = (exceed / len(valid)) * 100.0
    return prob, len(valid), len(member_precip)


def aggregate_wind_from_uv(
    u_components: list[float],
    v_components: list[float],
) -> tuple[Optional[float], Optional[float]]:
    """Compute wind speed/direction from U/V components member-first.

    Correct: compute speed from member-level U/V before averaging.
    Wrong: speed of mean U/V is not mean speed.
    """
    if not u_components or not v_components or len(u_components) != len(v_components):
        return None, None

    speeds = []
    dirs = []

    for u, v in zip(u_components, v_components):
        if not (is_finite(u) and is_finite(v)):
            continue
        speed = uv_component_to_speed(u, v)
        direction = uv_to_direction(u, v)
        speeds.append(speed)
        if direction is not None:
            dirs.append(direction)

    if not speeds:
        return None, None

    mean_speed = sum(speeds) / len(speeds)

    # Circular mean for direction
    if not dirs:
        return mean_speed, None

    # Convert to unit vectors, average, then back to angle
    sin_sum = sum(math.sin(math.radians(d)) for d in dirs)
    cos_sum = sum(math.cos(math.radians(d)) for d in dirs)
    mean_dir = math.degrees(math.atan2(sin_sum, cos_sum)) % 360

    return mean_speed, mean_dir


def calculate_joint_probability(
    member_trajectories: list[dict],
    constraints: dict,
) -> tuple[float, int, int]:
    """Count members whose complete trajectories satisfy all constraints.

    For joint work conditions, count members whose complete trajectories satisfy
    all approved rain/wind/temperature constraints over candidate interval.

    Do not multiply hourly probabilities or combine unrelated marginals.
    """
    if not member_trajectories:
        return 0.0, 0, 0

    valid_count = 0
    satisfying = 0

    for traj in member_trajectories:
        # traj should have complete hourly data for interval
        points = traj.get("points", [])
        if not points:
            continue
        valid_count += 1

        # Check all constraints over complete trajectory
        satisfies_all = True
        for point in points:
            # Rain constraint
            if "max_rain_mm" in constraints:
                if point.get("precipitation_mm", 0) > constraints["max_rain_mm"]:
                    satisfies_all = False
                    break
            # Wind constraint
            if "max_wind_kmh" in constraints:
                if point.get("wind_speed_kmh", 0) > constraints["max_wind_kmh"]:
                    satisfies_all = False
                    break
            # Temp constraints
            if "min_temp_c" in constraints:
                if point.get("temperature_c", 0) < constraints["min_temp_c"]:
                    satisfies_all = False
                    break
            if "max_temp_c" in constraints:
                if point.get("temperature_c", 100) > constraints["max_temp_c"]:
                    satisfies_all = False
                    break

        if satisfies_all:
            satisfying += 1

    prob = (satisfying / valid_count * 100) if valid_count > 0 else 0.0
    return prob, satisfying, valid_count


# ---------------------------------------------------------------------------
# Client-facing summaries (Flutter "Everyone" card: spread + next-24h rain)
# ---------------------------------------------------------------------------

def build_temperature_spread(forecast: Any, now: Optional[datetime] = None, window_hours: int = 24) -> Optional[dict]:
    """p10-p90 temperature envelope over the next ``window_hours``.

    Only providers that ship ensemble quantiles (WeatherNext) can produce this;
    returns None otherwise - a one-sided or fabricated spread is never emitted.
    The envelope is min(p10) .. max(p90) across the window: the range within
    which each hour's temperature sits with >= 80 % ensemble support.
    """
    ensemble = getattr(forecast, "ensemble", None) or {}
    series = (ensemble.get("series") or {}).get("temperature_2m") or {}
    values = series.get("values") or []
    if not values:
        return None
    now = now or datetime.now(timezone.utc)
    end = now + timedelta(hours=window_hours)
    p10s: list[float] = []
    p90s: list[float] = []
    times: list[datetime] = []
    for entry in values:
        try:
            t = datetime.fromisoformat(str(entry.get("time_utc")).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        if t < now - timedelta(minutes=30) or t > end:
            continue
        lo, hi = entry.get("p10"), entry.get("p90")
        if lo is None or hi is None or not (is_finite(lo) and is_finite(hi)):
            continue
        p10s.append(float(lo))
        p90s.append(float(hi))
        times.append(t)
    if not p10s or not p90s:
        return None
    low, high = min(p10s), max(p90s)
    if high < low:
        return None
    prov = getattr(forecast, "provenance", None)
    return {
        "p10_c": round(low, 1),
        "p90_c": round(high, 1),
        "valid_from": min(times).isoformat(),
        "valid_to": max(times).isoformat(),
        "hours": len(times),
        "members": ensemble.get("members"),
        "source": prov.selected_source.value if prov else None,
        "run_id": prov.run_id if prov else None,
        "method": "min_p10_max_p90_over_window",
    }


def build_precip_next_24h(forecast: Any, now: Optional[datetime] = None, window_hours: int = 24) -> Optional[dict]:
    """Expected precipitation total over the next ``window_hours`` from hourly points.

    Sums hourly amounts (for WeatherNext these are ensemble *means*, which are
    linear and therefore valid to sum; quantiles are never summed). Reports
    coverage so a partial interval is never presented as a full-period total.
    """
    hourly = list(getattr(forecast, "hourly", None) or [])
    if not hourly:
        return None
    now = now or datetime.now(timezone.utc)
    end = now + timedelta(hours=window_hours)
    total = 0.0
    times: list[datetime] = []
    for p in hourly:
        t = getattr(p, "time_utc", None)
        if t is None or t < now - timedelta(minutes=30) or t > end:
            continue
        amount = getattr(p, "precipitation_mm", None)
        if amount is None or not is_finite(amount):
            continue
        total += max(0.0, float(amount))
        times.append(t)
    if not times:
        return None
    prov = getattr(forecast, "provenance", None)
    statistic = "ensemble_mean" if any(getattr(p, "is_ensemble_mean", False) for p in hourly) else "deterministic"
    return {
        "total_mm": round(total, 2),
        "start": min(times).isoformat(),
        "end": max(times).isoformat(),
        "hours": len(times),
        "complete": len(times) >= window_hours,
        "label": f"next_{window_hours}h",
        "statistic": statistic,
        "source": prov.selected_source.value if prov else None,
        "run_id": prov.run_id if prov else None,
    }


def solar_j_to_w(joules_per_m2: float, interval_hours: int) -> float:
    """Convert interval solar J/m² to average W/m²."""
    seconds = interval_hours * 3600
    if seconds <= 0:
        return 0.0
    return joules_per_m2 / seconds
