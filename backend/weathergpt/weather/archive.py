"""Yearly climate series from the Open-Meteo ERA5 archive (researcher screens)."""

from __future__ import annotations

import concurrent.futures
from datetime import date
from typing import Optional

from weathergpt import http
from weathergpt.runtime import make_cache

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
METRICS = {
    "rainfall": ("precipitation_sum", "sum", "mm"),
    "temperature": ("temperature_2m_mean", "mean", "C"),
    "humidity": ("relative_humidity_2m_mean", "mean", "%"),
}
_cache = make_cache("archive", 256)


def last_full_year() -> int:
    return date.today().year - 1


def yearly_series(lat: float, lon: float, metric: str, start_year: int, end_year: int) -> dict:
    """Raises ValueError for bad input and ``http.UpstreamError`` when the archive fails."""
    key = metric.lower().strip()
    if key not in METRICS:
        raise ValueError(f"metric must be one of: {', '.join(METRICS)}")
    if end_year < start_year:
        raise ValueError("end_year must be >= start_year")
    if end_year - start_year > 40:
        raise ValueError("Maximum range is 40 years")
    daily_var, how, units = METRICS[key]
    cache_key = f"{round(lat, 2)}:{round(lon, 2)}:{key}:{start_year}:{end_year}"
    hit = _cache.get(cache_key)
    if hit is not None:
        return hit
    data = http.get_json(ARCHIVE_URL, {
        "latitude": round(lat, 4), "longitude": round(lon, 4),
        "start_date": f"{start_year}-01-01", "end_date": f"{end_year}-12-31",
        "daily": daily_var, "timezone": "auto",
    }, timeout=30.0)
    daily = (data or {}).get("daily") or {}
    buckets: dict[int, list[float]] = {}
    for t, v in zip(daily.get("time") or [], daily.get(daily_var) or []):
        if v is None:
            continue
        try:
            buckets.setdefault(int(str(t)[:4]), []).append(float(v))
        except (TypeError, ValueError):
            continue
    points = []
    for year in range(start_year, end_year + 1):
        vals = buckets.get(year)
        if not vals:
            continue
        # A year with large gaps would under-report a sum; require 90% coverage.
        if how == "sum" and len(vals) < 330:
            continue
        points.append({"year": year, "value": round(sum(vals), 1) if how == "sum" else round(sum(vals) / len(vals), 2),
                       "days": len(vals)})
    out = {"lat": lat, "lon": lon, "metric": key, "units": units, "aggregation": how,
           "start_year": start_year, "end_year": end_year, "points": points, "source": "open-meteo-archive",
           "dataset": "ERA5 reanalysis via Open-Meteo"}
    _cache.set(cache_key, out, 86400)
    return out


def parse_locations(raw: str) -> list[tuple[str, float, float]]:
    """'name,lat,lon;name2,lat2,lon2' — names may contain commas ("Pune, Maharashtra, India")."""
    out = []
    for chunk in (raw or "").split(";"):
        parts = chunk.rsplit(",", 2)
        if len(parts) != 3:
            continue
        name, lat_s, lon_s = (p.strip() for p in parts)
        try:
            lat, lon = float(lat_s), float(lon_s)
        except ValueError:
            continue
        if name and -90 <= lat <= 90 and -180 <= lon <= 180:
            out.append((name, lat, lon))
    return out[:8]


def comparison(locations: list[tuple[str, float, float]], metric: str, start_year: int, end_year: int) -> dict:
    def one(loc):
        name, lat, lon = loc
        try:
            series = yearly_series(lat, lon, metric, start_year, end_year)
            return {"name": name, "lat": lat, "lon": lon, "points": series["points"]}
        except http.UpstreamError as exc:
            return {"name": name, "lat": lat, "lon": lon, "points": [], "error": exc.reason}

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        series = list(pool.map(one, locations))
    return {"metric": metric.lower().strip(), "start_year": start_year, "end_year": end_year,
            "units": METRICS[metric.lower().strip()][2], "locations": series, "source": "open-meteo-archive"}


def default_range(start_year: Optional[int], end_year: Optional[int], span: int = 25) -> tuple[int, int]:
    end = end_year or last_full_year()
    return (start_year or end - span + 1), end
