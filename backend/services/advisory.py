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
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

THUNDER_CODES = {95, 96, 99}
# Daily `suitability` keeps the router's historic vocabulary (good/caution/poor);
# hourly cells use good/caution/avoid. "avoid" and "poor" are equally severe.
BAND_ORDER = {"good": 0, "caution": 1, "poor": 2, "avoid": 2}
# Maps a System One verdict onto the daily vocabulary.
VERDICT_TO_DAILY_BAND = {"avoid": "poor", "caution": "caution", "good": "good"}
SCORE_LEVELS = ["Unsafe", "Risky", "Workable with care", "Good", "Ideal"]

# Copy shown to farmers, keyed by final daily band (kept identical in spirit to
# the router's original strings so clients see familiar wording).
BAND_COPY = {
    "good": ("Good day for field work.", "Best: 6–10 AM"),
    "caution": ("Workable with caution — watch wind and showers.", "Plan for afternoon gaps"),
    "poor": ("Conditions unsafe — avoid spraying and limit field work.", "Indoor / planning tasks"),
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
    """Return the more conservative of two bands."""
    return a if BAND_ORDER.get(a, 0) >= BAND_ORDER.get(b, 0) else b


def band_from_score(value: float) -> str:
    """Map a 0..4 TypeSafe score (Unsafe..Ideal) onto a suitability band."""
    if value < 1.0:
        return "avoid"
    if value < 2.0:
        return "caution"
    return "good"


def hour_band(activity: str, *, pop: float, rain_mm: float, wind_kmh: float,
              temp_c: float | None, code: int) -> str:
    """Deterministic band for one activity in one hour. Unknown values fail open."""
    rule = ACTIVITY_RULES[activity]
    if code in THUNDER_CODES and rule.thunder_is_avoid:
        return "avoid"
    if wind_kmh >= rule.avoid_wind or pop >= rule.avoid_pop or rain_mm >= rule.avoid_rain:
        return "avoid"
    if temp_c is not None and (temp_c >= rule.avoid_temp_hi or temp_c <= rule.avoid_temp_lo):
        return "avoid"
    if (wind_kmh >= rule.caution_wind or pop >= rule.caution_pop
            or rain_mm >= rule.caution_rain):
        return "caution"
    if temp_c is not None and (temp_c >= rule.caution_temp_hi or temp_c <= rule.caution_temp_lo):
        return "caution"
    return "good"


def _num(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number or number in (float("inf"), float("-inf")):
        return default
    return number


def _day_indices(hourly: dict[str, Any]) -> dict[str, list[int]]:
    """Group hourly-array positions by the date part of each ISO timestamp."""
    groups: dict[str, list[int]] = {}
    for index, stamp in enumerate(hourly.get("time") or []):
        groups.setdefault(str(stamp)[:10], []).append(index)
    return groups


def daily_stats(hourly: dict[str, Any], date: str) -> dict[str, Any] | None:
    """Aggregate one day's hourly block — the numeric sketch the model reads."""
    groups = _day_indices(hourly)
    indices = groups.get(date)
    if not indices:
        return None
    times = hourly.get("time") or []
    pops = [_num((hourly.get("precipitation_probability") or [None] * len(times))[i]) for i in indices]
    rains = [_num((hourly.get("precipitation") or [None] * len(times))[i]) for i in indices]
    winds = [_num((hourly.get("wind_speed_10m") or [None] * len(times))[i]) for i in indices]
    temps = [_num((hourly.get("temperature_2m") or [None] * len(times))[i]) for i in indices]
    codes = [(hourly.get("weather_code") or [0] * len(times))[i] for i in indices]
    try:
        int_codes = [int(c) for c in codes]
    except (TypeError, ValueError):
        int_codes = [0] * len(indices)
    return {
        "pop_max": max(pops),
        "rain_sum": round(sum(rains), 1),
        "wind_max": max(winds),
        "temp_min": round(min(temps), 1),
        "temp_max": round(max(temps), 1),
        "thunder_hours": sum(1 for c in int_codes if c in THUNDER_CODES),
    }


def build_hourly_by_date(hourly: dict[str, Any], dates: list[str],
                         activities: tuple[str, ...] = ("irrigation", "spraying", "field_work"),
                         hourly_days: int = 2) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Per-date, per-activity hourly bands for the first ``hourly_days`` dates.

    Returns ``{date: {activity: [{"hour": "HH:00", "suitability": band}, ...]}}``.
    """
    groups = _day_indices(hourly)
    times = hourly.get("time") or []
    pops = hourly.get("precipitation_probability") or []
    rains = hourly.get("precipitation") or []
    winds = hourly.get("wind_speed_10m") or []
    temps = hourly.get("temperature_2m") or []
    codes = hourly.get("weather_code") or []

    out: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for date in dates[:max(0, hourly_days)]:
        indices = groups.get(date)
        if not indices:
            continue
        per_activity: dict[str, list[dict[str, Any]]] = {}
        for activity in activities:
            cells: list[dict[str, Any]] = []
            for i in indices:
                code = codes[i] if i < len(codes) else 0
                try:
                    code_i = int(code)
                except (TypeError, ValueError):
                    code_i = 0
                temp = _num(temps[i]) if i < len(temps) else None
                if i >= len(temps) or temps[i] is None:
                    temp = None
                cells.append({
                    "hour": str(times[i])[11:16] if i < len(times) else "",
                    "suitability": hour_band(
                        activity,
                        pop=_num(pops[i] if i < len(pops) else 0),
                        rain_mm=_num(rains[i] if i < len(rains) else 0),
                        wind_kmh=_num(winds[i] if i < len(winds) else 0),
                        temp_c=temp,
                        code=code_i,
                    ),
                })
            per_activity[activity] = cells
        out[date] = per_activity
    return out


# --------------------------------------------------------------------------- #
# TypeSafe overlay — composite scoring across days, one batched call.
# --------------------------------------------------------------------------- #
def build_state(crop_label: str, lat: float, lon: float, dates: list[str],
                stats: list[dict[str, Any] | None],
                farm: dict[str, str] | None = None) -> str:
    """Compact text state: everything a field officer would need for a gut-check.

    ``farm`` may carry optional context keys (``growth_stage``, ``soil``,
    ``irrigation``) — the same judgment differs by growth stage, so richer
    state makes the scores materially smarter. Values are sanitized.
    """
    def _clean(value: Any) -> str:
        return " ".join(str(value).split())[:40] if value else ""

    lines = [f"Crop: {crop_label}. Location: {lat:.2f}, {lon:.2f} (India)."]
    if farm:
        context = ", ".join(
            f"{key.replace('_', ' ')}: {cleaned}"
            for key in ("growth_stage", "soil", "irrigation")
            for cleaned in [_clean(farm.get(key))] if cleaned
        )
        if context:
            lines.append(f"Farm context: {context}.")
    lines.append("Daily forecast summary (rain chance is the daily maximum, wind the daily peak):")
    for date, day in zip(dates, stats):
        if not day:
            continue
        lines.append(
            f"{date}: rain chance {day['pop_max']:.0f}%, rain total {day['rain_sum']} mm, "
            f"max wind {day['wind_max']:.0f} km/h, temperature {day['temp_min']}–{day['temp_max']} °C, "
            f"thunderstorm hours {day['thunder_hours']}."
        )
    return "\n".join(lines)


def build_questions(dates: list[str]) -> dict[str, dict[str, Any]]:
    """Speculative fan-out: one Score per day per activity + one daily verdict."""
    questions: dict[str, dict[str, Any]] = {}
    for index in range(len(dates)):
        questions[f"d{index}_spray"] = {
            "type": "score",
            "instructions": (
                "How safe and effective would it be to spray pesticides or foliar "
                "fertilizer on this day, considering spray drift, rain wash-off and "
                "heat stress for the given crop?"
            ),
            "criteria": SCORE_LEVELS,
        }
        questions[f"d{index}_irrigation"] = {
            "type": "score",
            "instructions": (
                "How suitable is this day for irrigating the given crop, considering "
                "rain that would waste water and wind/heat that increase evaporation?"
            ),
            "criteria": SCORE_LEVELS,
        }
        questions[f"d{index}_fieldwork"] = {
            "type": "score",
            "instructions": (
                "How suitable is this day for general field work (weeding, pruning, "
                "manual labour) for the given crop, considering rain, lightning, "
                "strong wind and heat or cold stress for workers?"
            ),
            "criteria": SCORE_LEVELS,
        }
        questions[f"d{index}_overall"] = {
            "type": "choice",
            "instructions": "Overall verdict for farm work on this day",
            "criteria": {
                "good": "Safe and effective for spraying, irrigation and field work",
                "caution": "Workable but with watch-outs such as wind, showers or heat",
                "avoid": "Unsafe or wasteful — keep heavy work off the field",
            },
        }
    return questions


def _answer(answers: dict[str, Any], key: str) -> dict[str, Any] | None:
    value = answers.get(key)
    return value if isinstance(value, dict) else None


def _num_field(answers: dict[str, Any], key: str, field: str) -> float | None:
    answer = _answer(answers, key)
    if not answer:
        return None
    try:
        return float(answer.get(field))
    except (TypeError, ValueError):
        return None


def apply_typesafe_overlay(
    windows: list[dict[str, Any]],
    hourly_by_date: dict[str, dict[str, list[dict[str, Any]]]],
    answers: dict[str, Any],
    *,
    min_confidence: float = 0.55,
    model: str | None = None,
) -> dict[str, Any]:
    """Merge System One answers into threshold-based ``windows`` (in place).

    Returns the top-level ``ai`` metadata block for the response payload.
    """
    meta: dict[str, Any] = {
        "enabled": True,
        "applied": False,
        "model": model,
        "evaluated_days": 0,
        "mean_confidence": None,
        "overall_verdict": None,
        "overall_confidence": None,
    }
    confidences: list[float] = []
    applied_any = False

    for index, window in enumerate(windows):
        entry: dict[str, Any] = {}

        # Per-activity scores: "Unsafe" floors the day's hourly cells for that activity.
        for activity, key in (("spraying", "spray"), ("irrigation", "irrigation"),
                              ("field_work", "fieldwork")):
            value = _num_field(answers, f"d{index}_{key}", "score")
            if value is None:
                continue
            confidence = _num_field(answers, f"d{index}_{key}", "confidence")
            band = band_from_score(value)
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
        if choice_value in BAND_ORDER:
            entry["overall"] = {
                "choice": choice_value,
                "confidence": round(choice_confidence, 3) if choice_confidence is not None else None,
            }
            meta["evaluated_days"] += 1
            if choice_confidence is not None and choice_confidence >= min_confidence:
                confidences.append(choice_confidence)
                if meta["overall_confidence"] is None or choice_confidence > (meta["overall_confidence"] or 0):
                    meta["overall_verdict"] = choice_value
                    meta["overall_confidence"] = round(choice_confidence, 3)
                previous = str(window.get("suitability", "good"))
                merged = worse(previous, VERDICT_TO_DAILY_BAND[choice_value])
                if merged != previous:
                    window["suitability"] = merged
                    window["summary"], window["best_window"] = BAND_COPY[merged]
                    applied_any = True

        if entry:
            window["ai"] = entry

    if confidences:
        meta["mean_confidence"] = round(sum(confidences) / len(confidences), 3)
    meta["applied"] = applied_any
    return meta
