"""Everyone-mode summaries: ensemble temperature spread and next-24 h precipitation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from weathergpt.weather.models import Forecast, finite


def temperature_spread(forecast: Forecast, now: Optional[datetime] = None, window_hours: int = 24) -> Optional[dict]:
    """min(p10)..max(p90) over the next window. Only ensemble providers can support this."""
    series = ((forecast.ensemble or {}).get("series") or {}).get("temperature_2m") or {}
    now = now or datetime.now(timezone.utc)
    end = now + timedelta(hours=window_hours)
    lows, highs, times = [], [], []
    for entry in series.get("values") or []:
        try:
            t = datetime.fromisoformat(str(entry.get("time_utc")).replace("Z", "+00:00"))
        except ValueError:
            continue
        lo, hi = finite(entry.get("p10")), finite(entry.get("p90"))
        if lo is None or hi is None or t < now - timedelta(minutes=30) or t > end:
            continue
        lows.append(lo)
        highs.append(hi)
        times.append(t)
    if not lows or max(highs) < min(lows):
        return None
    return {
        "p10_c": round(min(lows), 1), "p90_c": round(max(highs), 1),
        "valid_from": min(times).isoformat(), "valid_to": max(times).isoformat(), "hours": len(times),
        "members": (forecast.ensemble or {}).get("members"), "source": forecast.provenance.source,
        "run_id": forecast.provenance.run_id, "method": "min_p10_max_p90_over_window",
    }


def precip_next_24h(forecast: Forecast, now: Optional[datetime] = None, window_hours: int = 24) -> Optional[dict]:
    """Sum of hourly amounts over the next window; ``complete`` says whether every hour was present."""
    if not forecast.hourly:
        return None
    now = now or datetime.now(timezone.utc)
    # The bucket still running at ``now`` plus the next ones: exactly ``window_hours`` buckets.
    buckets = sorted((p for p in forecast.hourly if p.time_utc + timedelta(hours=1) > now), key=lambda p: p.time_utc)
    buckets = [p for p in buckets if p.time_utc < buckets[0].time_utc + timedelta(hours=window_hours)] if buckets else []
    total, times = 0.0, []
    for p in buckets:
        if p.precipitation_mm is None:
            continue
        total += max(0.0, p.precipitation_mm)
        times.append(p.time_utc)
    if not times:
        return None
    hourly_source = forecast.field_sources.get("hourly") or forecast.provenance.source
    return {
        "total_mm": round(total, 2), "start": min(times).isoformat(), "end": max(times).isoformat(),
        "hours": len(times), "complete": len(times) >= window_hours, "label": f"next_{window_hours}h",
        "statistic": "ensemble_mean" if any(p.is_ensemble_mean for p in forecast.hourly) else "deterministic",
        "source": hourly_source, "run_id": forecast.provenance.run_id if hourly_source == forecast.provenance.source else None,
    }
