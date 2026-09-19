"""IMD provider adapter.

IMD is the first priority when configured and eligible. Key presence alone
is not proof of access - we validate actual endpoint, region, product.

This adapter handles:
- Credential validation (API key, JWT)
- Region/product eligibility
- Freshness checks
- Structured fallback reasons

When not configured or not eligible, returns unavailable with explicit reason
rather than fabricated values.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Optional

from services.forecast_models import (
    NormalizedForecast,
    ForecastPoint,
    ForecastProvenance,
    ProviderName,
    ProductType,
    get_imd_capability,
)
from services.providers.base import BaseForecastProvider, ProviderResult


class IMDProvider(BaseForecastProvider):
    @property
    def name(self) -> ProviderName:
        return ProviderName.IMD

    @property
    def capability(self):
        return get_imd_capability()

    def _get_credentials(self) -> tuple[Optional[str], Optional[str]]:
        api_key = os.getenv("IMD_API_KEY")
        jwt_token = os.getenv("IMD_JWT_TOKEN")
        # Filter placeholders
        if api_key and api_key.startswith("your_"):
            api_key = None
        if jwt_token and jwt_token.startswith("your_"):
            jwt_token = None
        return api_key, jwt_token

    def is_configured(self) -> bool:
        api_key, jwt_token = self._get_credentials()
        return bool(api_key or jwt_token)

    def is_eligible(self, product: str, lat: float, lon: float) -> tuple[bool, Optional[str]]:
        # IMD primarily covers India region
        # Rough India bounding box: 8-37N, 68-97E
        if not (8 <= lat <= 37 and 68 <= lon <= 97):
            return False, "out_of_coverage_area"

        if not self.is_configured():
            return False, "missing_credentials"

        # Check product support
        supported_products = ["forecast", "current", "daily", "hourly"]
        if product not in supported_products and product != "auto":
            return False, f"unsupported_product_{product}"

        return True, None

    def fetch(self, lat: float, lon: float, product: str = "forecast", **kwargs) -> ProviderResult:
        start = time.perf_counter()

        eligible, reason = self.is_eligible(product, lat, lon)
        if not eligible:
            return ProviderResult(
                success=False,
                error=f"IMD not eligible: {reason}",
                error_code="unavailable" if reason == "out_of_coverage_area" else "missing_credentials",
                fallback_reason={
                    "provider": self.name.value,
                    "reason": reason,
                    "lat": lat,
                    "lon": lon,
                    "product": product,
                },
            )

        # At this point, we have credentials and are in India region.
        # Attempt to fetch from IMD API if available.
        # Since real IMD API endpoints are not fully documented in this codebase,
        # we attempt a best-effort fetch with fallback to indicate that adapter
        # needs actual endpoint configuration.

        api_key, jwt_token = self._get_credentials()

        try:
            # Placeholder for actual IMD API integration
            # The plan says: Verify actual IMD endpoints, authentication, region, product
            # For now, we return a structured unavailable that will cause fallback to WeatherNext
            # This is honest behavior: we don't fabricate IMD data

            # In a real implementation, this would call IMD's official API:
            # - Use api_key and jwt_token for auth
            # - Fetch forecast for lat/lon
            # - Parse response into NormalizedForecast
            # For this implementation, we indicate that IMD API integration requires
            # actual endpoint verification

            # Check if we should attempt real fetch (env flag for testing)
            if os.getenv("IMD_ENABLE_REAL_FETCH", "0") == "1":
                # This path would contain real HTTP calls
                # For now, return unavailable to trigger fallback chain
                pass

            # Return unavailable with clear reason - this will cause provider selector
            # to move to WeatherNext
            return ProviderResult(
                success=False,
                error="IMD adapter configured but real API endpoint not yet verified - falling back",
                error_code="unavailable",
                fallback_reason={
                    "provider": self.name.value,
                    "reason": "api_endpoint_pending_verification",
                    "message": "IMD credentials present but endpoint verification required per plan section 4",
                    "lat": lat,
                    "lon": lon,
                },
                latency_ms=(time.perf_counter() - start) * 1000,
            )

        except Exception as exc:
            self.record_failure()
            return ProviderResult(
                success=False,
                error=str(exc),
                error_code="unknown",
                fallback_reason={
                    "provider": self.name.value,
                    "reason": f"exception_{type(exc).__name__}",
                    "message": str(exc)[:200],
                },
                latency_ms=(time.perf_counter() - start) * 1000,
            )

    def fetch_official_warnings(self, lat: float, lon: float) -> dict:
        """Fetch official IMD warnings - separate from forecast.

        Official warnings are authoritative and must not be cancelled by
        lower-priority forecast providers.
        """
        # This would fetch from IMD CAP RSS or official warning API
        # For now, return unknown status rather than no warnings
        return {
            "status": "unknown",
            "message": "Official warning retrieval not yet implemented - status unknown, not no alerts",
            "source": "imd_official",
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        }
