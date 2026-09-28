"""WeatherNext provider (Google DeepMind ensemble via BigQuery)."""

from __future__ import annotations

import dataclasses
import math
import time
from datetime import datetime, timedelta, timezone

from weathergpt.config import normalize_wn_model, settings
from weathergpt.runtime import make_cache
from weathergpt.weather.models import DayPoint, Forecast, HourPoint, Provenance, ProviderResult
from weathergpt.weather.providers.base import Provider
from weathergpt.weathernext import bigquery
from weathergpt.weathernext.auth import CredentialsUnavailable
from weathergpt.weathernext.normalize import normalize

_cache = make_cache("weathernext", 256)


class WeatherNextProvider(Provider):
    name = "weathernext"

    def availability(self, lat, lon):
        cfg = settings().weathernext
        if not cfg.enabled:
            return False, "disabled", "WEATHERNEXT_ENABLED is not 1"
        if cfg.mock_data:
            return True, None, None
        problems = cfg.problems()
        if problems:
            return False, "not_configured", "; ".join(problems)
        if not cfg.credential_sources() and not _adc_possible():
            return False, "not_configured", "No Google credentials configured"
        return True, None, None

    def fetch(self, lat, lon, *, forecast_days, **options) -> ProviderResult:
        started = time.perf_counter()
        cfg = settings().weathernext
        try:
            model = normalize_wn_model(options.get("model"))
        except ValueError as exc:
            return ProviderResult(False, reason="unsupported_model", message=str(exc))
        if cfg.mock_data:
            return ProviderResult(True, forecast=mock_forecast(lat, lon, forecast_days, model))

        run_id = options.get("run_id") or None
        horizon = min(forecast_days * 24 + 24, cfg.max_horizon_hours)
        key = f"{model}:{round(lat, 1)}:{round(lon, 1)}:{horizon}:{cfg.column_profile}"
        if not run_id:
            hit = _cache.get(key)
            if hit is not None:
                return ProviderResult(True, forecast=_restamp(hit), latency_ms=(time.perf_counter() - started) * 1000)
        try:
            raw = bigquery.adapter().fetch_point(lat, lon, horizon_hours=horizon, model=model, run_id=run_id)
            forecast = normalize(raw, lat=lat, lon=lon, forecast_days=forecast_days,
                                 freshness_hours=cfg.freshness_hours, now=bigquery.adapter().now())
        except CredentialsUnavailable as exc:
            return ProviderResult(False, reason=exc.code, message=str(exc), extra={"credential_attempts": exc.attempts},
                                  latency_ms=(time.perf_counter() - started) * 1000)
        except bigquery.WeatherNextQueryError as exc:
            extra = {k: v for k, v in exc.details.items() if k in ("required_bytes", "attempted_runs")}
            extra.update(surface="bigquery", model=model)
            return ProviderResult(False, reason=exc.code, message=str(exc), extra=extra,
                                  transient=exc.code not in bigquery.NON_TRANSIENT,
                                  latency_ms=(time.perf_counter() - started) * 1000)
        except Exception as exc:
            return ProviderResult(False, reason=f"exception_{type(exc).__name__}", message=str(exc)[:200], transient=True,
                                  latency_ms=(time.perf_counter() - started) * 1000)
        if not run_id:
            _cache.set(key, forecast, cfg.cache_ttl_seconds)
        return ProviderResult(True, forecast=forecast, latency_ms=(time.perf_counter() - started) * 1000)


def _adc_possible() -> bool:
    import os
    return not (os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"))


def _restamp(cached: Forecast) -> Forecast:
    """Cached forecasts are shared: copy, re-pick 'current' and mark the cache hit."""
    now = datetime.now(timezone.utc)
    prov = dataclasses.replace(cached.provenance,
                               query_diagnostics={**(cached.provenance.query_diagnostics or {}), "served_from_cache": True})
    current = min(cached.hourly, key=lambda p: abs((p.time_utc - now).total_seconds())) if cached.hourly else None
    return dataclasses.replace(cached, provenance=prov, current=dataclasses.replace(current) if current else None,
                               hourly=[dataclasses.replace(p) for p in cached.hourly],
                               daily=[dataclasses.replace(d, field_sources=dict(d.field_sources)) for d in cached.daily],
                               location=dict(cached.location), field_sources={})


def mock_forecast(lat: float, lon: float, forecast_days: int, model: str) -> Forecast:
    """WEATHERNEXT_MOCK_DATA=1: deterministic synthetic data, labelled as such (offline dev only)."""
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    base = 25.0 + (lat % 10) - 5
    hourly = []
    for i in range(24 * (forecast_days + 1)):
        t = now + timedelta(hours=i)
        hourly.append(HourPoint(time_utc=t, temperature_c=round(base + 5 * math.sin(i / 24 * 2 * math.pi), 1),
                                humidity_percent=60.0, wind_speed_kmh=10.0, precipitation_mm=0.0,
                                precipitation_probability=10.0, weather_code=2, condition="Partly cloudy",
                                is_ensemble_mean=True))
    daily = [DayPoint(date=(now + timedelta(days=d)).date().isoformat(), high_c=round(base + 5, 1),
                      low_c=round(base - 5, 1), high_p90_c=round(base + 6.5, 1), low_p10_c=round(base - 6.5, 1),
                      rain_probability=10.0, precipitation_mm=0.0, weather_code=2, condition="Partly cloudy",
                      statistic="ensemble_mean", source="weathernext") for d in range(forecast_days)]
    model_id = "weathernext_2_0_0_mock" if model == "weathernext_2" else "weathernext_3_0_0_mock"
    return Forecast(
        location={"lat": lat, "lon": lon, "timezone": "UTC", "utc_offset_seconds": 0, "timezone_source": "mock"},
        provenance=Provenance(source="weathernext", model=model_id, run_id=f"{model_id}_{now:%Y%m%d%H}",
                              init_time_utc=now - timedelta(hours=7), freshness_status="fresh", is_ensemble=True,
                              expected_member_count=64, sources=["weathernext_mock"], notes=["synthetic mock data"]),
        current=hourly[0], current_kind="model", hourly=hourly, daily=daily,
        ensemble={"members": 64, "series": {"temperature_2m": {"units": "C", "statistics": ["mean", "p10", "p90"],
                  "values": [{"time_utc": p.time_utc.isoformat(), "mean": p.temperature_c,
                              "p10": p.temperature_c - 1.5, "p90": p.temperature_c + 1.5} for p in hourly]}}},
    )
