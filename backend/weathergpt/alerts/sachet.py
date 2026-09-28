"""NDMA SACHET — India's national CAP alert feed (key-less, public domain).

IMD regional centres, CWC and state disaster authorities publish here, so it is
the official warnings channel that works even without IMD gateway credentials.

- ``FetchAllAlertDetails``: every active alert with centroid "lon,lat" and area km².
- ``FetchPolygonXMLFile?identifier=``: the alert's exact polygon(s) ("lat,lon lat,lon ...").

An alert applies to a point when the point is inside its polygon; when the
polygon cannot be fetched, a centroid/area radius test (with a margin) decides.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from weathergpt import http
from weathergpt.imd.parse import haversine_km
from weathergpt.runtime import make_cache

BASE = "https://sachet.ndma.gov.in/cap_public_website"
ALL_ALERTS_URL = f"{BASE}/FetchAllAlertDetails"
POLYGON_URL = f"{BASE}/FetchPolygonXMLFile"
XML_URL = f"{BASE}/FetchXMLFile"

_feed = make_cache("sachet_feed", 4)
_polygons = make_cache("sachet_polygons", 512)
IST = timezone(timedelta(hours=5, minutes=30))
_MONTHS = {m: i for i, m in enumerate(("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1)}
SEVERITY_RANK = {"red": 3, "orange": 2, "yellow": 1, "green": 0, "info": 0}


def parse_time(raw: Optional[str]) -> Optional[datetime]:
    """'Mon Sep 28 12:10:00 IST 2026' or ISO-8601 -> aware UTC datetime."""
    if not raw:
        return None
    s = str(raw).strip()
    m = re.match(r"^\w{3}\s+(\w{3})\s+(\d{1,2})\s+(\d{2}):(\d{2}):(\d{2})\s+(\w+)\s+(\d{4})$", s)
    if m and m.group(1) in _MONTHS:
        tz = IST if m.group(6) == "IST" else timezone.utc
        dt = datetime(int(m.group(7)), _MONTHS[m.group(1)], int(m.group(2)), int(m.group(3)), int(m.group(4)),
                      int(m.group(5)), tzinfo=tz)
        return dt.astimezone(timezone.utc)
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return (dt if dt.tzinfo else dt.replace(tzinfo=IST)).astimezone(timezone.utc)
    except ValueError:
        return None


def fetch_feed() -> list[dict]:
    hit = _feed.get("all")
    if hit is not None:
        return hit
    data = http.get_json(ALL_ALERTS_URL, timeout=8.0)
    rows = data if isinstance(data, list) else []
    _feed.set("all", rows, 300)
    return rows


def polygons(identifier: str) -> Optional[list[list[tuple[float, float]]]]:
    key = str(identifier)
    hit = _polygons.get(key)
    if hit is not None:
        return hit or None
    try:
        reply = http.send("GET", POLYGON_URL, params={"identifier": key}, timeout=6.0, retries=0)
    except http.UpstreamError:
        return None
    if reply.status >= 400:
        _polygons.set(key, [], 600)
        return None
    out = []
    for block in re.findall(r"<polygon>(.*?)</polygon>", reply.text, flags=re.S):
        ring = []
        for pair in block.split():
            try:
                la, lo = pair.split(",")[:2]
                ring.append((float(la), float(lo)))
            except ValueError:
                continue
        if len(ring) >= 3:
            out.append(ring)
    _polygons.set(key, out, 3600)
    return out or None


def point_in_ring(lat: float, lon: float, ring: list[tuple[float, float]]) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        yi, xi = ring[i]
        yj, xj = ring[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def _centroid(row: dict) -> Optional[tuple[float, float]]:
    try:
        lon_s, lat_s = str(row.get("centroid") or "").split(",")[:2]
        return float(lat_s), float(lon_s)
    except ValueError:
        return None


def _severity(row: dict) -> str:
    color = str(row.get("severity_color") or "").strip().lower()
    return color if color in SEVERITY_RANK else "info"


def alerts_for(lat: float, lon: float, *, now: Optional[datetime] = None, max_polygon_checks: int = 8) -> list[dict]:
    """Active SACHET alerts covering (lat, lon). Raises ``http.UpstreamError`` if the feed is unreachable."""
    now = now or datetime.now(timezone.utc)
    candidates = []
    for row in fetch_feed():
        if not isinstance(row, dict):
            continue
        end = parse_time(row.get("effective_end_time"))
        if end is not None and end < now:
            continue
        c = _centroid(row)
        if c is None:
            continue
        try:
            area = max(0.0, float(row.get("area_covered") or 0))
        except (TypeError, ValueError):
            area = 0.0
        radius = math.sqrt(area / math.pi) if area else 25.0
        distance = haversine_km(lat, lon, c[0], c[1])
        # Generous pre-filter: irregular areas extend past the equal-area radius.
        if distance <= radius * 2.0 + 15.0:
            candidates.append((distance, radius, row))

    candidates.sort(key=lambda x: x[0])
    out = []
    for i, (distance, radius, row) in enumerate(candidates):
        rings = polygons(row.get("identifier")) if i < max_polygon_checks else None
        if rings is not None:
            if not any(point_in_ring(lat, lon, r) for r in rings):
                continue
            match = "polygon"
        elif distance <= radius * 1.2 + 5.0:
            match = "centroid_radius"
        else:
            continue
        out.append({
            "id": f"sachet:{row.get('identifier')}",
            "source": "ndma_sachet",
            "issuer": row.get("alert_source"),
            "official": True,
            "type": "cap_alert",
            "event": row.get("disaster_type"),
            "severity": _severity(row),
            "cap_severity": row.get("severity"),
            "certainty": row.get("severity_level"),
            "headline": (row.get("warning_message") or "").strip(),
            "area": (row.get("area_description") or "").strip(),
            "language": row.get("actual_lang"),
            "onset": _iso(parse_time(row.get("effective_start_time"))),
            "expires": _iso(parse_time(row.get("effective_end_time"))),
            "url": f"{XML_URL}?identifier={row.get('identifier')}",
            "match": match,
        })
    return out


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None
