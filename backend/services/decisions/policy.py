"""Candidate constraints, eligibility, warning floors, confidence gates, abstention.

Implements safety monotonicity:
- Jev cannot clear hard exclusion, downgrade official warning, turn unknown into safe,
  or alter IMD-first order
- Low confidence produces no opinion
"""

from __future__ import annotations

import math
from typing import Any, Optional

from services.decisions.models import DecisionFeatureSpec, DecisionContextV2, DecisionResultV2, DecisionStatus
from services.forecast_models import ProviderName


def check_eligibility(
    context: DecisionContextV2,
    spec: DecisionFeatureSpec,
) -> tuple[bool, Optional[str]]:
    """Check if context is eligible for feature.

    Returns (eligible, reason_if_not).
    """
    # Check data sufficiency
    sufficient, reason = context.is_data_sufficient()
    if not sufficient:
        return False, reason

    # Check required evidence
    for req in spec.required_evidence:
        # Simplified check - in real implementation would check actual evidence dict
        if req == "soil_moisture" and not context.farm_context.get("soil_moisture_measured"):
            if spec.feature_id in ("farm.irrigation_timing", "farm.sowing_transplanting"):
                return False, f"missing_required_{req}"

    # Check official warning floors
    if context.official_warning_status in ("red", "orange"):
        # For safety-critical farm activities, official warnings are hard floors
        if spec.feature_id in ("farm.spray_windows", "farm.field_work", "farm.harvest_windows"):
            # Don't block eligibility, but final verdict must respect warning
            pass

    # Check source constraints
    if spec.source_constraints:
        # e.g., requires weathernext_ensemble
        if "weathernext_ensemble" in spec.source_constraints and context.requested_source != "weathernext":
            # Check if we actually have ensemble data
            if context.expected_member_count is None or context.expected_member_count < 10:
                return False, "requires_ensemble_data"

    return True, None


def apply_warning_floor(
    deterministic_verdict: str,
    official_warning_status: str,
) -> str:
    """Apply official warning floor: warnings cannot be downgraded by model.

    Official warnings are authoritative; model-derived hazard guidance is separate.
    """
    if official_warning_status in ("red", "orange"):
        # If official warning is red/orange, final cannot be good
        if deterministic_verdict == "good":
            return "poor"  # or caution depending on warning type
        if deterministic_verdict == "caution" and official_warning_status == "red":
            return "poor"
    return deterministic_verdict


def apply_conservative_merge(
    deterministic_verdict: str,
    model_verdict: Optional[str],
    model_confidence: Optional[float],
    min_confidence: float,
    spec: DecisionFeatureSpec,
) -> tuple[str, bool]:
    """Conservative merge: model can only make more conservative, never less.

    Returns (final_verdict, was_model_applied).
    """
    if not model_verdict:
        return deterministic_verdict, False

    if model_confidence is None or model_confidence < min_confidence:
        return deterministic_verdict, False

    # Validate model verdict is in allowed choices
    if spec.allowed_choices and model_verdict not in spec.allowed_choices:
        # Map score bands to verdicts if needed
        band_order = {"good": 0, "caution": 1, "poor": 2, "avoid": 2}
        # If model_verdict is a band, check if more conservative
        det_order = band_order.get(deterministic_verdict, 0)
        model_order = band_order.get(model_verdict, 0)
        if model_order > det_order:
            return model_verdict, True
        else:
            return deterministic_verdict, False

    # For choice features, check if model choice is more conservative
    # This is feature-specific; for farm activities, avoid > caution > good
    conservative_order = {"good": 0, "caution": 1, "avoid": 2, "poor": 2}

    det_order = conservative_order.get(deterministic_verdict, 0)
    model_order = conservative_order.get(model_verdict, 0)

    if model_order > det_order:
        # Model is more conservative, allow it
        return model_verdict, True
    else:
        # Model is less conservative or equal, keep deterministic
        # This prevents model from clearing hard exclusions
        return deterministic_verdict, False


def check_safety_monotonicity(
    result: DecisionResultV2,
    context: DecisionContextV2,
) -> tuple[bool, Optional[str]]:
    """Check safety invariants - zero allowed violations in release.

    - Jev cannot clear hard exclusion
    - Cannot downgrade official warning
    - Cannot turn unknown into safe
    - Cannot alter IMD-first order
    """
    # Check hard exclusions
    if result.deterministic_verdict in ("avoid", "poor") and result.final_verdict == "good":
        return False, "model_cleared_hard_exclusion"

    # Check official warning downgrade
    if context.official_warning_status in ("red", "orange") and result.final_verdict == "good":
        if result.deterministic_verdict != "good":
            # Deterministic already flagged warning, model says good -> violation
            return False, "model_downgraded_official_warning"

    # Check unknown -> safe
    if result.status == DecisionStatus.INSUFFICIENT_DATA and result.final_verdict == "good":
        return False, "unknown_turned_safe"

    # Check provider order (should be enforced at forecast service level, not here)
    # But verify requested_source == weathernext wasn't substituted
    if context.requested_source == "weathernext" and result.selected_source != "weathernext":
        if result.status != DecisionStatus.PROVIDER_UNAVAILABLE:
            return False, "pinned_source_substituted"

    return True, None


def confidence_gate(
    confidence: Optional[float],
    min_confidence: float,
) -> bool:
    """Check if confidence meets gate, with validation."""
    if confidence is None:
        return False
    if not math.isfinite(confidence):
        return False
    if confidence < 0 or confidence > 1:
        return False
    return confidence >= min_confidence
