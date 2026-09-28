"""IMD district warnings (5 days) and district nowcast (next ~3 h) for a point.

The point is resolved to a district name (OSM Nominatim) and matched against
IMD's district list. IMD spellings differ from OSM's ("AHMADABAD" vs
"Ahmedabad"), so names are compared after normalisation with a fuzzy fallback.

Colour scales differ between the two APIs (per the IMD API reference):
    districtwarning  Day*_Color: 1 red, 2 orange, 3 yellow, 4 green
    districtnowcast  color:      1 green, 2 yellow, 3 orange, 4 red
"""

from __future__ import annotations

import difflib
import re
from datetime import timedelta
from typing import Optional

from weathergpt.imd import client
from weathergpt.imd.parse import iter_dicts, number, parse_date, text

WARNING_CODES = {
    1: "No warning", 2: "Heavy rain", 3: "Heavy snow", 4: "Thunderstorm & lightning, squall",
    5: "Hailstorm", 6: "Dust storm", 7: "Dust raising winds", 8: "Strong surface winds", 9: "Heat wave",
    10: "Hot day", 11: "Warm night", 12: "Cold wave", 13: "Cold day", 14: "Ground frost", 15: "Fog",
    16: "Very heavy rain", 17: "Extremely heavy rain",
}
WARNING_COLOR = {1: "red", 2: "orange", 3: "yellow", 4: "green"}
NOWCAST_COLOR = {1: "green", 2: "yellow", 3: "orange", 4: "red"}
NOWCAST_CATEGORIES = {
    1: "No weather", 2: "Light rain", 3: "Light snow", 4: "Light thunderstorm", 5: "Slight dust storm",
    6: "Low lightning probability", 7: "Moderate rain", 8: "Moderate snow", 9: "Moderate thunderstorm",
    10: "Moderate dust storm", 11: "Moderate lightning probability", 12: "Heavy rain", 13: "Heavy snow",
    14: "Severe thunderstorm", 15: "Very severe thunderstorm", 31: "Thunderstorm with hail",
    32: "Severe dust storm", 33: "High lightning probability",
}
_STRIP = re.compile(r"\b(district|dist|rural|urban|city|division)\b")


def _norm(name: str) -> str:
    return re.sub(r"[^a-z]", "", _STRIP.sub("", (name or "").lower()))


def match_district(name: Optional[str], rows: list[dict]) -> Optional[dict]:
    if not name:
        return None
    target = _norm(name)
    if not target:
        return None
    by_name = {}
    for row in rows:
        d = text(row, "District", "DISTRICT", "district_name")
        if d:
            by_name.setdefault(_norm(d), row)
    if target in by_name:
        return by_name[target]
    close = difflib.get_close_matches(target, list(by_name), n=1, cutoff=0.8)
    return by_name[close[0]] if close else None


def _codes(raw) -> list[int]:
    out = []
    for part in re.split(r"[,\s]+", str(raw or "")):
        if part.strip().isdigit():
            out.append(int(part))
    return out


def district_warnings(row: dict) -> list[dict]:
    issued = parse_date(text(row, "Date", "date_obs"))
    district = text(row, "District")
    out = []
    for n in range(1, 6):
        codes = [c for c in _codes(text(row, f"Day_{n}", f"Day{n}")) if c != 1]
        color_code = number(row, f"Day{n}_Color", f"Day_{n}_Color", f"day{n}_color")
        severity = WARNING_COLOR.get(int(color_code)) if color_code is not None else None
        if not codes or severity in (None, "green"):
            continue
        hazards = [WARNING_CODES.get(c, f"Warning {c}") for c in codes]
        date = (issued + timedelta(days=n - 1)).isoformat() if issued else None
        out.append({
            "id": f"imd:district_warning:{text(row, 'Obj_id', 'OBJ_ID')}:{date or n}",
            "source": "imd", "issuer": "India Meteorological Department", "official": True,
            "type": "district_warning", "event": ", ".join(hazards), "hazards": hazards, "hazard_codes": codes,
            "severity": severity, "day": n, "date": date, "area": district,
            "headline": f"{severity.title()} warning for {district}: {', '.join(hazards)}" + (f" on {date}" if date else ""),
            "issued_utc": text(row, "UTC"),
        })
    return out


def nowcast_alert(row: dict) -> Optional[dict]:
    color_code = number(row, "color", "Color")
    severity = NOWCAST_COLOR.get(int(color_code)) if color_code is not None else None
    if severity in (None, "green"):
        return None
    cats = []
    for key, value in row.items():
        if re.fullmatch(r"(?i)cat\d+", str(key)) and str(value).strip().isdigit():
            code = int(str(value).strip())
            if code != 1 and code in NOWCAST_CATEGORIES:
                cats.append(NOWCAST_CATEGORIES[code])
    toi, upto = text(row, "toi"), text(row, "vupto", "Vupto")
    return {
        "id": f"imd:nowcast:{text(row, 'Obj_id', 'Station')}:{text(row, 'Date')}:{toi}",
        "source": "imd", "issuer": "India Meteorological Department", "official": True,
        "type": "nowcast", "event": ", ".join(cats) or "Nowcast warning", "hazards": cats,
        "severity": severity, "area": text(row, "State_District", "District", "Station"),
        "headline": text(row, "message") or ", ".join(cats),
        "date": text(row, "Date"), "issued_ist": toi, "valid_until_ist": upto,
    }


CITY_WARNING_COLORS = {"red": "red", "orange": "orange", "yellow": "yellow", "green": "green"}


def city_warnings(row: dict) -> list[dict]:
    """cityforecastwarning row -> per-day station warnings (colour names, e.g. 'green')."""
    issued = parse_date(text(row, "Date"))
    station = text(row, "Station_Name")
    out = []
    for n in range(1, 8):
        words = text(row, f"Day_{n}_Warning")
        color = (text(row, f"Day_{n}_Warning_Color") or "").lower()
        severity = CITY_WARNING_COLORS.get(color)
        if not words or severity in (None, "green") or words.strip().lower() == "no warning":
            continue
        date = (issued + timedelta(days=n - 1)).isoformat() if issued else None
        out.append({
            "id": f"imd:city_warning:{text(row, 'Station_Code')}:{date or n}",
            "source": "imd", "issuer": "India Meteorological Department", "official": True,
            "type": "city_warning", "event": words, "hazards": [words], "severity": severity,
            "day": n, "date": date, "area": station,
            "headline": f"{severity.title()} warning for {station}: {words}" + (f" on {date}" if date else ""),
        })
    return out


def alerts_for_district(district_name: Optional[str]) -> tuple[list[dict], Optional[dict]]:
    """(alerts, matched district) for a district name. Raises ``client.IMDError``."""
    rows = list(iter_dicts(client.fetch("district_warning").rows))
    row = match_district(district_name, rows)
    if row is None:
        return [], None
    district = {"name": text(row, "District"), "obj_id": text(row, "Obj_id", "OBJ_ID"), "matched_from": district_name}
    alerts = district_warnings(row)
    if district["obj_id"]:
        try:
            for nrow in iter_dicts(client.fetch("district_nowcast", {"id": district["obj_id"]}).rows):
                a = nowcast_alert(nrow)
                if a:
                    alerts.insert(0, a)
        except client.IMDError:
            pass  # the 5-day warning still stands; nowcast failure is reported by status()
    return alerts, district
