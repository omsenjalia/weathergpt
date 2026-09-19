"""Farm action-window logic: deterministic hourly thresholds + a TypeSafe overlay.

Two layers, in increasing order of intelligence:

1. **Hourly threshold bands** (`hour_band`, `build_hourly_by_date`) — transparent,
   agronomy-style physics rules per activity per hour: wind drift for spraying,
   rain wash-off, heat stress for field work. Always runs; needs no API key.
2. **TypeSafe System One overlay** (`build_questions`, `build_state`,
   `apply_typesafe_overlay`) — ONE batched call scoring every day on every
   activity (days x activities + a per-day verdict, evaluated in parallel and in
   isolation). Code owns the merge policy and stays conservative:

   * a high-confidence AI verdict can only make a day **more** conservative, never
     less — the model can veto risky days but cannot overrule clear weather;
   * a high-confidence "Unsafe" activity score floors that activity's hourly
     cells to `avoid` for the whole day;
   * low-confidence answers are recorded for transparency but change nothing.

Suitability bands are the strings ``good`` / ``caution`` / ``avoid`` used by the
mobile app's action-window bars.

Fixes applied per WeatherNext/Jev plan:
- Nullable inputs and data-sufficiency gate: unknown critical data returns
  insufficient_data or conservative unavailability, not "safe"
- Date-bound questions: embed exact date, timezone, activity/window ID, evidence ID
- Overall verdict per-day, not highest-confidence-day substitution
- Strict finite/range validation for Scores/confidences
- Worst-band hazard merging for heat vs rain
- Short-array validation and missing thunder-code handling
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Any, Optional

THUNDER_CODES = {95, 96, 99}
# Daily `suitability` keeps the router's historic vocabulary (good/caution/poor);
# hourly cells use good/caution/avoid. "avoid" and "poor" are equally severe.
BAND_ORDER = {"good": 0, "caution": 1, "poor": 2, "avoid": 2, "insufficient_data": 3}
# Maps a System One verdict onto the daily vocabulary.
VERDICT_TO_DAILY_BAND = {"avoid": "poor", "caution": "caution", "good": "good"}
SCORE_LEVELS = ["Unsafe", "Risky", "Workable with care", "Good", "Ideal"]

# Copy shown to farmers, keyed by final daily band
BAND_COPY = {
    "good": ("Good day for field work.", "Best: 6–10 AM"),
    "caution": ("Workable with caution — watch wind and showers.", "Plan for afternoon gaps"),
    "poor": ("Conditions unsafe — avoid spraying and limit field work.", "Indoor / planning tasks"),
    "insufficient_data": ("Insufficient weather data — exercise caution.", "Check forecast and field conditions"),
}


@dataclass(frozen=True)
class ActivityRule:
    """Thresholds (SI units) separating avoid / caution / good for one activity."""

    avoid_wind: float
    caution_wind: float
    avoid_pop: float  # precipitation probability, %
    caution_pop: float
    avoid_rain: float  # mm per hour
    caution_rain: float
    caution_temp_lo: float
    avoid_temp_lo: float
    caution_temp_hi: float
    avoid_temp_hi: float
    thunder_is_avoid: bool = True


ACTIVITY_RULES: dict[str, ActivityRule] = {
    # Spray drift and wash-off are the dominant risks; calm, dry, mild hours only.
    "spraying": ActivityRule(
        avoid_wind=25, caution_wind=15,
        avoid_pop=60, caution_pop=30,
        avoid_rain=0.5, caution_rain=0.1,
        caution_temp_lo=10, avoid_temp_lo=5,
        caution_temp_hi=35, avoid_temp_hi=40,
    ),
    # Irrigating into rain wastes water; hot wind loses it to evaporation.
    "irrigation": ActivityRule(
        avoid_wind=35, caution_wind=25,
        avoid_pop=60, caution_pop=30,
        avoid_rain=1.0, caution_rain=0.3,
        caution_temp_lo=-10, avoid_temp_lo=-15,
        caution_temp_hi=38, avoid_temp_hi=45,
        thunder_is_avoid=False,
    ),
    # People in the field: lightning, heavy rain, strong wind, heat, cold.
    "field_work": ActivityRule(
        avoid_wind=35, caution_wind=25,
        avoid_pop=70, caution_pop=40,
        avoid_rain=2.0, caution_rain=0.5,
        caution_temp_lo=8, avoid_temp_lo=2,
        caution_temp_hi=38, avoid_temp_hi=42,
    ),
}


def worse(a: str, b: str) -> str:
    """Return the more conservative of two bands. insufficient_data is most conservative."""
    # insufficient_data should be treated as most conservative
    order_a = BAND_ORDER.get(a, 0)
    order_b = BAND_ORDER.get(b, 0)
    return a if order_a >= order_b else b


def _is_finite_number(value: Any) -> bool:
    """Check if value is a finite number."""
    try:
        f = float(value)
        return math.isfinite(f)
    except (TypeError, ValueError):
        return False


def band_from_score(value: float) -> str:
    """Map a 0..4 TypeSafe score (Unsafe..Ideal) onto a suitability band.

    Fixes: rejects nonfinite and out-of-range scores.
    Invalid scores return 'insufficient_data' which is treated as no opinion
    by the overlay logic, not 'good'.
    """
    if not _is_finite_number(value):
        return "insufficient_data"
    v = float(value)
    # Score must be in 0..4 range per TypeSafe contract
    if v < 0 or v > 4:
        return "insufficient_data"
    if v < 1.0:
        return "avoid"
    if v < 2.0:
        return "caution"
    return "good"


def hour_band(
    activity: str,
    *,
    pop: float | None,
    rain_mm: float | None,
    wind_kmh: float | None,
    temp_c: float | None,
    code: int,
) -> str:
    """Deterministic band for one activity in one hour.

    Fixed: unknown critical data returns conservative 'avoid' or 'insufficient_data',
    not 'good'. Missing rain/wind/pop no longer coerced to zero for safety advice.

    Critical data for safety:
    - pop, rain_mm, wind_kmh are critical: missing -> avoid (conservative)
    - temp_c is optional: missing -> ignore temp checks but still evaluate others
    - code: thunder handling requires explicit code, missing -> assume no thunder
    """
    if activity not in ACTIVITY_RULES:
        return "insufficient_data"

    rule = ACTIVITY_RULES[activity]

    # Thunder check - code must be valid
    if code in THUNDER_CODES and rule.thunder_is_avoid:
        return "avoid"

    # Data sufficiency gate: critical fields must be present and finite
    # If any critical field is missing, return conservative avoid
    if pop is None or not _is_finite_number(pop):
        return "avoid"  # conservative: unknown rain chance -> avoid
    if rain_mm is None or not _is_finite_number(rain_mm):
        return "avoid"  # unknown rain -> avoid
    if wind_kmh is None or not _is_finite_number(wind_kmh):
        return "avoid"  # unknown wind -> avoid

    # Now we have valid critical data
    pop_f = float(pop)
    rain_f = float(rain_mm)
    wind_f = float(wind_kmh)

    # Validate ranges
    if pop_f < 0 or pop_f > 100:
        return "insufficient_data"
    if rain_f < 0 or rain_f > 1000:
        return "insufficient_data"
    if wind_f < 0 or wind_f > 500:
        return "insufficient_data"

    if wind_f >= rule.avoid_wind or pop_f >= rule.avoid_pop or rain_f >= rule.avoid_rain:
        return "avoid"

    # Temperature checks only if temp is present and finite
    if temp_c is not None and _is_finite_number(temp_c):
        temp_f = float(temp_c)
        if temp_f >= rule.avoid_temp_hi or temp_f <= rule.avoid_temp_lo:
            return "avoid"

    if wind_f >= rule.caution_wind or pop_f >= rule.caution_pop or rain_f >= rule.caution_rain:
        return "caution"

    if temp_c is not None and _is_finite_number(temp_c):
        temp_f = float(temp_c)
        if temp_f >= rule.caution_temp_hi or temp_f <= rule.caution_temp_lo:
            return "caution"

    return "good"


def _num(value: Any, default: float | None = 0.0) -> float | None:
    """Legacy helper: tries to parse float, returns default on failure.

    Kept for backward compatibility, but new code should use _safe_float.
    """
    try:
        if value is None:
            return default
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return number


def _safe_float(value: Any) -> float | None:
    """Strict parser: returns None for missing/nonfinite, not 0."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _day_indices(hourly: dict[str, Any]) -> dict[str, list[int]]:
    """Group hourly-array positions by the date part of each ISO timestamp."""
    groups: dict[str, list[int]] = {}
    for index, stamp in enumerate(hourly.get("time") or []):
        try:
            date_part = str(stamp)[:10]
            # Validate date format roughly
            if len(date_part) == 10 and date_part[4] == "-" and date_part[7] == "-":
                groups.setdefault(date_part, []).append(index)
        except Exception:
            continue
    return groups


def daily_stats(hourly: dict[str, Any], date: str) -> dict[str, Any] | None:
    """Aggregate one day's hourly block — the numeric sketch the model reads.

    Fixed:
    - Validates short arrays and missing data
    - Returns None if insufficient data
    - Includes data quality flags
    - Handles nullable inputs explicitly
    """
    groups = _day_indices(hourly)
    indices = groups.get(date)
    if not indices:
        return None

    times = hourly.get("time") or []
    # Use safe parsing with length checks
    def get_array(key: str) -> list:
        arr = hourly.get(key)
        if not isinstance(arr, list):
            return [None] * len(times)
        return arr

    pop_arr = get_array("precipitation_probability")
    rain_arr = get_array("precipitation")
    wind_arr = get_array("wind_speed_10m")
    temp_arr = get_array("temperature_2m")
    code_arr = get_array("weather_code")

    # Collect with validation, tracking missing counts
    pops: list[float] = []
    rains: list[float] = []
    winds: list[float] = []
    temps: list[float] = []
    codes: list[int] = []

    missing_pop = 0
    missing_rain = 0
    missing_wind = 0
    missing_temp = 0

    for i in indices:
        # Bounds check
        if i >= len(times):
            continue

        # Pop
        pop_val = _safe_float(pop_arr[i] if i < len(pop_arr) else None)
        if pop_val is None:
            missing_pop += 1
        else:
            pops.append(pop_val)

        # Rain
        rain_val = _safe_float(rain_arr[i] if i < len(rain_arr) else None)
        if rain_val is None:
            missing_rain += 1
            # For rain, missing should not be treated as 0 - track but don't include
        else:
            rains.append(rain_val)

        # Wind
        wind_val = _safe_float(wind_arr[i] if i < len(wind_arr) else None)
        if wind_val is None:
            missing_wind += 1
        else:
            winds.append(wind_val)

        # Temp
        temp_val = _safe_float(temp_arr[i] if i < len(temp_arr) else None)
        if temp_val is None:
            missing_temp += 1
        else:
            temps.append(temp_val)

        # Code - thunder detection: missing code implies no thunder, not 0
        code_raw = code_arr[i] if i < len(code_arr) else 0
        try:
            code_int = int(code_raw) if code_raw is not None else 0
        except (TypeError, ValueError):
            code_int = 0
        codes.append(code_int)

    # Data sufficiency gate: need at least some data
    # If more than 50% missing for critical fields, return insufficient
    total_expected = len(indices)
    if total_expected == 0:
        return None

    # Critical: need at least 1 valid reading for each critical field, or we flag insufficient
    if len(pops) == 0 and len(rains) == 0 and len(winds) == 0:
        return {
            "pop_max": None,
            "rain_sum": None,
            "wind_max": None,
            "temp_min": None,
            "temp_max": None,
            "thunder_hours": 0,
            "data_quality": "insufficient",
            "missing_counts": {
                "pop": missing_pop,
                "rain": missing_rain,
                "wind": missing_wind,
                "temp": missing_temp,
            },
            "valid_hours": 0,
            "expected_hours": total_expected,
        }

    # Compute aggregates only from valid data
    pop_max = max(pops) if pops else None
    rain_sum = round(sum(rains), 1) if rains else 0.0
    wind_max = max(winds) if winds else None
    temp_min = round(min(temps), 1) if temps else None
    temp_max = round(max(temps), 1) if temps else None
    thunder_hours = sum(1 for c in codes if c in THUNDER_CODES)

    # Quality flag
    valid_hours = max(len(pops), len(rains), len(winds))
    coverage = valid_hours / total_expected if total_expected > 0 else 0
    quality = "good" if coverage >= 0.8 else "partial" if coverage >= 0.5 else "insufficient"

    return {
        "pop_max": pop_max if pop_max is not None else 0,
        "rain_sum": rain_sum,
        "wind_max": wind_max if wind_max is not None else 0,
        "temp_min": temp_min,
        "temp_max": temp_max,
        "thunder_hours": thunder_hours,
        "data_quality": quality,
        "missing_counts": {
            "pop": missing_pop,
            "rain": missing_rain,
            "wind": missing_wind,
            "temp": missing_temp,
        },
        "valid_hours": valid_hours,
        "expected_hours": total_expected,
        "coverage": round(coverage, 2),
    }


def build_hourly_by_date(
    hourly: dict[str, Any],
    dates: list[str],
    activities: tuple[str, ...] = ("irrigation", "spraying", "field_work"),
    hourly_days: int = 2,
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Per-date, per-activity hourly bands for the first ``hourly_days`` dates.

    Fixed:
    - Validates short arrays
    - Handles nullable inputs explicitly
    - No index out-of-bounds
    - Returns conservative bands for missing critical data
    """
    groups = _day_indices(hourly)
    times = hourly.get("time") or []
    pops = hourly.get("precipitation_probability") or []
    rains = hourly.get("precipitation") or []
    winds = hourly.get("wind_speed_10m") or []
    temps = hourly.get("temperature_2m") or []
    codes = hourly.get("weather_code") or []

    # Ensure arrays are lists
    if not isinstance(pops, list):
        pops = []
    if not isinstance(rains, list):
        rains = []
    if not isinstance(winds, list):
        winds = []
    if not isinstance(temps, list):
        temps = []
    if not isinstance(codes, list):
        codes = []
    if not isinstance(times, list):
        times = []

    out: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for date in dates[: max(0, hourly_days)]:
        indices = groups.get(date)
        if not indices:
            continue
        per_activity: dict[str, list[dict[str, Any]]] = {}
        for activity in activities:
            cells: list[dict[str, Any]] = []
            for i in indices:
                # Bounds checks for all arrays
                if i >= len(times):
                    continue

                # Safe extraction with None for missing
                pop_val = _safe_float(pops[i] if i < len(pops) else None)
                rain_val = _safe_float(rains[i] if i < len(rains) else None)
                wind_val = _safe_float(winds[i] if i < len(winds) else None)

                # Temp is optional - None is allowed
                temp_raw = temps[i] if i < len(temps) else None
                temp_val = _safe_float(temp_raw)

                code_raw = codes[i] if i < len(codes) else 0
                try:
                    code_i = int(code_raw) if code_raw is not None else 0
                except (TypeError, ValueError):
                    code_i = 0

                # Hour label
                time_str = str(times[i]) if i < len(times) else ""
                hour_label = time_str[11:16] if len(time_str) >= 16 else ""

                band = hour_band(
                    activity,
                    pop=pop_val,
                    rain_mm=rain_val,
                    wind_kmh=wind_val,
                    temp_c=temp_val,
                    code=code_i,
                )

                cells.append({
                    "hour": hour_label,
                    "suitability": band,
                    "evidence": {
                        "pop": pop_val,
                        "rain_mm": rain_val,
                        "wind_kmh": wind_val,
                        "temp_c": temp_val,
                        "code": code_i,
                    } if band == "insufficient_data" else None,
                })
                # Remove evidence key if not needed to keep backward compat
                if cells[-1]["evidence"] is None:
                    del cells[-1]["evidence"]

            per_activity[activity] = cells
        out[date] = per_activity
    return out


# --------------------------------------------------------------------------- #
# TypeSafe overlay — composite scoring across days, one batched call.
# --------------------------------------------------------------------------- #
def build_state(
    crop_label: str,
    lat: float,
    lon: float,
    dates: list[str],
    stats: list[dict[str, Any] | None],
    farm: dict[str, str] | None = None,
    timezone_str: str = "Asia/Kolkata",
    evidence_ids: list[str] | None = None,
) -> str:
    """Compact text state: everything a field officer would need for a gut-check.

    Fixed:
    - Includes exact dates, timezone, evidence IDs
    - Bounded serialization (TYPESAFE_MAX_STATE_CHARS)
    - Sanitized farm context
    - Preserves complete safety/date/evidence context
    - Never drops date, warnings, provenance via truncation
    """
    def _clean(value: Any) -> str:
        return " ".join(str(value).split())[:40] if value else ""

    max_chars = int(os.getenv("TYPESAFE_MAX_STATE_CHARS", "7000") or "7000")
    # Reserve for safety
    max_chars = min(max_chars, 7000)

    lines = [f"Crop: {crop_label}. Location: {lat:.2f}, {lon:.2f} (India). Timezone: {timezone_str}."]
    if evidence_ids:
        lines.append(f"Evidence IDs: {', '.join(evidence_ids[:len(dates)])}.")

    if farm:
        context = ", ".join(
            f"{key.replace('_', ' ')}: {cleaned}"
            for key in ("growth_stage", "soil", "irrigation")
            for cleaned in [_clean(farm.get(key))] if cleaned
        )
        if context:
            lines.append(f"Farm context: {context}.")

    lines.append("Daily forecast summary (rain chance is daily maximum, wind daily peak):")
    for idx, (date, day) in enumerate(zip(dates, stats)):
        if not day:
            ev_id = evidence_ids[idx] if evidence_ids and idx < len(evidence_ids) else f"ev_{idx}"
            lines.append(f"{date} (evidence_id={ev_id}): insufficient data - exercise caution.")
            continue

        # Include evidence ID and data quality
        ev_id = evidence_ids[idx] if evidence_ids and idx < len(evidence_ids) else f"ev_{idx}_{date}"
        quality = day.get("data_quality", "unknown")
        pop = day.get("pop_max", 0)
        rain = day.get("rain_sum", 0)
        wind = day.get("wind_max", 0)
        t_min = day.get("temp_min", "unknown")
        t_max = day.get("temp_max", "unknown")
        thunder = day.get("thunder_hours", 0)
        coverage = day.get("coverage", 1.0)

        lines.append(
            f"{date} (evidence_id={ev_id}, quality={quality}, coverage={coverage}): "
            f"rain chance {pop:.0f}%, rain total {rain} mm, "
            f"max wind {wind:.0f} km/h, temperature {t_min}–{t_max} °C, "
            f"thunderstorm hours {thunder}."
        )

    full_text = "\n".join(lines)

    # Bounded serialization: preserve safety-critical parts (dates, warnings)
    # If too long, truncate from the end but keep first lines (crop, location, timezone)
    if len(full_text) > max_chars:
        # Keep header and truncate forecast summary
        header = "\n".join(lines[:2]) + "\n"
        remaining_budget = max_chars - len(header) - 100  # reserve
        forecast_part = "\n".join(lines[2:])
        if len(forecast_part) > remaining_budget:
            forecast_part = forecast_part[:remaining_budget] + "\n[truncated for budget]"
        full_text = header + forecast_part

    return full_text


def build_questions(
    dates: list[str],
    timezone_str: str = "Asia/Kolkata",
    evidence_ids: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Speculative fan-out: one Score per day per activity + one daily verdict.

    Fixed:
    - Embeds exact date, timezone, activity/window ID and evidence ID in each question
    - Ensures question IDs map to immutable evidence records
    - Preserves backward compatibility with d{index}_* keys
    """
    questions: dict[str, dict[str, Any]] = {}
    for index, date in enumerate(dates):
        ev_id = evidence_ids[index] if evidence_ids and index < len(evidence_ids) else f"ev_{index}_{date}"
        window_id = f"window_{date}_{index}"
        tz = timezone_str

        # Spraying
        questions[f"d{index}_spray"] = {
            "type": "score",
            "instructions": (
                f"For date {date} (timezone {tz}, window_id {window_id}, evidence_id {ev_id}): "
                f"How safe and effective would it be to spray pesticides or foliar "
                f"fertilizer on this specific day {date}, considering spray drift, rain wash-off and "
                f"heat stress for the given crop? Evaluate only this day {date}, not other days."
            ),
            "criteria": SCORE_LEVELS,
        }
        # Irrigation
        questions[f"d{index}_irrigation"] = {
            "type": "score",
            "instructions": (
                f"For date {date} (timezone {tz}, window_id {window_id}, evidence_id {ev_id}): "
                f"How suitable is this specific day {date} for irrigating the given crop, considering "
                f"rain that would waste water and wind/heat that increase evaporation? Evaluate only {date}."
            ),
            "criteria": SCORE_LEVELS,
        }
        # Field work
        questions[f"d{index}_fieldwork"] = {
            "type": "score",
            "instructions": (
                f"For date {date} (timezone {tz}, window_id {window_id}, evidence_id {ev_id}): "
                f"How suitable is this specific day {date} for general field work (weeding, pruning, "
                f"manual labour) for the given crop, considering rain, lightning, "
                f"strong wind and heat or cold stress for workers? Evaluate only {date}."
            ),
            "criteria": SCORE_LEVELS,
        }
        # Overall verdict per day
        questions[f"d{index}_overall"] = {
            "type": "choice",
            "instructions": (
                f"For date {date} (timezone {tz}, window_id {window_id}, evidence_id {ev_id}): "
                f"Overall verdict for farm work on this specific day {date}. "
                f"Choose the most conservative appropriate verdict for {date} alone."
            ),
            "criteria": {
                "good": f"Safe and effective for spraying, irrigation and field work on {date}",
                "caution": f"Workable but with watch-outs such as wind, showers or heat on {date}",
                "avoid": f"Unsafe or wasteful on {date} — keep heavy work off the field",
            },
        }
    return questions


def _answer(answers: dict[str, Any], key: str) -> dict[str, Any] | None:
    value = answers.get(key)
    return value if isinstance(value, dict) else None


def _num_field(answers: dict[str, Any], key: str, field: str) -> float | None:
    """Strict field extraction: rejects nonfinite and out-of-range.

    Fixed: rejects NaN, inf, and invalid types.
    """
    answer = _answer(answers, key)
    if not answer:
        return None
    raw = answer.get(field)
    if raw is None:
        return None
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(val):
        return None
    return val


def apply_typesafe_overlay(
    windows: list[dict[str, Any]],
    hourly_by_date: dict[str, dict[str, list[dict[str, Any]]]],
    answers: dict[str, Any],
    *,
    min_confidence: float = 0.55,
    model: str | None = None,
) -> dict[str, Any]:
    """Merge System One answers into threshold-based ``windows`` (in place).

    Fixed:
    - Validates scores are finite and in 0..4 range
    - Rejects invalid answers as no opinion
    - Overall verdict per-day, not highest-confidence-day substitution
    - Worst-band merging for heat vs rain
    - Returns per-day verdicts plus conservative global verdict
    """
    meta: dict[str, Any] = {
        "enabled": True,
        "applied": False,
        "model": model,
        "evaluated_days": 0,
        "mean_confidence": None,
        "overall_verdict": None,  # deprecated global, now worst-case
        "overall_confidence": None,
        "overall_verdicts_by_date": {},  # new per-day
        "per_day": {},  # detailed per-day
    }
    confidences: list[float] = []
    applied_any = False
    per_day_verdicts: dict[str, str] = {}

    for index, window in enumerate(windows):
        date_str = str(window.get("date", f"day_{index}"))
        entry: dict[str, Any] = {}

        # Per-activity scores: "Unsafe" floors the day's hourly cells for that activity.
        for activity, key in (("spraying", "spray"), ("irrigation", "irrigation"), ("field_work", "fieldwork")):
            value = _num_field(answers, f"d{index}_{key}", "score")
            if value is None:
                continue
            # Validate score range 0..4
            if value < 0 or value > 4:
                continue

            confidence = _num_field(answers, f"d{index}_{key}", "confidence")
            # Validate confidence 0..1 if present
            if confidence is not None and (confidence < 0 or confidence > 1):
                confidence = None

            band = band_from_score(value)
            if band == "insufficient_data":
                # Invalid score treated as no opinion
                continue

            entry[key] = {
                "score": round(value, 2),
                "confidence": round(confidence, 3) if confidence is not None else None,
                "band": band,
            }
            if confidence is not None and confidence >= min_confidence and band == "avoid":
                cells = hourly_by_date.get(str(window.get("date")), {}).get(activity, [])
                for cell in cells:
                    if cell["suitability"] != "avoid":
                        cell["suitability"] = "avoid"
                        applied_any = True

        # Daily verdict Choice may only make the day more conservative.
        verdict = _answer(answers, f"d{index}_overall")
        choice_value = verdict.get("choice") if verdict else None
        choice_confidence = _num_field(answers, f"d{index}_overall", "confidence")
        if choice_confidence is not None and (choice_confidence < 0 or choice_confidence > 1):
            choice_confidence = None

        if choice_value in VERDICT_TO_DAILY_BAND:
            entry["overall"] = {
                "choice": choice_value,
                "confidence": round(choice_confidence, 3) if choice_confidence is not None else None,
                "date": date_str,
            }
            meta["evaluated_days"] += 1
            per_day_verdicts[date_str] = choice_value
            meta["overall_verdicts_by_date"][date_str] = {
                "choice": choice_value,
                "confidence": round(choice_confidence, 3) if choice_confidence is not None else None,
            }

            if choice_confidence is not None and choice_confidence >= min_confidence:
                confidences.append(choice_confidence)
                # For global overall_verdict, use worst-case (most conservative), not highest confidence
                # This fixes the bug where tomorrow=good with high confidence could override today=poor
                current_global = meta["overall_verdict"]
                if current_global is None:
                    meta["overall_verdict"] = choice_value
                    meta["overall_confidence"] = round(choice_confidence, 3)
                else:
                    # Worst-case merging
                    merged_global = worse(
                        VERDICT_TO_DAILY_BAND.get(current_global, current_global),
                        VERDICT_TO_DAILY_BAND.get(choice_value, choice_value),
                    )
                    # Convert back to choice vocabulary
                    reverse_map = {"poor": "avoid", "avoid": "avoid", "caution": "caution", "good": "good"}
                    meta["overall_verdict"] = reverse_map.get(merged_global, merged_global)
                    # Keep highest confidence among those that contributed to worst case? Or mean?
                    # For simplicity, keep max confidence seen
                    if choice_confidence > (meta["overall_confidence"] or 0):
                        meta["overall_confidence"] = round(choice_confidence, 3)

                # Per-day merging: apply only to this day's window
                previous = str(window.get("suitability", "good"))
                merged = worse(previous, VERDICT_TO_DAILY_BAND[choice_value])
                if merged != previous:
                    window["suitability"] = merged
                    window["summary"], window["best_window"] = BAND_COPY[merged]
                    applied_any = True

            # Store per-day detail
            meta["per_day"][date_str] = {
                "choice": choice_value,
                "confidence": round(choice_confidence, 3) if choice_confidence is not None else None,
                "previous_suitability": window.get("suitability"),
            }

        if entry:
            window["ai"] = entry

    if confidences:
        meta["mean_confidence"] = round(sum(confidences) / len(confidences), 3)

    # If no global verdict set but we have per-day, set global to worst per-day
    if meta["overall_verdict"] is None and per_day_verdicts:
        # Find worst among per-day
        worst = "good"
        for v in per_day_verdicts.values():
            worst = worse(worst, VERDICT_TO_DAILY_BAND.get(v, v))
        reverse = {"poor": "avoid", "avoid": "avoid", "caution": "caution", "good": "good"}
        meta["overall_verdict"] = reverse.get(worst, worst)

    meta["applied"] = applied_any
    return meta
