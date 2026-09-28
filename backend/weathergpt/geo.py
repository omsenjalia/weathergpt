"""Geocoding: place name -> coordinates (Open-Meteo) and coordinates -> district (OSM Nominatim).

Nominatim's usage policy requires an identifying User-Agent and <= 1 request/s;
results are cached per ~5 km cell for a day, so steady-state traffic is tiny.
"""

from __future__ import annotations

import threading
import time
from typing import Optional

from weathergpt import http
from weathergpt.config import settings
from weathergpt.runtime import make_cache

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"

_forward = make_cache("geocode", 512)
_reverse = make_cache("reverse_geocode", 1024)
_reverse_lock = threading.Lock()
_last_reverse = 0.0


def geocode(name: str, *, country_bias: str = "IN") -> Optional[dict]:
    """Best match for a place name, preferring India. None when not found / unreachable."""
    query = (name or "").strip()
    if len(query) < 2:
        return None
    key = query.lower()
    hit = _forward.get(key)
    if hit is not None:
        return hit or None
    try:
        data = http.get_json(GEOCODING_URL, {"name": query, "count": 5, "language": "en", "format": "json"}, timeout=6.0)
    except http.UpstreamError:
        return None
    results = (data or {}).get("results") or []
    if not results:
        _forward.set(key, {}, 3600)
        return None
    best = next((r for r in results if r.get("country_code") == country_bias), results[0])
    out = {
        "name": best.get("name") or query,
        "lat": float(best["latitude"]),
        "lon": float(best["longitude"]),
        "admin1": best.get("admin1"),
        "admin2": best.get("admin2"),
        "country": best.get("country"),
        "country_code": best.get("country_code"),
        "timezone": best.get("timezone"),
    }
    _forward.set(key, out, 86400)
    return out


def reverse(lat: float, lon: float) -> Optional[dict]:
    """District/state for a point (Nominatim zoom 10). None when unavailable."""
    global _last_reverse
    key = f"{round(lat / 0.05) * 0.05:.2f}:{round(lon / 0.05) * 0.05:.2f}"
    hit = _reverse.get(key)
    if hit is not None:
        return hit or None
    with _reverse_lock:  # respect Nominatim's 1 req/s policy per instance
        wait = 1.0 - (time.time() - _last_reverse)
        if wait > 0:
            time.sleep(wait)
        _last_reverse = time.time()
    try:
        data = http.get_json(REVERSE_URL, {"lat": f"{lat:.5f}", "lon": f"{lon:.5f}", "format": "jsonv2",
                                           "zoom": 10, "accept-language": "en", "addressdetails": 1},
                             headers={"User-Agent": settings().nominatim_user_agent}, timeout=6.0, retries=0)
    except http.UpstreamError:
        _reverse.set(key, {}, 300)
        return None
    addr = (data or {}).get("address") or {}
    out = {
        "district": addr.get("state_district") or addr.get("county") or addr.get("city_district") or addr.get("city"),
        "state": addr.get("state"),
        "country_code": (addr.get("country_code") or "").upper() or None,
        "display_name": (data or {}).get("display_name"),
        "source": "openstreetmap_nominatim",
    }
    _reverse.set(key, out, 86400)
    return out
