"""Privacy-first diagnostics and audit records.

Implements secure backend store for audit, with retention and redaction.
Raw prompt/model payload logging stays disabled in production.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

from services.decisions.engine import get_audit_store, get_decision_cache


def get_audit_stats() -> dict:
    store = get_audit_store()
    return store.stats()


def get_recent_audits(limit: int = 20) -> list[dict]:
    store = get_audit_store()
    return store.get_recent(limit)


def get_decision_cache_stats() -> dict:
    from services.forecast_cache import get_cache
    forecast_cache = get_cache()
    decision_cache = get_decision_cache()
    return {
        "forecast_cache": forecast_cache.stats(),
        "decision_cache": {
            "size": len(decision_cache._cache),
            "max_size": decision_cache.max_size,
        },
        "audit": get_audit_stats(),
    }
