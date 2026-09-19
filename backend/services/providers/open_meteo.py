"""Open-Meteo provider adapter (fallback, always available).

Wraps existing open_meteo service with new provider interface.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Optional

from services.forecast_models import (
    NormalizedForecast,
    ForecastPoint,
    ForecastProvenance,
    ProviderName,
    ProductType,
    get_open_meteo_capability,
)
from services.providers.base import BaseForecastProvider, ProviderResult
from services.open_meteo import FORECAST_URL, AIR_QUALITY_URL, get_json, UpstreamError, code_to_condition, extract_weather_code


class OpenMeteoProvider(BaseForecastProvider):
    @property
    def name(self) -> ProviderName:
        return ProviderName.OPEN_METEO

    @property
    def capability(self):
        return get_open_meteo_capability()

    def is_configured(self) -> bool:
        return True  # no key required

    def is_eligible(self, product: str, lat: float, lon: float) -> tuple[bool, Optional[str]]:
        # Open-Meteo covers global, but check bounds
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return False, "invalid_coordinates"
        # All products supported
        return True, None

    def fetch(self, lat: float, lon: float, product: str = "forecast", **kwargs) -> ProviderResult:
        start = time.perf_counter()
        try:
            # Check eligibility
            eligible, reason = self.is_eligible(product, lat, lon)
            if not eligible:
                return ProviderResult(
                    success=False,
                    error=f"Not eligible: {reason}",
                    error_code="unsupported",
                    fallback_reason={"provider": self.name.value, "reason": reason, "product": product},
                )

            # Fetch forecast
            mode = kwargs.get("mode", "everyone")
            forecast_days = kwargs.get("forecast_days", 7)
            timezone_str = kwargs.get("timezone", "auto")

            data = get_json(
                FORECAST_URL,
                {
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,wind_direction_10m,surface_pressure,precipitation",
                    "hourly": "temperature_2m,precipitation_probability,precipitation,wind_speed_10m,weather_code,relative_humidity_2m",
                    "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code,rain_sum,sunrise,sunset,uv_index_max,wind_direction_10m_dominant",
                    "forecast_days": forecast_days,
                    "timezone": timezone_str,
                },
                timeout=12.0,
            )

            current = data.get("current") or {}
            daily = data.get("daily") or {}
            hourly = data.get("hourly") or {}

            # Build normalized forecast
            code = extract_weather_code(current, default=0)
            current_point = ForecastPoint(
                time_utc=datetime.now(timezone.utc),
                temperature_c=current.get("temperature_2m"),
                feels_like_c=current.get("apparent_temperature"),
                humidity_percent=current.get("relative_humidity_2m"),
                wind_speed_kmh=current.get("wind_speed_10m"),
                wind_direction_deg=current.get("wind_direction_10m"),
                pressure_hpa=current.get("surface_pressure"),
                pressure_type="surface",
                precipitation_mm=current.get("precipitation"),
                weather_code=code,
                condition=code_to_condition(code),
            )

            hourly_points = []
            h_times = hourly.get("time") or []
            h_temps = hourly.get("temperature_2m") or []
            h_pops = hourly.get("precipitation_probability") or []
            h_precip = hourly.get("precipitation") or []
            h_winds = hourly.get("wind_speed_10m") or []
            h_codes = hourly.get("weather_code") or hourly.get("weathercode") or []
            h_humidity = hourly.get("relative_humidity_2m") or []

            for i in range(min(len(h_times), 168)):  # up to 7 days hourly
                try:
                    t = datetime.fromisoformat(str(h_times[i]).replace("Z", "+00:00"))
                    if t.tzinfo is None:
                        t = t.replace(tzinfo=timezone.utc)
                except Exception:
                    t = datetime.now(timezone.utc)

                hourly_points.append(ForecastPoint(
                    time_utc=t,
                    temperature_c=h_temps[i] if i < len(h_temps) else None,
                    humidity_percent=h_humidity[i] if i < len(h_humidity) else None,
                    wind_speed_kmh=h_winds[i] if i < len(h_winds) else None,
                    precipitation_mm=h_precip[i] if i < len(h_precip) else None,
                    precipitation_probability=h_pops[i] if i < len(h_pops) else None,
                    weather_code=h_codes[i] if i < len(h_codes) else None,
                    condition=code_to_condition(h_codes[i]) if i < len(h_codes) else None,
                ))

            daily_list = []
            d_times = daily.get("time") or []
            d_highs = daily.get("temperature_2m_max") or []
            d_lows = daily.get("temperature_2m_min") or []
            d_pops = daily.get("precipitation_probability_max") or []
            d_codes = daily.get("weather_code") or daily.get("weathercode") or []
            d_rain = daily.get("rain_sum") or []
            d_sunrise = daily.get("sunrise") or []
            d_sunset = daily.get("sunset") or []

            for i in range(min(len(d_times), forecast_days)):
                daily_list.append({
                    "date": d_times[i],
                    "high_c": d_highs[i] if i < len(d_highs) else None,
                    "low_c": d_lows[i] if i < len(d_lows) else None,
                    "rain_probability": d_pops[i] if i < len(d_pops) else None,
                    "rain_mm": d_rain[i] if i < len(d_rain) else None,
                    "condition": code_to_condition(d_codes[i] if i < len(d_codes) else 0),
                    "weather_code": d_codes[i] if i < len(d_codes) else 0,
                    "sunrise": d_sunrise[i] if i < len(d_sunrise) else None,
                    "sunset": d_sunset[i] if i < len(d_sunset) else None,
                })

            # Air quality best-effort
            aqi_data = None
            try:
                aq = get_json(
                    AIR_QUALITY_URL,
                    {"latitude": lat, "longitude": lon, "current": "european_aqi,pm2_5", "timezone": "auto"},
                    timeout=8.0,
                )
                cur_aq = aq.get("current") or {}
                aqi_data = {"european_aqi": cur_aq.get("european_aqi"), "pm2_5": cur_aq.get("pm2_5"), "standard": "european"}
            except Exception:
                pass

            provenance = ForecastProvenance(
                requested_source=kwargs.get("requested_source", "auto"),
                selected_source=ProviderName.OPEN_METEO,
                product=ProductType.FORECAST,
                model="open-meteo-ecmwf",
                init_time_utc=datetime.now(timezone.utc),
                served_at_utc=datetime.now(timezone.utc),
                requested_lat=lat,
                requested_lon=lon,
                sampled_lat=lat,
                sampled_lon=lon,
                resolution_deg=0.1,
                spatial_method="nearest",
                sources=["open-meteo"],
            )

            normalized = NormalizedForecast(
                location={"lat": lat, "lon": lon, "timezone": data.get("timezone", "auto")},
                current=current_point,
                hourly=hourly_points,
                daily=daily_list,
                provenance=provenance,
                air_quality=aqi_data,
                mode=mode,
            )

            self.record_success()
            latency_ms = (time.perf_counter() - start) * 1000
            return ProviderResult(success=True, forecast=normalized, latency_ms=latency_ms)

        except UpstreamError as exc:
            self.record_failure()
            latency_ms = (time.perf_counter() - start) * 1000
            return ProviderResult(
                success=False,
                error=str(exc),
                error_code="timeout" if exc.status_code == 504 else "unavailable",
                fallback_reason={"provider": self.name.value, "reason": str(exc), "status_code": exc.status_code},
                latency_ms=latency_ms,
            )
        except Exception as exc:
            self.record_failure()
            latency_ms = (time.perf_counter() - start) * 1000
            return ProviderResult(
                success=False,
                error=str(exc),
                error_code="unknown",
                fallback_reason={"provider": self.name.value, "reason": str(exc)},
                latency_ms=latency_ms,
            )
