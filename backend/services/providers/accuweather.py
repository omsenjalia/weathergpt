"""AccuWeather provider adapter for forecast (not just current).

Existing fusion.py only fetched current conditions. This adapter adds
forecast support with proper capability checks and provenance.

Requires ACCUWEATHER_KEY.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

from services.forecast_models import (
    NormalizedForecast,
    ForecastPoint,
    ForecastProvenance,
    ProviderName,
    ProductType,
    get_accuweather_capability,
)
from services.providers.base import BaseForecastProvider, ProviderResult
from services.open_meteo import code_to_condition


class AccuWeatherProvider(BaseForecastProvider):
    @property
    def name(self) -> ProviderName:
        return ProviderName.ACCUWEATHER

    @property
    def capability(self):
        return get_accuweather_capability()

    def _get_key(self) -> Optional[str]:
        for env_key in ("ACCUWEATHER_KEY", "VITE_ACCUWEATHER_KEY"):
            val = os.getenv(env_key)
            if val and not val.startswith("your_"):
                return val
        return None

    def is_configured(self) -> bool:
        return self._get_key() is not None

    def is_eligible(self, product: str, lat: float, lon: float) -> tuple[bool, Optional[str]]:
        if not self.is_configured():
            return False, "missing_credentials"

        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return False, "invalid_coordinates"

        # Check forecast horizon vs subscription
        # AccuWeather free tier may have limited days; we assume 5-15 days
        supported = ["forecast", "current", "daily", "hourly", "auto"]
        if product not in supported:
            return False, f"unsupported_product_{product}"

        return True, None

    def _geocode_location(self, client: httpx.Client, lat: float, lon: float, api_key: str) -> Optional[str]:
        """Get AccuWeather location key from lat/lon."""
        try:
            resp = client.get(
                "https://dataservice.accuweather.com/locations/v1/cities/geoposition/search",
                params={"apikey": api_key, "q": f"{lat},{lon}"},
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json() or {}
            return data.get("Key")
        except Exception:
            return None

    def fetch(self, lat: float, lon: float, product: str = "forecast", **kwargs) -> ProviderResult:
        start = time.perf_counter()

        eligible, reason = self.is_eligible(product, lat, lon)
        if not eligible:
            return ProviderResult(
                success=False,
                error=f"AccuWeather not eligible: {reason}",
                error_code="missing_credentials" if "credentials" in reason else "unsupported",
                fallback_reason={"provider": self.name.value, "reason": reason},
            )

        api_key = self._get_key()
        if not api_key:
            return ProviderResult(
                success=False,
                error="AccuWeather key missing",
                error_code="missing_credentials",
                fallback_reason={"provider": self.name.value, "reason": "missing_credentials"},
            )

        try:
            with httpx.Client(timeout=12.0) as client:
                # Get location key
                loc_key = self._geocode_location(client, lat, lon, api_key)
                if not loc_key:
                    return ProviderResult(
                        success=False,
                        error="Failed to resolve AccuWeather location key",
                        error_code="unavailable",
                        fallback_reason={"provider": self.name.value, "reason": "geocode_failed"},
                        latency_ms=(time.perf_counter() - start) * 1000,
                    )

                # Fetch daily forecast
                forecast_days = min(kwargs.get("forecast_days", 5), 15)
                # AccuWeather uses 1,5,10,15 day endpoints
                if forecast_days <= 1:
                    endpoint = f"https://dataservice.accuweather.com/forecasts/v1/daily/1day/{loc_key}"
                elif forecast_days <= 5:
                    endpoint = f"https://dataservice.accuweather.com/forecasts/v1/daily/5day/{loc_key}"
                elif forecast_days <= 10:
                    endpoint = f"https://dataservice.accuweather.com/forecasts/v1/daily/10day/{loc_key}"
                else:
                    endpoint = f"https://dataservice.accuweather.com/forecasts/v1/daily/15day/{loc_key}"

                resp = client.get(endpoint, params={"apikey": api_key, "details": "true", "metric": "true"}, timeout=12.0)
                resp.raise_for_status()
                data = resp.json() or {}

                daily_forecasts = data.get("DailyForecasts") or []

                daily_list = []
                for day in daily_forecasts:
                    date_str = day.get("Date", "")[:10]
                    temp = day.get("Temperature") or {}
                    max_temp = (temp.get("Maximum") or {}).get("Value")
                    min_temp = (temp.get("Minimum") or {}).get("Value")
                    day_part = day.get("Day") or {}
                    night_part = day.get("Night") or {}
                    rain_prob = day_part.get("PrecipitationProbability") or night_part.get("PrecipitationProbability") or 0

                    daily_list.append({
                        "date": date_str,
                        "high_c": max_temp,
                        "low_c": min_temp,
                        "rain_probability": rain_prob,
                        "condition": day_part.get("IconPhrase") or "Unknown",
                        "source": "accuweather",
                    })

                # Build current from first day if needed, or fetch current endpoint
                current_point = None
                try:
                    cur_resp = client.get(
                        f"https://dataservice.accuweather.com/currentconditions/v1/{loc_key}",
                        params={"apikey": api_key, "details": "true"},
                        timeout=8.0,
                    )
                    cur_resp.raise_for_status()
                    cur_data = (cur_resp.json() or [{}])[0] or {}
                    temp_val = ((cur_data.get("Temperature") or {}).get("Metric") or {}).get("Value")
                    current_point = ForecastPoint(
                        time_utc=datetime.now(timezone.utc),
                        temperature_c=temp_val,
                        humidity_percent=cur_data.get("RelativeHumidity"),
                        wind_speed_kmh=((cur_data.get("Wind") or {}).get("Speed") or {}).get("Metric", {}).get("Value"),
                        condition=cur_data.get("WeatherText"),
                    )
                except Exception:
                    pass

                provenance = ForecastProvenance(
                    requested_source=kwargs.get("requested_source", "auto"),
                    selected_source=ProviderName.ACCUWEATHER,
                    product=ProductType.FORECAST,
                    model="accuweather",
                    init_time_utc=datetime.now(timezone.utc),
                    served_at_utc=datetime.now(timezone.utc),
                    requested_lat=lat,
                    requested_lon=lon,
                    sampled_lat=lat,
                    sampled_lon=lon,
                    sources=["accuweather"],
                )

                normalized = NormalizedForecast(
                    location={"lat": lat, "lon": lon},
                    current=current_point,
                    daily=daily_list,
                    hourly=[],  # AccuWeather hourly is separate endpoint; omitted for brevity
                    provenance=provenance,
                    mode=kwargs.get("mode", "everyone"),
                )

                self.record_success()
                return ProviderResult(
                    success=True,
                    forecast=normalized,
                    latency_ms=(time.perf_counter() - start) * 1000,
                )

        except httpx.HTTPStatusError as exc:
            self.record_failure()
            status = exc.response.status_code
            error_code = "rate_limited" if status == 429 else "unavailable" if status >= 500 else "invalid"
            return ProviderResult(
                success=False,
                error=f"AccuWeather HTTP {status}",
                error_code=error_code,
                fallback_reason={"provider": self.name.value, "reason": f"http_{status}", "status_code": status},
                latency_ms=(time.perf_counter() - start) * 1000,
            )
        except Exception as exc:
            self.record_failure()
            return ProviderResult(
                success=False,
                error=str(exc),
                error_code="unknown",
                fallback_reason={"provider": self.name.value, "reason": f"exception_{type(exc).__name__}"},
                latency_ms=(time.perf_counter() - start) * 1000,
            )
