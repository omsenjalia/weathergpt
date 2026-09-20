"""Shared forecast provider with IMD -> WeatherNext -> AccuWeather -> Open-Meteo selection.

Implements required default order and selection rules from plan section 4.

Rules:
1. Configured IMD key necessary but not sufficient; verify actual endpoints
2. For source=auto, select highest-priority fresh eligible source for product
3. Search for prior complete runs within freshness budget; stale high-priority must not outrank fresh lower-priority
4. Official IMD warnings independent channel
5. Explicit researcher/source queries bypass automatic substitution
6. Bounded timeout, retry/backoff, circuit breaker, shared cache
7. Return requested_source, selected_source, selection_policy_version, provenance, fallback_reasons
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from services.config import get_config
from services.forecast_models import (
    NormalizedForecast,
    ProviderName,
    SELECTION_POLICY_VERSION,
    ForecastProvenance,
    FreshnessStatus,
    ProductType,
)
from services.providers.base import ProviderResult
from services.providers.imd import IMDProvider
from services.providers.weathernext import WeatherNextProvider
from services.providers.accuweather import AccuWeatherProvider
from services.providers.open_meteo import OpenMeteoProvider


@dataclass
class SelectionResult:
    forecast: Optional[NormalizedForecast]
    selected_source: ProviderName
    requested_source: str
    fallback_reasons: list[dict]
    latency_ms: float
    tried_providers: list[str]
    is_stale: bool = False
    error: Optional[str] = None


class ForecastService:
    """Implements ordered provider selection with freshness and capability checks."""

    def __init__(self):
        self.providers = {
            ProviderName.IMD: IMDProvider(),
            ProviderName.WEATHERNEXT: WeatherNextProvider(),
            ProviderName.ACCUWEATHER: AccuWeatherProvider(),
            ProviderName.OPEN_METEO: OpenMeteoProvider(),
        }
        self.policy_version = SELECTION_POLICY_VERSION

    def _get_ordered_providers(self, requested_source: str = "auto") -> list[ProviderName]:
        """Get provider order based on config and requested source."""
        config = get_config()
        priority = config.provider_priority

        # Map string names to enum
        mapping = {
            "imd": ProviderName.IMD,
            "weathernext": ProviderName.WEATHERNEXT,
            "accuweather": ProviderName.ACCUWEATHER,
            "open_meteo": ProviderName.OPEN_METEO,
            "open-meteo": ProviderName.OPEN_METEO,
        }

        if requested_source != "auto":
            # Explicit source pin - return only that provider
            # This is for researcher mode: source=weathernext must return weathernext or explicit failure
            normalized = requested_source.lower().replace("-", "_")
            if normalized in mapping:
                return [mapping[normalized]]
            # Unknown source
            return []

        # Auto mode: use configured priority order
        ordered = []
        for name in priority:
            # name is like "imd", "weathernext", etc.
            if name in mapping:
                ordered.append(mapping[name])

        # Ensure we have all 4 in case config is partial
        for prov in [ProviderName.IMD, ProviderName.WEATHERNEXT, ProviderName.ACCUWEATHER, ProviderName.OPEN_METEO]:
            if prov not in ordered:
                ordered.append(prov)

        return ordered

    def select_forecast(
        self,
        lat: float,
        lon: float,
        product: str = "forecast",
        requested_source: str = "auto",
        mode: str = "everyone",
        forecast_days: int = 7,
        allow_stale: bool = False,
        **kwargs,
    ) -> SelectionResult:
        """Select forecast using ordered provider chain.

        Implements:
        - Fresh eligible source selection
        - Stale high-priority must not outrank fresh lower-priority
        - Explicit source pins return that data or precise unavailable
        - Structured fallback reasons
        """
        start = time.perf_counter()
        fallback_reasons: list[dict] = []
        tried_providers: list[str] = []

        ordered = self._get_ordered_providers(requested_source)

        if not ordered and requested_source != "auto":
            # Explicit source requested but unknown
            return SelectionResult(
                forecast=None,
                selected_source=ProviderName.UNAVAILABLE,
                requested_source=requested_source,
                fallback_reasons=[{"provider": requested_source, "reason": "unknown_provider"}],
                latency_ms=(time.perf_counter() - start) * 1000,
                tried_providers=[],
                error=f"Unknown provider: {requested_source}",
            )

        # For auto mode, we need to evaluate freshness
        # Strategy: try each provider in order, but track if we have a fresh result
        # from lower priority that should outrank stale high-priority

        fresh_candidates: list[tuple[ProviderResult, ProviderName]] = []
        stale_candidates: list[tuple[ProviderResult, ProviderName]] = []

        for provider_name in ordered:
            provider = self.providers.get(provider_name)
            if not provider:
                continue

            tried_providers.append(provider_name.value)

            # Circuit breaker check
            if provider.should_circuit_break():
                fallback_reasons.append({
                    "provider": provider_name.value,
                    "reason": "circuit_breaker_open",
                    "consecutive_failures": provider._consecutive_failures,
                })
                continue

            # Eligibility check
            eligible, reason = provider.is_eligible(product, lat, lon)
            if not eligible:
                fallback_reasons.append({
                    "provider": provider_name.value,
                    "reason": reason,
                    "product": product,
                })
                continue

            # Attempt fetch
            result = provider.fetch(
                lat, lon,
                product=product,
                requested_source=requested_source,
                mode=mode,
                forecast_days=forecast_days,
                allow_stale=allow_stale,
                **kwargs,
            )

            if result.success and result.forecast:
                if result.fallback_reason:
                    fallback_reasons.append(result.fallback_reason)
                # Check freshness. Prefer the status the provider stamped on the
                # forecast: WeatherNext classifies it on the same (injectable)
                # clock that selected the run, so run selection and the gate
                # can never disagree. Wall-clock recompute stays as the
                # fallback for providers that do not stamp one.
                init_time = result.forecast.provenance.init_time_utc
                stored = result.forecast.provenance.freshness_status
                freshness = (
                    stored
                    if stored and stored != FreshnessStatus.UNKNOWN
                    else provider.get_freshness_status(init_time)
                )

                if freshness.value == "fresh":
                    fresh_candidates.append((result, provider_name))
                    # For auto mode, first fresh candidate wins (highest priority fresh)
                    # So we can return immediately
                    if requested_source == "auto":
                        latency = (time.perf_counter() - start) * 1000
                        return SelectionResult(
                            forecast=result.forecast,
                            selected_source=provider_name,
                            requested_source=requested_source,
                            fallback_reasons=fallback_reasons,
                            latency_ms=latency,
                            tried_providers=tried_providers,
                            is_stale=False,
                        )
                elif freshness.value == "stale":
                    if allow_stale:
                        stale_candidates.append((result, provider_name))
                    fallback_reasons.append({
                        "provider": provider_name.value,
                        "reason": "stale_data",
                        "init_time": init_time.isoformat() if init_time else None,
                        "freshness": freshness.value,
                    })
                else:
                    fallback_reasons.append({
                        "provider": provider_name.value,
                        "reason": f"expired_{freshness.value}",
                        "init_time": init_time.isoformat() if init_time else None,
                    })
            else:
                # Failure
                fallback_reasons.append(
                    result.fallback_reason or {
                        "provider": provider_name.value,
                        "reason": result.error_code,
                        "error": result.error,
                    }
                )

        # If we have fresh candidates (for explicit source mode, we collected all)
        if fresh_candidates:
            # Return highest priority fresh (first in ordered list)
            # fresh_candidates is already in priority order because we iterated in order
            result, provider_name = fresh_candidates[0]
            latency = (time.perf_counter() - start) * 1000
            return SelectionResult(
                forecast=result.forecast,
                selected_source=provider_name,
                requested_source=requested_source,
                fallback_reasons=fallback_reasons,
                latency_ms=latency,
                tried_providers=tried_providers,
                is_stale=False,
            )

        # No fresh, check stale if allowed
        if allow_stale and stale_candidates:
            result, provider_name = stale_candidates[0]
            latency = (time.perf_counter() - start) * 1000
            return SelectionResult(
                forecast=result.forecast,
                selected_source=provider_name,
                requested_source=requested_source,
                fallback_reasons=fallback_reasons,
                latency_ms=latency,
                tried_providers=tried_providers,
                is_stale=True,
            )

        # No provider succeeded
        latency = (time.perf_counter() - start) * 1000

        # For explicit source pins, return explicit failure, not fallback to another provider
        if requested_source != "auto":
            return SelectionResult(
                forecast=None,
                selected_source=ProviderName.UNAVAILABLE,
                requested_source=requested_source,
                fallback_reasons=fallback_reasons,
                latency_ms=latency,
                tried_providers=tried_providers,
                error=f"Requested source {requested_source} unavailable: {fallback_reasons[-1]['reason'] if fallback_reasons else 'unknown'}",
            )

        # Auto mode with no fresh providers
        return SelectionResult(
            forecast=None,
            selected_source=ProviderName.UNAVAILABLE,
            requested_source=requested_source,
            fallback_reasons=fallback_reasons,
            latency_ms=latency,
            tried_providers=tried_providers,
            error="No eligible fresh forecast provider available",
        )

    def get_current_with_fallback_chain(
        self,
        lat: float,
        lon: float,
        mode: str = "everyone",
    ) -> SelectionResult:
        """Get current conditions with full fallback chain.

        Note: WeatherNext forecasts cannot stand in for actual observations.
        For current conditions that require observations, skip WeatherNext.
        """
        # For current conditions that are estimates, we can use forecast providers
        # But for actual observations, WeatherNext is not eligible
        # Here we treat current as estimate (forecast near now)
        return self.select_forecast(lat, lon, product="current", mode=mode, requested_source="auto")

    def get_official_warnings(self, lat: float, lon: float) -> dict:
        """Get official warnings independent of forecast provider.

        Official IMD warnings are independent authoritative channel.
        Failure to retrieve warnings means unknown status, not no alerts.
        """
        # Try IMD warnings first
        imd_provider = self.providers.get(ProviderName.IMD)
        if imd_provider and isinstance(imd_provider, IMDProvider):
            try:
                warnings = imd_provider.fetch_official_warnings(lat, lon)
                return warnings
            except Exception as exc:
                return {
                    "status": "unknown",
                    "message": f"Failed to retrieve official warnings: {type(exc).__name__}",
                    "source": "imd_official",
                    "error": str(exc)[:200],
                }

        return {
            "status": "unknown",
            "message": "Official warning source not configured",
            "source": "unknown",
        }


# Global singleton
_forecast_service: Optional[ForecastService] = None

def get_forecast_service() -> ForecastService:
    global _forecast_service
    if _forecast_service is None:
        _forecast_service = ForecastService()
    return _forecast_service
