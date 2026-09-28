"""Provider selection: IMD -> WeatherNext -> Open-Meteo.

- ``auto``: the first provider that returns *fresh* data wins. A stale result is
  remembered and only served if nothing fresher answers (flagged degraded).
- a pinned source (``imd`` / ``weathernext`` / ``open_meteo``) returns that
  provider's data or an explicit unavailable result — it is never silently
  replaced by another provider.
- every skip/failure is reported in ``fallback_reasons``; ``degraded`` is true
  only for real failures, not for providers that simply do not apply
  (not configured, outside India, no IMD station nearby).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from weathergpt.config import PROVIDERS, settings
from weathergpt.weather.models import Forecast
from weathergpt.weather.providers.base import NOT_APPLICABLE_REASONS, Provider
from weathergpt.weather.providers.imd import IMDProvider
from weathergpt.weather.providers.open_meteo import OpenMeteoProvider
from weathergpt.weather.providers.weathernext import WeatherNextProvider

SOURCE_ALIASES = {"open-meteo": "open_meteo", "openmeteo": "open_meteo", "": "auto"}


class InvalidSource(ValueError):
    pass


def normalize_source(value: Optional[str]) -> str:
    s = (value or "auto").strip().lower()
    s = SOURCE_ALIASES.get(s, s)
    if s != "auto" and s not in PROVIDERS:
        raise InvalidSource(f"requested_source must be one of auto|{'|'.join(PROVIDERS)}")
    return s


@dataclass
class Selection:
    requested_source: str
    forecast: Optional[Forecast] = None
    selected_source: str = "unavailable"
    fallback_reasons: list = field(default_factory=list)
    tried_providers: list = field(default_factory=list)
    latency_ms: float = 0.0
    is_stale: bool = False
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.forecast is not None

    @property
    def degraded(self) -> bool:
        if self.is_stale:
            return True
        return any(r.get("reason") not in NOT_APPLICABLE_REASONS for r in self.fallback_reasons)


class ForecastService:
    def __init__(self) -> None:
        self.providers: dict[str, Provider] = {
            "imd": IMDProvider(),
            "weathernext": WeatherNextProvider(),
            "open_meteo": OpenMeteoProvider(),
        }

    def order(self, requested: str) -> list[str]:
        return [requested] if requested != "auto" else list(settings().provider_priority)

    def select(self, lat: float, lon: float, *, requested_source: str = "auto", forecast_days: int = 7,
               model: Optional[str] = None, run_id: Optional[str] = None) -> Selection:
        started = time.perf_counter()
        requested = normalize_source(requested_source)
        pinned = requested != "auto"
        sel = Selection(requested_source=requested)
        stale_candidate: Optional[tuple[str, Forecast]] = None

        for name in self.order(requested):
            provider = self.providers[name]
            sel.tried_providers.append(name)
            eligible, reason, message = provider.availability(lat, lon)
            if not eligible:
                sel.fallback_reasons.append({"provider": name, "reason": reason, "message": message})
                continue
            if not provider.breaker.allow():
                sel.fallback_reasons.append({"provider": name, "reason": "circuit_open",
                                             "message": "Temporarily skipped after repeated failures",
                                             **provider.breaker.to_dict()})
                continue
            result = provider.fetch(lat, lon, forecast_days=forecast_days, model=model, run_id=run_id)
            if not result.ok or result.forecast is None:
                if result.transient:
                    provider.breaker.record(False)
                sel.fallback_reasons.append(result.fallback_reason(name))
                continue
            provider.breaker.record(True)
            freshness = result.forecast.provenance.freshness_status
            if freshness == "expired":
                sel.fallback_reasons.append({"provider": name, "reason": "expired_data",
                                             "issued_at": _iso(result.forecast.provenance.issued_at_utc)})
                continue
            if freshness == "stale" and not pinned:
                sel.fallback_reasons.append({"provider": name, "reason": "stale_data",
                                             "issued_at": _iso(result.forecast.provenance.issued_at_utc)})
                stale_candidate = stale_candidate or (name, result.forecast)
                continue
            sel.forecast, sel.selected_source = result.forecast, name
            sel.is_stale = freshness == "stale"
            break

        if sel.forecast is None and stale_candidate is not None:
            sel.selected_source, sel.forecast = stale_candidate
            sel.is_stale = True
        if sel.forecast is None:
            last = sel.fallback_reasons[-1] if sel.fallback_reasons else {}
            sel.error = (f"Requested source {requested} unavailable: {last.get('reason', 'unknown')}" if pinned
                         else "No forecast provider available")
        sel.latency_ms = round((time.perf_counter() - started) * 1000, 1)
        return sel

    def health(self) -> dict:
        return {name: {"in_priority": name in settings().provider_priority, **p.health()}
                for name, p in self.providers.items()}


def _iso(dt) -> Optional[str]:
    return dt.isoformat() if dt else None


_service: Optional[ForecastService] = None


def service() -> ForecastService:
    global _service
    if _service is None:
        _service = ForecastService()
    return _service


def reset_service() -> None:
    global _service
    _service = None
