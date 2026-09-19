"""Base provider interface for forecast providers.

All providers implement the same contract with capability metadata,
freshness checks, and explicit unavailable states.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from services.forecast_models import (
    NormalizedForecast,
    ProviderName,
    ProviderCapability,
    FreshnessStatus,
)


@dataclass
class ProviderResult:
    """Result from a provider fetch attempt."""
    success: bool
    forecast: Optional[NormalizedForecast] = None
    error: Optional[str] = None
    error_code: str = "unknown"  # not_granted, unavailable, timeout, rate_limited, etc.
    fallback_reason: Optional[dict] = None
    latency_ms: Optional[float] = None
    is_stale: bool = False


class BaseForecastProvider(ABC):
    """Abstract base for all forecast providers."""

    def __init__(self):
        self._last_success: Optional[datetime] = None
        self._consecutive_failures: int = 0

    @property
    @abstractmethod
    def name(self) -> ProviderName:
        pass

    @property
    @abstractmethod
    def capability(self) -> ProviderCapability:
        pass

    @abstractmethod
    def is_configured(self) -> bool:
        """Check if provider has required credentials/config."""
        pass

    @abstractmethod
    def is_eligible(self, product: str, lat: float, lon: float) -> tuple[bool, Optional[str]]:
        """Check if provider can serve this product for location. Returns (eligible, reason_if_not)."""
        pass

    @abstractmethod
    def fetch(self, lat: float, lon: float, product: str = "forecast", **kwargs) -> ProviderResult:
        """Fetch forecast. Must be synchronous for threadpool use."""
        pass

    def get_freshness_status(self, init_time: Optional[datetime]) -> FreshnessStatus:
        """Determine freshness based on init time and budget."""
        if not init_time:
            return FreshnessStatus.UNKNOWN
        age_hours = (datetime.now(timezone.utc) - init_time).total_seconds() / 3600.0
        budget = self.capability.freshness_budget_hours
        if age_hours <= budget:
            return FreshnessStatus.FRESH
        elif age_hours <= budget * 2:
            return FreshnessStatus.STALE
        else:
            return FreshnessStatus.EXPIRED

    def record_success(self):
        self._last_success = datetime.now(timezone.utc)
        self._consecutive_failures = 0

    def record_failure(self):
        self._consecutive_failures += 1

    def should_circuit_break(self) -> bool:
        """Simple circuit breaker: 5 consecutive failures."""
        return self._consecutive_failures >= 5
