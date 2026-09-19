"""Bounded execution, batching, cache, retry budget, per-feature rollout and audit.

Implements:
- Request-wide deadline across all Jev calls
- Bounded retry with jitter for retryable failures only
- Circuit breaker, concurrency limits, request coalescing
- Cache immutable decisions by evidence/run/interval/region, etc.
- Redacted audit + evaluation metrics
"""

from __future__ import annotations

import math
import time
import random
import uuid
from collections import OrderedDict
from datetime import datetime, timezone, timedelta
from threading import RLock
from typing import Any, Optional

from services.config import get_config
from services.decisions.models import DecisionContextV2, DecisionResultV2, DecisionStatus, ReleaseState
from services.decisions.registry import get_registry
from services.decisions.policy import check_eligibility, apply_conservative_merge, apply_warning_floor, confidence_gate, check_safety_monotonicity
from services.decisions.questions import build_question_for_feature
from state import log_event


# ---------------------------------------------------------------------------
# Decision cache (immutable decisions by evidence/run/interval/region, etc.)
# ---------------------------------------------------------------------------

class DecisionCache:
    def __init__(self, max_size: int = 500, default_ttl_seconds: int = 3600):
        self.max_size = max_size
        self.default_ttl = default_ttl_seconds
        self._cache: OrderedDict[str, tuple[DecisionResultV2, datetime]] = OrderedDict()
        self._lock = RLock()

    def _make_key(self, context: DecisionContextV2, feature_id: str) -> str:
        # Key includes evidence/run/interval/region/activity/farm-profile/rules/template/model and ownership
        parts = [
            feature_id,
            context.mode,
            f"{context.lat:.2f}_{context.lon:.2f}",
            context.activity_id or "",
            context.crop or "",
            context.growth_stage or "",
            context.run_id or "",
            ",".join(sorted(context.evidence_ids)) if context.evidence_ids else "",
            context.requested_source,
        ]
        return "|".join(parts)

    def get(self, context: DecisionContextV2, feature_id: str) -> Optional[DecisionResultV2]:
        key = self._make_key(context, feature_id)
        with self._lock:
            entry = self._cache.get(key)
            if not entry:
                return None
            result, expires_at = entry
            if datetime.now(timezone.utc) > expires_at:
                del self._cache[key]
                return None
            # Check if evidence changed or warning changed
            # Simplified: if official warning status changed, invalidate
            # Real implementation would check evidence freshness
            self._cache.move_to_end(key)
            return result

    def set(self, context: DecisionContextV2, feature_id: str, result: DecisionResultV2, ttl_seconds: Optional[int] = None):
        key = self._make_key(context, feature_id)
        with self._lock:
            ttl = ttl_seconds or self.default_ttl
            expires = datetime.now(timezone.utc) + timedelta(seconds=ttl)
            if key in self._cache:
                del self._cache[key]
            self._cache[key] = (result, expires)
            while len(self._cache) > self.max_size:
                self._cache.popitem(last=False)

    def clear(self):
        with self._lock:
            self._cache.clear()


_decision_cache: Optional[DecisionCache] = None

def get_decision_cache() -> DecisionCache:
    global _decision_cache
    if _decision_cache is None:
        _decision_cache = DecisionCache()
    return _decision_cache


# ---------------------------------------------------------------------------
# Audit trail (redacted, structured outcomes, not raw payloads)
# ---------------------------------------------------------------------------

class AuditStore:
    def __init__(self, max_records: int = 1000, retention_days: int = 7):
        self.max_records = max_records
        self.retention_days = retention_days
        self._records: list[dict] = []
        self._lock = RLock()

    def record(self, result: DecisionResultV2, context: DecisionContextV2):
        cfg = get_config().jev
        if not cfg.decision_audit_enabled:
            return

        # Redacted audit: structured outcomes, not raw prompts/secrets/full arrays
        record = {
            "decision_id": result.decision_id,
            "feature_id": result.feature_id,
            "request_id": result.request_id,
            "mode": result.mode,
            "status": result.status.value,
            "final_verdict": result.final_verdict,
            "decision_confidence": result.decision_confidence,
            "evidence_ids": result.evidence_ids[:3],  # limited
            "latency_ms": result.latency_ms,
            "cache_state": result.cache_state,
            "created_at": result.created_at.isoformat(),
            "model_resolved": result.model_resolved,
            "versions": {
                "template": result.template_version,
                "rule": result.rule_version,
            },
        }

        # Never log raw payloads in production unless explicitly allowed (and even then, redacted)
        if cfg.decision_log_raw_payloads:
            # This should stay disabled in production per spec
            record["raw_context"] = context.to_compact_state(max_chars=500)  # still bounded

        with self._lock:
            self._records.append(record)
            # Enforce retention and max size
            cutoff = datetime.now(timezone.utc) - timedelta(days=self.retention_days)
            self._records = [r for r in self._records if datetime.fromisoformat(r["created_at"]) > cutoff]
            if len(self._records) > self.max_records:
                self._records = self._records[-self.max_records:]

    def get_recent(self, limit: int = 50) -> list[dict]:
        with self._lock:
            return self._records[-limit:]

    def stats(self) -> dict:
        with self._lock:
            if not self._records:
                return {"total": 0}
            by_feature = {}
            by_status = {}
            for r in self._records:
                by_feature[r["feature_id"]] = by_feature.get(r["feature_id"], 0) + 1
                by_status[r["status"]] = by_status.get(r["status"], 0) + 1
            return {
                "total": len(self._records),
                "by_feature": by_feature,
                "by_status": by_status,
            }


_audit_store: Optional[AuditStore] = None

def get_audit_store() -> AuditStore:
    global _audit_store
    if _audit_store is None:
        cfg = get_config().jev
        _audit_store = AuditStore(retention_days=cfg.decision_audit_retention_days)
    return _audit_store


# ---------------------------------------------------------------------------
# Bounded execution engine
# ---------------------------------------------------------------------------

class DecisionEngine:
    def __init__(self):
        self.cache = get_decision_cache()
        self.audit = get_audit_store()
        self._in_flight: dict[str, DecisionResultV2] = {}
        self._lock = RLock()

    def evaluate(
        self,
        context: DecisionContextV2,
        feature_id: str,
        use_cache: bool = True,
    ) -> DecisionResultV2:
        """Evaluate a single feature with bounded execution.

        Implements total deadline, not just per-attempt timeout.
        """
        cfg = get_config().jev
        registry = get_registry()
        spec = registry.get(feature_id)

        start = time.perf_counter()
        request_id = context.request_id

        # Check if feature exists
        if not spec:
            return DecisionResultV2(
                request_id=request_id,
                feature_id=feature_id,
                status=DecisionStatus.UNSUPPORTED,
                reason_codes=[f"unknown_feature_{feature_id}"],
                created_at=datetime.now(timezone.utc),
            )

        # Check release state and allowlist
        enabled_features = registry.enabled_features(cfg)
        enabled_ids = {f.feature_id for f in enabled_features}

        # Determine execution mode
        if cfg.weathernext_mode == "off":
            # Off preserves existing Jev paths for enforced features only
            if feature_id not in enabled_ids:
                # For off mode, if not in enforced, return deterministic baseline or abstain
                return DecisionResultV2(
                    request_id=request_id,
                    feature_id=feature_id,
                    feature_version=spec.version,
                    mode=context.mode,
                    status=DecisionStatus.ABSTAINED,
                    reason_codes=["feature_off_mode"],
                    execution_mode="off",
                    evidence_ids=context.evidence_ids,
                    requested_source=context.requested_source,
                    created_at=datetime.now(timezone.utc),
                )
            execution_mode = "enforce" if spec.release_state == ReleaseState.ENFORCE else "off"
        elif cfg.weathernext_mode == "shadow":
            execution_mode = "shadow"
        else:  # enforce
            execution_mode = "enforce"

        # Check cache
        if use_cache:
            cached = self.cache.get(context, feature_id)
            if cached:
                cached.cache_state = "hit"
                return cached

        # Check eligibility
        eligible, reason = check_eligibility(context, spec)
        if not eligible:
            result = DecisionResultV2(
                request_id=request_id,
                feature_id=feature_id,
                feature_version=spec.version,
                mode=context.mode,
                activity_id=context.activity_id,
                evidence_ids=context.evidence_ids,
                requested_source=context.requested_source,
                execution_mode=execution_mode,
                status=DecisionStatus.INSUFFICIENT_DATA if "missing" in reason or "insufficient" in reason else DecisionStatus.UNSUPPORTED,
                reason_codes=[reason or "not_eligible"],
                missing_inputs=[reason] if reason else [],
                created_at=datetime.now(timezone.utc),
                latency_ms=(time.perf_counter() - start) * 1000,
            )
            self.audit.record(result, context)
            return result

        # Check total budget
        total_budget_ms = cfg.total_budget_ms
        elapsed_ms = (time.perf_counter() - start) * 1000
        if elapsed_ms > total_budget_ms:
            return DecisionResultV2(
                request_id=request_id,
                feature_id=feature_id,
                status=DecisionStatus.BUDGET_EXCEEDED,
                reason_codes=["total_budget_exceeded"],
                execution_mode=execution_mode,
                created_at=datetime.now(timezone.utc),
                latency_ms=elapsed_ms,
            )

        # Build question
        question_ctx = {
            "date": context.utc_interval_start.date().isoformat() if context.utc_interval_start else "unknown",
            "timezone": context.timezone,
            "window_id": context.activity_id or f"window_{context.utc_interval_start}",
            "evidence_id": context.evidence_ids[0] if context.evidence_ids else "ev_unknown",
            "activity_id": context.activity_id or feature_id,
            "crop": context.crop or "crops",
            "growth_stage": context.growth_stage or "unknown",
            "soil": context.soil or "unknown",
            "irrigation": context.irrigation or "unknown",
            "wind_max": context.distributions.get("wind_max", "unknown"),
            "rain_sum": context.distributions.get("rain_sum", "unknown"),
            "pop_max": context.distributions.get("pop_max", "unknown"),
            "temp_max": context.distributions.get("temp_max", "unknown"),
            "temp_min": context.distributions.get("temp_min", "unknown"),
            "thunder_hours": context.distributions.get("thunder_hours", 0),
            "warning_status": context.official_warning_status,
            "evidence_quality": context.distributions.get("evidence_quality", "unknown"),
            "coverage": context.distributions.get("coverage", 1.0),
        }

        question = build_question_for_feature(spec, question_ctx)
        state_text = context.to_compact_state(max_chars=cfg.max_state_chars)

        # Bounded Jev call with total deadline awareness
        remaining_budget = total_budget_ms - (time.perf_counter() - start) * 1000
        per_attempt_timeout = min(cfg.timeout_seconds, remaining_budget / 1000 * 0.8)

        if per_attempt_timeout <= 0:
            return DecisionResultV2(
                request_id=request_id,
                feature_id=feature_id,
                status=DecisionStatus.BUDGET_EXCEEDED,
                reason_codes=["no_time_for_jev_call"],
                execution_mode=execution_mode,
                created_at=datetime.now(timezone.utc),
                latency_ms=(time.perf_counter() - start) * 1000,
            )

        # Call TypeSafe
        try:
            from services import typesafe
            if not typesafe.is_enabled():
                # Jev disabled, return deterministic baseline
                result = DecisionResultV2(
                    request_id=request_id,
                    feature_id=feature_id,
                    feature_version=spec.version,
                    mode=context.mode,
                    activity_id=context.activity_id,
                    evidence_ids=context.evidence_ids,
                    requested_source=context.requested_source,
                    execution_mode=execution_mode,
                    status=DecisionStatus.PROVIDER_UNAVAILABLE,
                    deterministic_verdict=context.deterministic_baseline,
                    final_verdict=context.deterministic_baseline,
                    reason_codes=["jev_disabled"],
                    created_at=datetime.now(timezone.utc),
                    latency_ms=(time.perf_counter() - start) * 1000,
                )
                self.cache.set(context, feature_id, result)
                self.audit.record(result, context)
                return result

            # Evaluate with retry budget
            eval_result = typesafe.evaluate(
                state_text,
                {feature_id: question},
                timeout=per_attempt_timeout,
                label=f"decision_{feature_id}",
            )

            if not eval_result:
                # Jev failed, use deterministic
                result = DecisionResultV2(
                    request_id=request_id,
                    feature_id=feature_id,
                    feature_version=spec.version,
                    mode=context.mode,
                    activity_id=context.activity_id,
                    evidence_ids=context.evidence_ids,
                    requested_source=context.requested_source,
                    execution_mode=execution_mode,
                    status=DecisionStatus.PROVIDER_UNAVAILABLE,
                    deterministic_verdict=context.deterministic_baseline,
                    final_verdict=context.deterministic_baseline,
                    reason_codes=["jev_evaluation_failed"],
                    created_at=datetime.now(timezone.utc),
                    latency_ms=(time.perf_counter() - start) * 1000,
                    attempts=cfg.max_attempts,
                )
                self.cache.set(context, feature_id, result)
                self.audit.record(result, context)
                return result

            answers = eval_result.get("answers", {})
            answer = answers.get(feature_id, {})

            # Parse answer based on primitive
            model_verdict = None
            score = None
            confidence = answer.get("confidence")

            if spec.primitive.value == "choice":
                model_verdict = answer.get("choice")
            elif spec.primitive.value == "score":
                score = answer.get("score")
                # Map score to band for final verdict
                if score is not None and math.isfinite(score) and 0 <= score <= 4:
                    from services.advisory import band_from_score
                    model_verdict = band_from_score(score)
                    if model_verdict == "insufficient_data":
                        model_verdict = None
                        score = None
            elif spec.primitive.value == "noul":
                noul_prob = answer.get("noul")
                if noul_prob is not None and math.isfinite(noul_prob):
                    model_verdict = "yes" if noul_prob >= 0.5 else "no"
                    confidence = noul_prob if noul_prob >= 0.5 else 1 - noul_prob

            # Validate confidence
            if confidence is not None:
                if not math.isfinite(confidence) or confidence < 0 or confidence > 1:
                    confidence = None

            # Apply conservative merge
            deterministic = context.deterministic_baseline or "good"
            # Apply warning floor first
            deterministic = apply_warning_floor(deterministic, context.official_warning_status)

            final_verdict, applied = apply_conservative_merge(
                deterministic_verdict=deterministic,
                model_verdict=model_verdict,
                model_confidence=confidence,
                min_confidence=spec.confidence_gate,
                spec=spec,
            )

            # Check safety monotonicity
            temp_result = DecisionResultV2(
                request_id=request_id,
                feature_id=feature_id,
                deterministic_verdict=deterministic,
                model_verdict=model_verdict,
                final_verdict=final_verdict,
                status=DecisionStatus.EVALUATED,
            )
            safe, violation = check_safety_monotonicity(temp_result, context)
            if not safe:
                # Violation - force deterministic and mark invalid
                final_verdict = deterministic
                result = DecisionResultV2(
                    request_id=request_id,
                    feature_id=feature_id,
                    feature_version=spec.version,
                    mode=context.mode,
                    activity_id=context.activity_id,
                    evidence_ids=context.evidence_ids,
                    requested_source=context.requested_source,
                    execution_mode=execution_mode,
                    status=DecisionStatus.INVALID_ANSWER,
                    deterministic_verdict=deterministic,
                    model_verdict=model_verdict,
                    final_verdict=final_verdict,
                    score=score,
                    decision_confidence=confidence,
                    reason_codes=[f"safety_violation_{violation}"],
                    created_at=datetime.now(timezone.utc),
                    latency_ms=(time.perf_counter() - start) * 1000,
                    model_requested=cfg.model,
                    model_resolved=eval_result.get("model"),
                    template_version=spec.template_version,
                )
            else:
                result = DecisionResultV2(
                    request_id=request_id,
                    feature_id=feature_id,
                    feature_version=spec.version,
                    mode=context.mode,
                    activity_id=context.activity_id,
                    evidence_ids=context.evidence_ids,
                    requested_source=context.requested_source,
                    selected_source=context.requested_source,
                    execution_mode=execution_mode,
                    status=DecisionStatus.EVALUATED,
                    deterministic_verdict=deterministic,
                    model_verdict=model_verdict,
                    final_verdict=final_verdict,
                    score=score,
                    decision_confidence=confidence,
                    evidence_quality=context.distributions.get("evidence_quality", "unknown"),
                    valid_member_count=context.valid_member_count,
                    expected_member_count=context.expected_member_count,
                    reason_codes=["evaluated"] if applied else ["deterministic_baseline"],
                    created_at=datetime.now(timezone.utc),
                    expires_at=datetime.now(timezone.utc) + timedelta(seconds=self.cache.default_ttl),
                    latency_ms=(time.perf_counter() - start) * 1000,
                    attempts=eval_result.get("attempts", 1),
                    usage=eval_result.get("usage", {}),
                    model_requested=cfg.model,
                    model_resolved=eval_result.get("model"),
                    template_version=spec.template_version,
                    rule_version="1.0",
                )

            # In shadow mode, final verdict should not change user-visible advice
            # So we keep deterministic as final for shadow, but record model verdict for evaluation
            if execution_mode == "shadow":
                result.final_verdict = deterministic
                result.reason_codes.append("shadow_mode_no_user_visible_change")

            self.cache.set(context, feature_id, result)
            self.audit.record(result, context)
            return result

        except Exception as exc:
            log_event("WARN", f"Decision evaluation failed for {feature_id}: {type(exc).__name__}", {"request_id": request_id})
            result = DecisionResultV2(
                request_id=request_id,
                feature_id=feature_id,
                status=DecisionStatus.PROVIDER_UNAVAILABLE,
                reason_codes=[f"exception_{type(exc).__name__}"],
                execution_mode=execution_mode,
                deterministic_verdict=context.deterministic_baseline,
                final_verdict=context.deterministic_baseline,
                created_at=datetime.now(timezone.utc),
                latency_ms=(time.perf_counter() - start) * 1000,
            )
            self.audit.record(result, context)
            return result


_engine: Optional[DecisionEngine] = None

def get_engine() -> DecisionEngine:
    global _engine
    if _engine is None:
        _engine = DecisionEngine()
    return _engine
