"""Farm action windows: deterministic hourly thresholds, official warnings, optional System One.

Layers, each only able to make a day *more* conservative:
1. Hourly threshold bands per activity (spraying / irrigation / field work).
2. Daily band from the day's rain, wind, heat and thunder.
3. Official IMD / NDMA warnings for that date (red -> poor, orange -> caution).
4. TypeSafe System One overlay (high-confidence answers only).

Wire vocabulary: daily ``suitability`` good | caution | poor | neutral (neutral =
insufficient data); hourly cells good | caution | avoid.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

from weathergpt.weather.codes import THUNDER_CODES
from weathergpt.weather.models import DayPoint, Forecast, HourPoint

ACTIVITIES = ("irrigation", "spraying", "field_work")
DAILY_RANK = {"good": 0, "neutral": 0, "caution": 1, "poor": 2}
HOURLY_RANK = {"good": 0, "caution": 1, "avoid": 2}
SCORE_LEVELS = ["Unsafe", "Risky", "Workable with care", "Good", "Ideal"]
VERDICT_TO_DAILY = {"avoid": "poor", "caution": "caution", "good": "good"}
BAND_COPY = {
    "good": "Good day for field work.",
    "caution": "Workable with caution — watch wind and showers.",
    "poor": "Conditions unsafe — avoid spraying and limit field work.",
    "neutral": "Not enough forecast data to judge this day — check local conditions.",
}


@dataclass(frozen=True)
class Rule:
    avoid_wind: float
    caution_wind: float
    avoid_pop: float
    caution_pop: float
    avoid_rain: float
    caution_rain: float
    avoid_temp_lo: float
    caution_temp_lo: float
    caution_temp_hi: float
    avoid_temp_hi: float
    thunder_is_avoid: bool = True


RULES = {
    # Drift and wash-off dominate: calm, dry, mild hours only.
    "spraying": Rule(25, 15, 60, 30, 0.5, 0.1, 5, 10, 35, 40),
    # Irrigating into rain wastes water; hot wind loses it to evaporation.
    "irrigation": Rule(35, 25, 60, 30, 1.0, 0.3, -15, -10, 38, 45, thunder_is_avoid=False),
    # People in the field: lightning, heavy rain, wind, heat, cold.
    "field_work": Rule(35, 25, 70, 40, 2.0, 0.5, 2, 8, 38, 42),
}


def worse_daily(a: str, b: str) -> str:
    return a if DAILY_RANK.get(a, 0) >= DAILY_RANK.get(b, 0) else b


def hour_band(activity: str, p: HourPoint) -> str:
    """Band for one hour. Missing rain/wind data is treated conservatively (avoid)."""
    rule = RULES[activity]
    if p.weather_code in THUNDER_CODES and rule.thunder_is_avoid:
        return "avoid"
    if p.precipitation_probability is None and p.precipitation_mm is None:
        return "avoid"
    if p.wind_speed_kmh is None:
        return "avoid"
    pop = p.precipitation_probability if p.precipitation_probability is not None else 0.0
    rain = p.precipitation_mm if p.precipitation_mm is not None else 0.0
    wind, temp = p.wind_speed_kmh, p.temperature_c
    if wind >= rule.avoid_wind or pop >= rule.avoid_pop or rain >= rule.avoid_rain:
        return "avoid"
    if temp is not None and (temp >= rule.avoid_temp_hi or temp <= rule.avoid_temp_lo):
        return "avoid"
    if wind >= rule.caution_wind or pop >= rule.caution_pop or rain >= rule.caution_rain:
        return "caution"
    if temp is not None and (temp >= rule.caution_temp_hi or temp <= rule.caution_temp_lo):
        return "caution"
    return "good"


def _label(hour: int) -> str:
    if hour == 0 or hour == 24:
        return "12 AM"
    if hour == 12:
        return "12 PM"
    return f"{hour - 12} PM" if hour > 12 else f"{hour} AM"


def best_window(cells: list[dict]) -> str:
    """Longest daylight run (5 AM – 7 PM) of good hours for field work, else caution hours."""
    for target, prefix in (("good", "Best"), ("caution", "Workable")):
        best: tuple[int, int] = (0, -1)
        start = None
        for cell in cells + [{"local_hour": 99, "suitability": "end"}]:
            h = cell["local_hour"]
            ok = 5 <= h < 19 and cell["suitability"] == target
            if ok and start is None:
                start = h
            if not ok and start is not None:
                if h - start > best[1] - best[0]:
                    best = (start, h)
                start = None
        if best[1] - best[0] >= 2:
            return f"{prefix}: {_label(best[0])}–{_label(best[1])}"
    return "Indoor / planning tasks"


def hourly_cells(hours: list[HourPoint], offset_seconds: int) -> dict[str, dict[str, list[dict]]]:
    """{local_date: {activity: [{hour, local_hour, suitability}]}}"""
    shift = timedelta(seconds=offset_seconds)
    out: dict[str, dict[str, list[dict]]] = {}
    for p in hours:
        local = p.time_utc + shift
        date = local.date().isoformat()
        for activity in ACTIVITIES:
            out.setdefault(date, {a: [] for a in ACTIVITIES})[activity].append({
                "hour": f"{local.hour:02d}:00", "local_hour": local.hour, "suitability": hour_band(activity, p),
            })
    return out


def daily_band(day: DayPoint) -> tuple[str, list[str]]:
    if day.rain_probability is None and day.precipitation_mm is None:
        return "neutral", ["insufficient_data"]
    band, reasons = "good", []
    rp, rain, wind, high = day.rain_probability, day.precipitation_mm, day.wind_kmh_max, day.high_c
    if (rp is not None and rp >= 70) or (rain is not None and rain >= 10):
        band, reasons = worse_daily(band, "poor"), reasons + ["heavy_rain_likely"]
    elif (rp is not None and rp >= 40) or (rain is not None and rain >= 2.5):
        band, reasons = worse_daily(band, "caution"), reasons + ["showers_possible"]
    if day.weather_code in THUNDER_CODES:
        band, reasons = worse_daily(band, "poor"), reasons + ["thunderstorm"]
    if wind is not None and wind >= 35:
        band, reasons = worse_daily(band, "poor"), reasons + ["strong_wind"]
    elif wind is not None and wind >= 25:
        band, reasons = worse_daily(band, "caution"), reasons + ["breezy"]
    if high is not None and high >= 40:
        band, reasons = worse_daily(band, "caution"), reasons + ["heat_stress"]
    return band, reasons


def _alert_applies(alert: dict, date: str, index: int, offset_seconds: int) -> bool:
    if alert.get("type") == "nowcast":
        return index == 0                       # nowcasts cover the next few hours
    if alert.get("date"):
        return alert["date"] == date            # IMD district warnings are per day
    shift = timedelta(seconds=offset_seconds)   # CAP alerts carry onset/expiry instants
    try:
        start = (datetime.fromisoformat(alert["onset"]) + shift).date().isoformat() if alert.get("onset") else None
        end = (datetime.fromisoformat(alert["expires"]) + shift).date().isoformat() if alert.get("expires") else None
    except ValueError:
        return False
    return (start is None or start <= date) and (end is None or date <= end) and (start or end) is not None


def apply_alerts(windows: list[dict], alerts: list[dict], offset_seconds: int = 0) -> None:
    for i, w in enumerate(windows):
        for a in alerts:
            if a.get("severity") not in ("red", "orange") or not _alert_applies(a, w["date"], i, offset_seconds):
                continue
            target = "poor" if a["severity"] == "red" else "caution"
            merged = worse_daily(w["suitability"], target)
            if merged != w["suitability"]:
                w["suitability"] = merged
                w["summary"] = f"Official {a['severity']} warning: {a.get('event') or a.get('headline')}. {BAND_COPY[merged]}"
            w["reasons"].append(f"official_warning:{a.get('source')}:{a['severity']}")
            w.setdefault("official_warnings", []).append({k: a.get(k) for k in ("id", "source", "severity", "event", "headline")})


def build_windows(forecast: Forecast, days: int, alerts: Optional[list[dict]] = None) -> tuple[list[dict], dict]:
    offset = forecast.utc_offset_seconds or 0
    cells = hourly_cells(forecast.hourly, offset)
    windows = []
    for i, day in enumerate(forecast.daily[:days]):
        band, reasons = daily_band(day)
        entry = {
            "date": day.date, "suitability": band, "summary": BAND_COPY[band], "best_window": None,
            "rain_probability": day.rain_probability, "rain_mm": day.precipitation_mm,
            "wind_kmh_max": day.wind_kmh_max, "high_c": day.high_c, "low_c": day.low_c,
            "condition": day.condition, "reasons": reasons,
        }
        day_cells = cells.get(day.date)
        if day_cells and i < 2:
            entry["hourly"] = {a: [{"hour": c["hour"], "suitability": c["suitability"]} for c in day_cells[a]]
                               for a in ACTIVITIES}
        entry["best_window"] = best_window(day_cells["field_work"]) if day_cells else (
            "Indoor / planning tasks" if band == "poor" else "Check the morning forecast")
        windows.append(entry)
    apply_alerts(windows, alerts or [], offset)
    return windows, cells


# --------------------------------------------------------------------------- #
# TypeSafe System One overlay


def build_state(crop: str, lat: float, lon: float, windows: list[dict], farm: dict, tz: str) -> str:
    def clean(v: Any) -> str:
        return " ".join(str(v).split())[:40] if v else ""

    lines = [f"Crop: {crop}. Location: {lat:.2f}, {lon:.2f} (India). Timezone: {tz}."]
    ctx = ", ".join(f"{k.replace('_', ' ')}: {clean(farm.get(k))}" for k in ("growth_stage", "soil", "irrigation")
                    if clean(farm.get(k)))
    if ctx:
        lines.append(f"Farm context: {ctx}.")
    lines.append("Daily forecast (rain chance is the daily maximum, wind the daily peak):")
    for i, w in enumerate(windows):
        def f(v, unit=""):
            return "unknown" if v is None else f"{v:.0f}{unit}"
        warn = "; ".join(o["event"] or "" for o in w.get("official_warnings", []))
        lines.append(f"{w['date']} (evidence_id=ev_{i}_{w['date']}): rain chance {f(w['rain_probability'], '%')}, "
                     f"rain {f(w['rain_mm'], ' mm')}, max wind {f(w['wind_kmh_max'], ' km/h')}, "
                     f"temperature {f(w['low_c'])}–{f(w['high_c'])} °C, sky {w.get('condition') or 'unknown'}"
                     + (f", OFFICIAL WARNING: {warn}" if warn else "") + ".")
    return "\n".join(lines)[:7000]


def build_questions(windows: list[dict], tz: str) -> dict[str, dict]:
    q: dict[str, dict] = {}
    for i, w in enumerate(windows):
        d = w["date"]
        scope = f"For date {d} only (timezone {tz}, evidence_id ev_{i}_{d})"
        q[f"d{i}_spray"] = {"type": "score", "criteria": SCORE_LEVELS, "instructions":
                            f"{scope}: how safe and effective is spraying pesticide or foliar fertilizer, "
                            "considering drift, rain wash-off and heat stress for this crop?"}
        q[f"d{i}_irrigation"] = {"type": "score", "criteria": SCORE_LEVELS, "instructions":
                                 f"{scope}: how suitable is irrigating this crop, considering rain that would "
                                 "waste water and wind/heat that increase evaporation?"}
        q[f"d{i}_fieldwork"] = {"type": "score", "criteria": SCORE_LEVELS, "instructions":
                                f"{scope}: how suitable is general field work considering rain, lightning, "
                                "wind and heat or cold stress for workers?"}
        q[f"d{i}_overall"] = {"type": "choice", "instructions":
                              f"{scope}: overall verdict for farm work. Choose the most conservative appropriate verdict.",
                              "criteria": {"good": "Safe and effective for spraying, irrigation and field work",
                                           "caution": "Workable with watch-outs such as wind, showers or heat",
                                           "avoid": "Unsafe or wasteful — keep heavy work off the field"}}
    return q


def _num(answers: dict, key: str, fld: str, low: float, high: float) -> Optional[float]:
    a = answers.get(key)
    if not isinstance(a, dict):
        return None
    try:
        v = float(a.get(fld))
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and low <= v <= high else None


def apply_overlay(windows: list[dict], answers: dict, *, min_confidence: float, model: Optional[str]) -> dict:
    """Merge System One answers; a verdict can only make a day more conservative."""
    meta: dict[str, Any] = {"enabled": True, "applied": False, "model": model, "evaluated_days": 0,
                            "mean_confidence": None, "overall_verdict": None, "per_day": {}}
    confidences, worst = [], None
    for i, w in enumerate(windows):
        entry: dict[str, Any] = {}
        for activity, key in (("spraying", "spray"), ("irrigation", "irrigation"), ("field_work", "fieldwork")):
            score = _num(answers, f"d{i}_{key}", "score", 0, 4)
            if score is None:
                continue
            conf = _num(answers, f"d{i}_{key}", "confidence", 0, 1)
            band = "avoid" if score < 1 else "caution" if score < 2 else "good"
            entry[key] = {"score": round(score, 2), "confidence": round(conf, 3) if conf is not None else None, "band": band}
            if conf is not None and conf >= min_confidence and band == "avoid" and "hourly" in w:
                for cell in w["hourly"].get(activity, []):
                    if cell["suitability"] != "avoid":
                        cell["suitability"] = "avoid"
                        meta["applied"] = True
        choice = (answers.get(f"d{i}_overall") or {}).get("choice") if isinstance(answers.get(f"d{i}_overall"), dict) else None
        conf = _num(answers, f"d{i}_overall", "confidence", 0, 1)
        if choice in VERDICT_TO_DAILY:
            entry["overall"] = {"choice": choice, "confidence": round(conf, 3) if conf is not None else None, "date": w["date"]}
            meta["evaluated_days"] += 1
            meta["per_day"][w["date"]] = entry["overall"]
            if conf is not None and conf >= min_confidence:
                confidences.append(conf)
                merged = worse_daily(w["suitability"], VERDICT_TO_DAILY[choice])
                if merged != w["suitability"]:
                    w["suitability"], w["summary"] = merged, BAND_COPY[merged]
                    meta["applied"] = True
            worst = choice if worst is None else ("avoid" if "avoid" in (worst, choice) else
                                                  "caution" if "caution" in (worst, choice) else "good")
        if entry:
            w["ai"] = entry
    meta["overall_verdict"] = worst  # aggregate for the 7-day overview only, never one day's verdict
    if confidences:
        meta["mean_confidence"] = round(sum(confidences) / len(confidences), 3)
    return meta


def summary_line(crop: str, windows: list[dict], place: str) -> str:
    good = sum(1 for w in windows if w["suitability"] == "good")
    poor = sum(1 for w in windows if w["suitability"] == "poor")
    text = f"{crop.title()} near {place}: {good} of {len(windows)} day(s) look good for field work"
    if poor:
        text += f", {poor} day(s) to avoid"
    return text + "."

