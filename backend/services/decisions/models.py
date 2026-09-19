"""Typed models for decision platform: FeatureSpec, ContextV2, ResultV2.

Implements contracts from jev_backend_plan.md sections 4 and 5.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional


class FeaturePrimitive(str, Enum):
    CHOICE = "choice"
    SCORE = "score"
    NOUL = "noul"


class DecisionStatus(str, Enum):
    EVALUATED = "evaluated"
    ABSTAINED = "abstained"
    INSUFFICIENT_DATA = "insufficient_data"
    NOT_AUTHORIZED = "not_authorized"
    UNSUPPORTED = "unsupported"
    BUDGET_EXCEEDED = "budget_exceeded"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    INVALID_ANSWER = "invalid_answer"
    PENDING_JOB = "pending_job"


class ReleaseState(str, Enum):
    OFF = "off"
    SHADOW = "shadow"
    ENFORCE = "enforce"


@dataclass(frozen=True)
class DecisionFeatureSpec:
    """Stable spec for a decision feature."""
    feature_id: str
    version: str
    owner: str
    description: str
    primitive: FeaturePrimitive
    modes: list[str]  # everyone, farmer, researcher
    callers: list[str]  # which routes/tools can call it
    required_evidence: list[str]  # e.g., ["rain_accumulation", "wind_speed"]
    optional_evidence: list[str] = field(default_factory=list)
    evidence_units: dict[str, str] = field(default_factory=dict)
    evidence_intervals: dict[str, str] = field(default_factory=dict)
    source_constraints: list[str] = field(default_factory=list)  # e.g., ["weathernext_ensemble"]
    coverage_requirements: dict[str, Any] = field(default_factory=dict)
    freshness_requirements: dict[str, Any] = field(default_factory=dict)
    sensitivity_tags: list[str] = field(default_factory=list)  # e.g., ["farm_location", "private"]
    processor_sharing_allowed: bool = False
    candidate_construction: str = ""  # how candidates built
    hard_exclusions: list[str] = field(default_factory=list)
    allowed_choices: list[str] = field(default_factory=list)
    ordered_score_criteria: list[str] = field(default_factory=list)
    noul_proposition: str = ""
    template_version: str = "1.0"
    confidence_gate: float = 0.55
    fallback: str = "deterministic"
    abstention_semantics: str = "no_opinion"
    latency_class: str = "fast"  # fast, medium, slow
    cost_class: str = "low"  # low, medium, high
    execution_tier: str = "sync"  # sync, async
    audit_policy: str = "structured_only"
    test_id: str = ""
    release_state: ReleaseState = ReleaseState.OFF
    blocker: Optional[str] = None


@dataclass
class DecisionContextV2:
    """Normalized context before calling Jev.

    From plan section 4: Request ID, mode, auth scope, location/timezone,
    activity/plot IDs, farm context, evidence IDs, model/run/version,
    valid/expected members, masks, incompleteness, official-warning status,
    backend-calculated distributions, permitted candidates, baseline, etc.
    """
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    mode: str = "everyone"  # everyone, farmer, researcher
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    auth_scope: dict = field(default_factory=dict)
    requested_source: str = "auto"
    requested_product: str = "forecast"
    requested_run: Optional[str] = None

    # Location/time
    lat: float = 0.0
    lon: float = 0.0
    timezone: str = "Asia/Kolkata"
    location_name: Optional[str] = None
    utc_interval_start: Optional[datetime] = None
    utc_interval_end: Optional[datetime] = None
    local_interval_start: Optional[datetime] = None
    local_interval_end: Optional[datetime] = None

    # Activity/plot
    activity_id: Optional[str] = None
    plot_id: Optional[str] = None
    crop: Optional[str] = None
    growth_stage: Optional[str] = None
    soil: Optional[str] = None
    irrigation: Optional[str] = None
    farm_context: dict = field(default_factory=dict)

    # Evidence
    evidence_ids: list[str] = field(default_factory=list)
    model: Optional[str] = None
    model_version: Optional[str] = None
    run_id: Optional[str] = None
    init_time_utc: Optional[datetime] = None
    valid_time_utc: Optional[datetime] = None
    publication_time_utc: Optional[datetime] = None
    ingestion_time_utc: Optional[datetime] = None
    sampled_grid: Optional[dict] = None
    field_source: Optional[str] = None
    units: dict = field(default_factory=dict)
    derivation_version: str = "1.0"

    # Coverage
    valid_member_count: Optional[int] = None
    expected_member_count: Optional[int] = None
    valid_time_samples: Optional[int] = None
    expected_time_samples: Optional[int] = None
    masks: dict = field(default_factory=dict)
    incompleteness_reason: Optional[str] = None

    # Warnings
    official_warning_status: str = "unknown"
    official_warning_validity: Optional[datetime] = None
    last_warning_retrieval: Optional[datetime] = None

    # Calculated
    distributions: dict = field(default_factory=dict)
    counts: dict = field(default_factory=dict)
    thresholds: dict = field(default_factory=dict)
    joint_probabilities: dict = field(default_factory=dict)

    # Candidates
    permitted_candidates: list[dict] = field(default_factory=list)
    deterministic_baseline: Optional[str] = None
    required_clarifications: list[str] = field(default_factory=list)

    # Metadata
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    schema_version: str = "2.0"

    def is_data_sufficient(self) -> tuple[bool, Optional[str]]:
        """Check if context has sufficient data for decision."""
        if not self.evidence_ids:
            return False, "missing_evidence_ids"
        if self.valid_member_count is not None and self.expected_member_count:
            if self.valid_member_count / self.expected_member_count < 0.5:
                return False, "insufficient_member_coverage"
        if self.official_warning_status == "unknown":
            # Unknown warnings should not block but flag
            pass
        return True, None

    def to_compact_state(self, max_chars: int = 7000) -> str:
        """Serialize to compact text for Jev, preserving safety/date/evidence."""
        lines = [
            f"Request: {self.request_id}, Mode: {self.mode}, Source: {self.requested_source}",
            f"Location: {self.lat:.2f},{self.lon:.2f} ({self.location_name or 'unknown'}), TZ: {self.timezone}",
        ]
        if self.utc_interval_start and self.utc_interval_end:
            lines.append(f"Interval UTC: {self.utc_interval_start.isoformat()} to {self.utc_interval_end.isoformat()}")
        if self.activity_id:
            lines.append(f"Activity: {self.activity_id}, Crop: {self.crop or 'unknown'}, Stage: {self.growth_stage or 'unknown'}")
        if self.evidence_ids:
            lines.append(f"Evidence IDs: {', '.join(self.evidence_ids[:5])}")
        if self.run_id:
            lines.append(f"Run: {self.run_id}, Init: {self.init_time_utc.isoformat() if self.init_time_utc else 'unknown'}")
        if self.distributions:
            for key, val in list(self.distributions.items())[:5]:
                lines.append(f"{key}: {val}")
        if self.thresholds:
            lines.append(f"Thresholds: {self.thresholds}")
        if self.official_warning_status != "unknown":
            lines.append(f"Official warning: {self.official_warning_status}")
        else:
            lines.append("Official warning: unknown (not no alerts)")

        if self.permitted_candidates:
            lines.append(f"Candidates: {len(self.permitted_candidates)} eligible")
            for cand in self.permitted_candidates[:3]:
                lines.append(f"  - {cand.get('id')}: {cand.get('summary', '')}")

        full = "\n".join(lines)
        if len(full) > max_chars:
            # Truncate but preserve first and last safety lines
            header = "\n".join(lines[:3]) + "\n"
            footer = f"\n[truncated, total {len(full)} chars, evidence preserved: {self.evidence_ids[:2]}]"
            budget = max_chars - len(header) - len(footer)
            middle = "\n".join(lines[3:])[:budget]
            full = header + middle + footer

        return full


@dataclass
class DecisionResultV2:
    """Stable envelope for decision results.

    From plan section 4: schema_version, decision_id, feature_id/version,
    request_id, mode, activity/plot, interval, evidence_ids, requested/selected_source,
    execution_mode, status, deterministic/model/final verdicts, candidate, score,
    confidence, weather probability, evidence quality, flags, reason codes, etc.
    """
    schema_version: str = "2.0"
    decision_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    feature_id: str = ""
    feature_version: str = "1.0"
    request_id: str = ""

    mode: str = "everyone"
    activity_id: Optional[str] = None
    plot_id: Optional[str] = None
    interval_start: Optional[datetime] = None
    interval_end: Optional[datetime] = None
    evidence_ids: list[str] = field(default_factory=list)
    requested_source: str = "auto"
    selected_source: str = "unknown"

    execution_mode: str = "off"  # off, shadow, enforce
    status: DecisionStatus = DecisionStatus.EVALUATED

    deterministic_verdict: Optional[str] = None
    model_verdict: Optional[str] = None
    final_verdict: Optional[str] = None

    selected_candidate_id: Optional[str] = None
    score: Optional[float] = None
    criteria: Optional[str] = None
    decision_confidence: Optional[float] = None

    weather_event_probability: Optional[float] = None
    weather_event_definition: Optional[str] = None
    evidence_quality: str = "unknown"
    valid_member_count: Optional[int] = None
    expected_member_count: Optional[int] = None

    constraint_flags: list[str] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)
    missing_inputs: list[str] = field(default_factory=list)
    suggested_followup: Optional[str] = None

    model_requested: Optional[str] = None
    model_resolved: Optional[str] = None
    template_version: str = "1.0"
    rule_version: str = "1.0"
    feature_version_resolved: str = "1.0"

    latency_ms: Optional[float] = None
    attempts: int = 1
    usage: dict = field(default_factory=dict)
    cache_state: str = "miss"  # hit, miss, stale

    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = None

    def to_dict(self, safe: bool = True) -> dict:
        """Convert to dict, with safe mode redacting internal diagnostics."""
        d = {
            "schema_version": self.schema_version,
            "decision_id": self.decision_id,
            "feature_id": self.feature_id,
            "feature_version": self.feature_version,
            "request_id": self.request_id,
            "mode": self.mode,
            "activity_id": self.activity_id,
            "plot_id": self.plot_id,
            "interval": {
                "start": self.interval_start.isoformat() if self.interval_start else None,
                "end": self.interval_end.isoformat() if self.interval_end else None,
            },
            "evidence_ids": self.evidence_ids,
            "requested_source": self.requested_source,
            "selected_source": self.selected_source,
            "execution_mode": self.execution_mode,
            "status": self.status.value,
            "deterministic_verdict": self.deterministic_verdict,
            "model_verdict": self.model_verdict,
            "final_verdict": self.final_verdict,
            "selected_candidate_id": self.selected_candidate_id,
            "score": self.score,
            "criteria": self.criteria,
            "decision_confidence": self.decision_confidence,
            "weather_event_probability": self.weather_event_probability,
            "weather_event_definition": self.weather_event_definition,
            "evidence_quality": self.evidence_quality,
            "constraint_flags": self.constraint_flags,
            "reason_codes": self.reason_codes,
            "missing_inputs": self.missing_inputs,
            "suggested_followup": self.suggested_followup,
            "model": {
                "requested": self.model_requested,
                "resolved": self.model_resolved,
            },
            "versions": {
                "template": self.template_version,
                "rule": self.rule_version,
                "feature": self.feature_version_resolved,
            },
            "latency_ms": self.latency_ms,
            "attempts": self.attempts,
            "cache_state": self.cache_state,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }
        if not safe:
            d["usage"] = self.usage
            d["valid_member_count"] = self.valid_member_count
            d["expected_member_count"] = self.expected_member_count
        return d

    def is_safe_to_apply(self) -> bool:
        """Check if decision is safe to apply (not unsafe clearance)."""
        if self.status in (DecisionStatus.INSUFFICIENT_DATA, DecisionStatus.PROVIDER_UNAVAILABLE, DecisionStatus.NOT_AUTHORIZED):
            return False
        if self.final_verdict in ("avoid", "poor") and self.deterministic_verdict in ("avoid", "poor"):
            # Both agree unsafe - safe to avoid
            return True
        if self.final_verdict == "good" and self.deterministic_verdict in ("avoid", "poor"):
            # Model says good but deterministic says avoid - unsafe clearance, must not apply
            return False
        return True
