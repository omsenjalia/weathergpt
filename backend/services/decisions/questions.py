"""Versioned Choice/Score/Noul templates with date/window/evidence IDs.

Templates are reviewed independently of transport.
"""

from __future__ import annotations

from typing import Any

from services.decisions.models import DecisionFeatureSpec


def build_question_for_feature(
    spec: DecisionFeatureSpec,
    context: dict,
) -> dict[str, Any]:
    """Build a single Jev question from spec and context.

    Context must include date, timezone, window_id, evidence_id, etc.
    """
    date = context.get("date", "unknown_date")
    tz = context.get("timezone", "Asia/Kolkata")
    window_id = context.get("window_id", f"window_{date}")
    evidence_id = context.get("evidence_id", f"ev_{date}")
    activity = context.get("activity_id", spec.feature_id)
    crop = context.get("crop", "crops")

    base_instruction = f"For date {date} (timezone {tz}, window_id {window_id}, evidence_id {evidence_id}, activity {activity}, crop {crop}): "

    if spec.primitive.value == "choice":
        # Build choice with criteria
        criteria = {}
        for choice in spec.allowed_choices:
            criteria[choice] = f"{choice} for {date} (evidence {evidence_id})"
        # Use spec's allowed_choices if it already has descriptive criteria
        # For backward compat, if spec has detailed criteria in description, use that
        if spec.feature_id.startswith("farm.") or spec.feature_id.startswith("route."):
            # Use the spec's own allowed choices as criteria keys with descriptive values
            # Already handled
            pass

        return {
            "type": "choice",
            "instructions": base_instruction + spec.description,
            "criteria": {k: f"{k} - {spec.description} for {date}" for k in spec.allowed_choices} if spec.allowed_choices else {spec.feature_id: spec.description},
        }

    elif spec.primitive.value == "score":
        return {
            "type": "score",
            "instructions": base_instruction + spec.description,
            "criteria": spec.ordered_score_criteria or ["Unsafe", "Risky", "Workable with care", "Good", "Ideal"],
        }

    elif spec.primitive.value == "noul":
        return {
            "type": "noul",
            "instructions": base_instruction + (spec.noul_proposition or spec.description),
        }

    else:
        return {
            "type": "choice",
            "instructions": base_instruction + spec.description,
            "criteria": {"unknown": "Unknown"},
        }


def build_batch_questions(
    specs: list[DecisionFeatureSpec],
    contexts: list[dict],
) -> dict[str, dict[str, Any]]:
    """Build batch of questions with explicit bindings.

    Each question ID maps to immutable evidence record.
    """
    questions: dict[str, dict[str, Any]] = {}
    for spec, ctx in zip(specs, contexts):
        qid = ctx.get("question_id") or f"{spec.feature_id}_{ctx.get('date', 'unknown')}"
        # Ensure qid is stable and maps to evidence
        questions[qid] = build_question_for_feature(spec, ctx)
    return questions


# Versioned templates for farm activities (migrated from advisory)
FARM_QUESTION_TEMPLATES_V2 = {
    "spray": {
        "version": "2.0",
        "type": "score",
        "template": "For date {date} (timezone {timezone}, window_id {window_id}, evidence_id {evidence_id}, crop {crop}): How safe and effective would it be to spray pesticides or foliar fertilizer on this specific day {date}, considering spray drift (wind {wind_max} km/h), rain wash-off (rain {rain_sum} mm, pop {pop_max}%), heat stress (temp {temp_max} C), and official warning status {warning_status}? Evaluate only this day {date}, not other days. Evidence quality: {evidence_quality}.",
        "criteria": ["Unsafe", "Risky", "Workable with care", "Good", "Ideal"],
    },
    "irrigation": {
        "version": "2.0",
        "type": "score",
        "template": "For date {date} (timezone {timezone}, window_id {window_id}, evidence_id {evidence_id}, crop {crop}, stage {growth_stage}): How suitable is this specific day {date} for irrigating, considering rain that would waste water (rain {rain_sum} mm), wind/heat that increase evaporation (wind {wind_max} km/h, temp {temp_max} C), soil {soil}, irrigation {irrigation}? Evaluate only {date}.",
        "criteria": ["Unsafe", "Risky", "Workable with care", "Good", "Ideal"],
    },
    "field_work": {
        "version": "2.0",
        "type": "score",
        "template": "For date {date} (timezone {timezone}, window_id {window_id}, evidence_id {evidence_id}): How suitable is this specific day {date} for general field work, considering rain {rain_sum} mm, lightning {thunder_hours}h, wind {wind_max} km/h, heat {temp_max} C, cold {temp_min} C, warnings {warning_status}? Evaluate only {date}.",
        "criteria": ["Unsafe", "Risky", "Workable with care", "Good", "Ideal"],
    },
    "overall": {
        "version": "2.0",
        "type": "choice",
        "template": "For date {date} (timezone {timezone}, window_id {window_id}, evidence_id {evidence_id}): Overall verdict for farm work on this specific day {date}. Choose most conservative appropriate verdict for {date} alone. Evidence quality {evidence_quality}, coverage {coverage}.",
        "criteria": {
            "good": "Safe and effective for spraying, irrigation and field work on {date}",
            "caution": "Workable but with watch-outs such as wind, showers or heat on {date}",
            "avoid": "Unsafe or wasteful on {date} — keep heavy work off the field",
        },
    },
}
