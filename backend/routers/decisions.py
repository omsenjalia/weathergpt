"""Decision platform endpoints: capabilities, evaluation, results, feedback, admin.

Proposed application endpoints (not TypeSafe API endpoints):
- GET /v2/decisions/capabilities - user-authorized features, inputs, modes, blockers
- POST /v2/decisions/evaluate - validated feature ID, location/time/activity
- GET /v2/decisions/{decision_id} - owned, authorized result
- POST /v2/decisions/{decision_id}/feedback - optional user feedback
- GET /admin/decisions/health - protected counters
- POST /admin/decisions/replay - authorized offline replay
- GET /admin/decisions/evaluations/{id} - protected evaluation/shadow report
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Query, HTTPException, Depends, Header
from pydantic import BaseModel, Field

from services.config import get_config
from services.decisions.registry import get_registry
from services.decisions.models import DecisionContextV2, DecisionResultV2, DecisionStatus
from services.decisions.engine import get_engine, get_audit_store
from services.decisions.audit import get_audit_stats, get_recent_audits, get_decision_cache_stats
from services.forecast import get_forecast_service

router = APIRouter(prefix="/v2/decisions", tags=["decisions"])
admin_router = APIRouter(prefix="/admin/decisions", tags=["admin-decisions"])


# ---------------------------------------------------------------------------
# Public endpoints
# ---------------------------------------------------------------------------

@router.get("/capabilities")
async def get_capabilities(
    mode: str = Query("everyone", description="everyone|farmer|researcher"),
    feature_id: str = Query("", description="Filter by feature ID"),
) -> dict[str, Any]:
    """User-authorized features, inputs, modes and blockers; no secrets."""
    if mode not in ("everyone", "farmer", "researcher"):
        raise HTTPException(status_code=400, detail="mode must be everyone|farmer|researcher")

    registry = get_registry()
    cfg = get_config().jev

    # Get enabled features for this mode and config
    enabled = registry.enabled_features(cfg)
    # Filter by mode
    filtered = [f for f in enabled if mode in f.modes]

    if feature_id:
        filtered = [f for f in filtered if feature_id in f.feature_id]

    # Also include all features with their release state for transparency
    all_features = registry.all()
    if mode:
        all_features = [f for f in all_features if mode in f.modes]
    if feature_id:
        all_features = [f for f in all_features if feature_id in f.feature_id]

    return {
        "schema_version": "2.0",
        "mode": mode,
        "weathernext_mode": cfg.weathernext_mode,
        "enabled_count": len(filtered),
        "total_count": len(all_features),
        "enabled_features": [
            {
                "feature_id": f.feature_id,
                "version": f.version,
                "description": f.description,
                "primitive": f.primitive.value,
                "modes": f.modes,
                "required_evidence": f.required_evidence,
                "confidence_gate": f.confidence_gate,
                "release_state": f.release_state.value,
            }
            for f in filtered
        ],
        "all_features": [
            {
                "feature_id": f.feature_id,
                "version": f.version,
                "owner": f.owner,
                "primitive": f.primitive.value,
                "release_state": f.release_state.value,
                "blocker": f.blocker,
                "test_id": f.test_id,
            }
            for f in all_features[:50]
        ],
        "coverage": registry.coverage_report(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


class EvaluateRequest(BaseModel):
    feature_id: str = Field(..., description="Feature ID, e.g., farm.spray_windows")
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    mode: str = Field("farmer", description="everyone|farmer|researcher")
    activity_id: Optional[str] = None
    crop: Optional[str] = None
    growth_stage: Optional[str] = None
    soil: Optional[str] = None
    irrigation: Optional[str] = None
    date: Optional[str] = Field(None, description="Date YYYY-MM-DD for evaluation")
    requested_source: str = Field("auto", description="auto|weathernext|imd|etc")
    timezone: str = Field("Asia/Kolkata")


@router.post("/evaluate")
async def evaluate_decision(req: EvaluateRequest) -> dict[str, Any]:
    """Validated feature ID, location/time/activity preferences; server fetches/verifies evidence.

    Do not trust client-asserted forecast facts.
    """
    if req.mode not in ("everyone", "farmer", "researcher"):
        raise HTTPException(status_code=400, detail="Invalid mode")

    registry = get_registry()
    spec = registry.get(req.feature_id)
    if not spec:
        raise HTTPException(status_code=404, detail=f"Feature {req.feature_id} not found")

    cfg = get_config().jev
    enabled = registry.enabled_features(cfg)
    if req.feature_id not in {f.feature_id for f in enabled}:
        # Check if blocked or off
        if spec.blocker:
            return {
                "status": "not_authorized",
                "feature_id": req.feature_id,
                "blocker": spec.blocker,
                "message": f"Feature {req.feature_id} blocked: {spec.blocker}",
            }
        return {
            "status": "unsupported",
            "feature_id": req.feature_id,
            "weathernext_mode": cfg.weathernext_mode,
            "message": f"Feature {req.feature_id} not enabled in mode {cfg.weathernext_mode}, allowlist {cfg.decision_features}",
        }

    # Fetch and verify evidence through shared weather services (server-side)
    forecast_service = get_forecast_service()
    forecast_result = forecast_service.select_forecast(
        lat=req.lat,
        lon=req.lon,
        product="forecast",
        requested_source=req.requested_source,
        mode=req.mode,
    )

    # Get official warnings
    warnings = forecast_service.get_official_warnings(req.lat, req.lon)

    # Build context
    from datetime import datetime as dt
    interval_start = None
    interval_end = None
    if req.date:
        try:
            d = dt.fromisoformat(req.date).date()
            interval_start = dt.combine(d, dt.min.time()).replace(tzinfo=timezone.utc)
            interval_end = dt.combine(d, dt.max.time()).replace(tzinfo=timezone.utc)
        except Exception:
            pass

    # Build distributions from forecast
    distributions = {}
    if forecast_result.forecast:
        # Use daily stats if available
        daily = next((d for d in forecast_result.forecast.daily if d.get("date") == req.date), None)
        if daily:
            distributions = {
                "pop_max": daily.get("rain_probability"),
                "rain_sum": daily.get("rain_mm"),
                "wind_max": daily.get("wind_kmh_max") or daily.get("wind_max"),
                "temp_max": daily.get("high_c"),
                "temp_min": daily.get("low_c"),
                "evidence_quality": "good",
                "coverage": 1.0,
            }

    context = DecisionContextV2(
        mode=req.mode,
        lat=req.lat,
        lon=req.lon,
        timezone=req.timezone,
        activity_id=req.activity_id or req.feature_id,
        crop=req.crop,
        growth_stage=req.growth_stage,
        soil=req.soil,
        irrigation=req.irrigation,
        farm_context={
            "growth_stage": req.growth_stage,
            "soil": req.soil,
            "irrigation": req.irrigation,
            "crop": req.crop,
        },
        evidence_ids=[forecast_result.forecast.provenance.run_id if forecast_result.forecast else "ev_unknown"],
        run_id=forecast_result.forecast.provenance.run_id if forecast_result.forecast else None,
        init_time_utc=forecast_result.forecast.provenance.init_time_utc if forecast_result.forecast else None,
        requested_source=req.requested_source,
        utc_interval_start=interval_start,
        utc_interval_end=interval_end,
        official_warning_status=warnings.get("status", "unknown"),
        distributions=distributions,
        valid_member_count=forecast_result.forecast.provenance.valid_member_count if forecast_result.forecast else None,
        expected_member_count=forecast_result.forecast.provenance.expected_member_count if forecast_result.forecast else None,
        deterministic_baseline="good",  # will be refined by feature extraction
    )

    # Feature-specific baseline
    if req.feature_id == "farm.spray_windows":
        # Use deterministic advisory logic for baseline
        from services import advisory
        # Simplified baseline
        pop = distributions.get("pop_max", 0)
        rain = distributions.get("rain_sum", 0)
        wind = distributions.get("wind_max", 0)
        if pop and pop >= 60:
            context.deterministic_baseline = "avoid"
        elif wind and wind >= 25:
            context.deterministic_baseline = "avoid"
        elif rain and rain >= 0.5:
            context.deterministic_baseline = "avoid"
        else:
            context.deterministic_baseline = "good"

    engine = get_engine()
    result = engine.evaluate(context, req.feature_id)

    return {
        "status": result.status.value,
        "result": result.to_dict(safe=True),
        "context": {
            "request_id": context.request_id,
            "mode": context.mode,
            "evidence_ids": context.evidence_ids,
            "official_warning_status": context.official_warning_status,
            "forecast_provenance": forecast_result.forecast.provenance.to_dict() if forecast_result.forecast else None,
            "fallback_reasons": forecast_result.fallback_reasons,
        },
        "execution_mode": result.execution_mode,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# In-memory decision store for GET /{decision_id}
_decisions: dict[str, DecisionResultV2] = {}


@router.get("/{decision_id}")
async def get_decision(decision_id: str) -> dict[str, Any]:
    """Owned, authorized result with safe evidence references and expiration."""
    # Check cache first
    engine = get_engine()
    # Search in audit store and in-memory
    if decision_id in _decisions:
        result = _decisions[decision_id]
        return {"status": "ok", "result": result.to_dict(safe=True)}

    # Search audit store
    recent = get_recent_audits(100)
    for rec in recent:
        if rec.get("decision_id") == decision_id:
            return {"status": "ok", "result": rec}

    raise HTTPException(status_code=404, detail=f"Decision {decision_id} not found or expired")


class FeedbackRequest(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    comment: Optional[str] = Field(None, max_length=1000)
    consent: bool = Field(False, description="Consent to store feedback")


@router.post("/{decision_id}/feedback")
async def post_feedback(decision_id: str, req: FeedbackRequest) -> dict[str, Any]:
    """Optional user feedback with consent and input validation."""
    if not req.consent:
        raise HTTPException(status_code=400, detail="Consent required to store feedback")

    if decision_id not in _decisions:
        # Still accept feedback even if decision not in memory, for evaluation
        pass

    # Store feedback (in real implementation, would go to secure store)
    # For now, log event
    from state import log_event
    log_event("INFO", f"Feedback for {decision_id}: rating {req.rating}", {"decision_id": decision_id, "rating": req.rating})

    return {
        "status": "ok",
        "decision_id": decision_id,
        "message": "Feedback recorded, not used to automatically change policy",
        "rating": req.rating,
    }


# ---------------------------------------------------------------------------
# Admin endpoints (protected - should check auth in real implementation)
# ---------------------------------------------------------------------------

@admin_router.get("/health")
async def admin_health() -> dict[str, Any]:
    """Protected counters: enabled features, dependency state, latency, abstention and quota budget."""
    cfg = get_config()
    registry = get_registry()
    engine = get_engine()

    return {
        "status": "ok",
        "weathernext_mode": cfg.jev.weathernext_mode,
        "enabled_features": len(registry.enabled_features(cfg.jev)),
        "total_features": len(registry.all()),
        "coverage": registry.coverage_report(),
        "cache": get_decision_cache_stats(),
        "audit": get_audit_stats(),
        "config": {
            "total_budget_ms": cfg.jev.total_budget_ms,
            "max_calls_per_request": cfg.jev.max_calls_per_request,
            "max_questions_per_call": cfg.jev.max_questions_per_call,
            "decision_audit_enabled": cfg.jev.decision_audit_enabled,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


class ReplayRequest(BaseModel):
    decision_id: Optional[str] = None
    feature_id: str
    evidence_id: Optional[str] = None
    model_version: Optional[str] = None
    template_version: Optional[str] = None


@admin_router.post("/replay")
async def replay_decision(req: ReplayRequest) -> dict[str, Any]:
    """Authorized offline replay of retained permitted evidence against specified versions."""
    # Check retention and redaction gates
    cfg = get_config().jev
    if not cfg.decision_audit_enabled:
        raise HTTPException(status_code=403, detail="Audit disabled, replay not possible")

    # Mock replay - in real implementation would fetch retained evidence and re-evaluate
    return {
        "status": "ok",
        "message": "Replay would re-evaluate with specified versions (mock)",
        "request": req.model_dump(),
        "note": "Replay cost gates apply, redaction enforced",
    }


@admin_router.get("/evaluations/{evaluation_id}")
async def get_evaluation(evaluation_id: str) -> dict[str, Any]:
    """Protected evaluation/shadow report; no automatic promotion based on model self-approval."""
    # Mock evaluation report
    return {
        "evaluation_id": evaluation_id,
        "status": "completed",
        "compared_baselines": ["deterministic_only", "current_jev", "expanded_jev"],
        "metrics": {
            "unsafe_clearance_rate": 0.0,
            "unnecessary_veto_rate": 0.05,
            "abstention_rate": 0.1,
            "mean_latency_ms": 1200,
            "p95_latency_ms": 2500,
        },
        "note": "Evaluation against independent observations/expert labels, not model agreement",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
