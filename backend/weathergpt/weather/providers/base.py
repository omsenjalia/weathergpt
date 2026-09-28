"""Provider contract and circuit breaker."""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from typing import Optional

from weathergpt.weather.models import ProviderResult

# Reasons meaning "this provider does not apply here / was not set up" — skipping
# it is the normal path, not a degradation the user should be warned about.
NOT_APPLICABLE_REASONS = frozenset({
    "not_configured", "disabled", "out_of_coverage", "no_station_nearby",
    "missing_credentials", "weathernext_disabled",
})


class CircuitBreaker:
    """Opens after ``threshold`` consecutive transient failures; half-opens after ``cooldown``."""

    def __init__(self, threshold: int = 5, cooldown_seconds: float = 120.0):
        self.threshold = threshold
        self.cooldown_seconds = cooldown_seconds
        self.failures = 0
        self.opened_at: Optional[float] = None
        self._lock = threading.Lock()

    def allow(self) -> bool:
        with self._lock:
            if self.opened_at is None:
                return True
            if time.time() - self.opened_at >= self.cooldown_seconds:
                self.opened_at = None          # half-open: let one attempt through
                self.failures = self.threshold - 1
                return True
            return False

    def record(self, ok: bool) -> None:
        with self._lock:
            if ok:
                self.failures = 0
                self.opened_at = None
                return
            self.failures += 1
            if self.failures >= self.threshold and self.opened_at is None:
                self.opened_at = time.time()

    @property
    def is_open(self) -> bool:
        return self.opened_at is not None and time.time() - self.opened_at < self.cooldown_seconds

    def to_dict(self) -> dict:
        return {"consecutive_failures": self.failures, "open": self.is_open,
                "retry_in_seconds": round(max(0.0, self.cooldown_seconds - (time.time() - self.opened_at)), 1)
                if self.is_open else 0}


class Provider(ABC):
    name: str = ""

    def __init__(self) -> None:
        self.breaker = CircuitBreaker()

    @abstractmethod
    def availability(self, lat: float, lon: float) -> tuple[bool, Optional[str], Optional[str]]:
        """(eligible, reason, message) without network I/O."""

    @abstractmethod
    def fetch(self, lat: float, lon: float, *, forecast_days: int, **options) -> ProviderResult:
        """Fetch and normalize. Must never raise."""

    def health(self, lat: float = 23.02, lon: float = 72.57) -> dict:
        eligible, reason, message = self.availability(lat, lon)
        return {"eligible_for_sample": eligible, "reason": reason, "message": message,
                "circuit": self.breaker.to_dict()}
