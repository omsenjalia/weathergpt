"""Tolerant readers for IMD rows.

IMD field names mix styles ("Station Id", "M.S.L.P", "Todays_Forecast_Max_Temp",
"Day_2_Min_temp") and values use "NA", "--", "" or "Trace". Keys are matched
case/punctuation-insensitively; placeholder values become None.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Optional

IST = timezone(timedelta(hours=5, minutes=30))
IST_OFFSET_SECONDS = 19800
_NULLS = {"", "na", "n/a", "nan", "null", "none", "--", "-", "nil", "nd", "*", "999", "999.0", "-999"}


def norm_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def value(row: dict, *names: str) -> Any:
    """First present, non-placeholder value among ``names`` (normalized match)."""
    if not isinstance(row, dict):
        return None
    index = {norm_key(k): v for k, v in row.items()}
    for name in names:
        v = index.get(norm_key(name))
        if v is None:
            continue
        if isinstance(v, str) and v.strip().lower() in _NULLS:
            continue
        return v.strip() if isinstance(v, str) else v
    return None


def number(row: dict, *names: str, low: Optional[float] = None, high: Optional[float] = None) -> Optional[float]:
    v = value(row, *names)
    if v is None:
        return None
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("trace", "tr"):
            return 0.0
        m = re.search(r"-?\d+(?:\.\d+)?", s)
        if not m:
            return None
        v = m.group(0)
    try:
        num = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(num):
        return None
    if (low is not None and num < low) or (high is not None and num > high):
        return None
    return num


def text(row: dict, *names: str) -> Optional[str]:
    v = value(row, *names)
    return str(v).strip() if v is not None and str(v).strip() else None


def parse_date(raw: Any) -> Optional[date]:
    if raw is None:
        return None
    s = str(raw).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def parse_hhmm(raw: Any) -> Optional[tuple[int, int]]:
    """'06:12', '0612', '6:12 AM', '18:31' -> (hour, minute)."""
    if raw is None:
        return None
    s = str(raw).strip().upper()
    m = re.match(r"^(\d{1,2})[:.]?(\d{2})\s*(AM|PM)?", s)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if m.group(3) == "PM" and h < 12:
        h += 12
    if m.group(3) == "AM" and h == 12:
        h = 0
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        return None
    return h, mi


def local_stamp(day: Optional[date], hhmm: Any) -> Optional[str]:
    """Naive location-local 'YYYY-MM-DDTHH:MM' (the format Open-Meteo uses for sun times)."""
    t = parse_hhmm(hhmm)
    if day is None or t is None:
        return None
    return f"{day.isoformat()}T{t[0]:02d}:{t[1]:02d}"


def observation_time_utc(row: dict) -> Optional[datetime]:
    """current_wx: 'Date of Observation' + 'Time of Observation' (documented as UTC)."""
    day = parse_date(value(row, "Date of Observation", "Date", "date_obs", "DATE"))
    t = parse_hhmm(value(row, "Time of Observation", "Time of Observation (UTC)", "Time", "TIME", "UTC"))
    if day is None:
        return None
    h, m = t if t else (0, 0)
    return datetime(day.year, day.month, day.day, h, m, tzinfo=timezone.utc)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def station_code(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if s.isdigit():
        return s.lstrip("0") or s
    return s.upper()


def iter_dicts(rows: Iterable) -> Iterable[dict]:
    for row in rows or []:
        if isinstance(row, dict):
            yield row
