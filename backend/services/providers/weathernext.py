"""WeatherNext provider adapter.

Implements bounded reads from WeatherNext products, with support for:
- BigQuery surface tables (precomputed ensemble statistics)  <- live
- GCS statistics Zarr                                        <- planned
- GCS full ensemble Zarr (member-level)                      <- planned
- Earth Engine (optional)                                    <- planned

When WEATHERNEXT_ENABLED=0, no Google reads are attempted.

Live path (BigQuery):
    fetch() -> services.weathernext_bigquery.WeatherNextBigQueryAdapter
            -> credentials chain SA JSON -> ADC -> OAuth (services.weathernext_auth)
            -> bounded, partition-filtered point query with maximum_bytes_billed
            -> services.weathernext_normalize -> NormalizedForecast

Every failure is returned as a structured ``fallback_reason`` (provider, reason,
surface, table, redacted message) so the provider chain can fall back honestly
and clients can display the real source.

Scientific correctness:
- Coherent run selection (one init_time per payload)
- Native units preserved on the wire, converted once for display
- Explicit unavailable states, never fabricated values
"""

from __future__ import annotations

import dataclasses
import os
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from services.config import get_config
from services.forecast_models import (
    NormalizedForecast,
    ForecastPoint,
    ForecastProvenance,
    ProviderName,
    ProductType,
    FreshnessStatus,
    get_weathernest_capability,
    kelvin_to_celsius,
    meters_to_mm,
    ms_to_kmh,
    pa_to_hpa,
)
from services.providers.base import BaseForecastProvider, ProviderResult
from services.weathernext_auth import validate_credentials, AuthStatus, CredentialsUnavailable

# Query reason codes that are configuration/entitlement problems rather than
# transient faults: they must not trip the circuit breaker, otherwise the
# client would see "circuit_breaker_open" instead of the actionable reason.
_NON_TRANSIENT_CODES = {
    "live_credentials_required",
    "credential_refresh_failed",
    "permission_denied",
    "billing_disabled",
    "unauthenticated",
    "table_not_found",
    "table_not_configured",
    "invalid_table",
    "invalid_columns",
    "invalid_run_id",
    "schema_mismatch",
    "bytes_billed_limit_exceeded",
    "missing_dependency_bigquery",
    "missing_dependency_gcs",
    "no_candidate_run",
    "surface_chain_exhausted",
}

_ERROR_CODE_BY_REASON = {
    "live_credentials_required": "missing_credentials",
    "credential_refresh_failed": "missing_credentials",
    "unauthenticated": "missing_credentials",
    "permission_denied": "not_granted",
    "billing_disabled": "not_granted",
    "quota_exceeded": "rate_limited",
    "query_timeout": "timeout",
    "no_recent_run": "unavailable",
    "run_not_available": "unavailable",
}


def _mock_data_enabled() -> bool:
    """WEATHERNEXT_MOCK_DATA=1 -> synthetic offline data, clearly labelled.

    Dev/test only. When set, the provider must be eligible *without* Google
    credentials - running credential-free is the entire point of the mode -
    and every response is stamped ``weathernext_3_0_0_mock``.
    """
    return os.getenv("WEATHERNEXT_MOCK_DATA", "0") == "1"


class WeatherNextProvider(BaseForecastProvider):
    @property
    def name(self) -> ProviderName:
        return ProviderName.WEATHERNEXT

    @property
    def capability(self):
        return get_weathernest_capability()

    def is_configured(self) -> bool:
        cfg = get_config().weathernext
        if not cfg.enabled:
            return False
        status = validate_credentials(cfg)
        return status.status in (AuthStatus.CONFIGURED, AuthStatus.READY)

    def is_eligible(self, product: str, lat: float, lon: float) -> tuple[bool, Optional[str]]:
        cfg = get_config().weathernext

        if not cfg.enabled:
            return False, "weathernext_disabled"

        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return False, "invalid_coordinates"

        # Check credentials (mock mode is designed to run without them)
        if not _mock_data_enabled():
            cred_status = validate_credentials(cfg)
            if cred_status.status == AuthStatus.DISABLED:
                return False, "weathernext_disabled"
            if cred_status.status in (AuthStatus.MISSING_CREDENTIALS, AuthStatus.INVALID_CONFIG):
                return False, f"credentials_{cred_status.status.value}"

        # Product eligibility: WeatherNext is forecast, not observations
        # Current conditions as observations are not WeatherNext's product
        if product == "current_observation":
            return False, "not_observation_product"

        # All forecast products are eligible when configured
        supported = ["forecast", "hourly", "daily", "ensemble", "profile", "current", "auto"]
        if product not in supported:
            return False, f"unsupported_product_{product}"

        return True, None

    def fetch(self, lat: float, lon: float, product: str = "forecast", **kwargs) -> ProviderResult:
        start = time.perf_counter()
        cfg = get_config().weathernext

        # Offline synthetic data for tests / demos - clearly labelled, never
        # live. This must short-circuit *before* the credential/eligibility
        # checks: the documented WEATHERNEXT_MOCK_DATA=1 offline mode is
        # specifically for running without Google credentials, so gating it
        # behind validate_credentials() made it unreachable.
        if _mock_data_enabled() and cfg.enabled:
            return self._mock_forecast(lat, lon, product, start, **kwargs)

        eligible, reason = self.is_eligible(product, lat, lon)
        if not eligible:
            return ProviderResult(
                success=False,
                error=f"WeatherNext not eligible: {reason}",
                error_code="unavailable" if "disabled" in reason else "missing_credentials",
                fallback_reason={
                    "provider": self.name.value,
                    "reason": reason,
                    "product": product,
                    "lat": lat,
                    "lon": lon,
                },
            )

        # Check for cached data first (shared per grid cell + horizon, run-keyed
        # inside the payload). Explicit run_id pins bypass the cache.
        cache_key = self._cache_key(lat, lon, product, **kwargs)
        if cache_key and not kwargs.get("run_id"):
            try:
                from services.forecast_cache import get_cache
                cached = get_cache().get(cache_key)
                if cached:
                    # Prefer the classification stamped at fetch time (it may
                    # come from the adapter's injectable clock); recompute on
                    # the wall clock only when absent. The 1 h cache TTL bounds
                    # any drift between the two.
                    stored = cached.provenance.freshness_status
                    freshness = (
                        stored
                        if stored and stored != FreshnessStatus.UNKNOWN
                        else self.get_freshness_status(cached.provenance.init_time_utc)
                    )
                    if freshness == FreshnessStatus.FRESH:
                        self.record_success()
                        return ProviderResult(
                            success=True,
                            forecast=self._restamp(cached, kwargs.get("requested_source", "auto"), FreshnessStatus.FRESH),
                            latency_ms=(time.perf_counter() - start) * 1000,
                        )
                    if freshness == FreshnessStatus.STALE and kwargs.get("allow_stale", False):
                        self.record_success()
                        return ProviderResult(
                            success=True,
                            forecast=self._restamp(cached, kwargs.get("requested_source", "auto"), FreshnessStatus.STALE),
                            latency_ms=(time.perf_counter() - start) * 1000,
                            is_stale=True,
                        )
            except Exception:
                # Cache failures are non-fatal
                pass

        # WeatherNext itself has a surface fallback chain.  This is separate
        # from ForecastService's provider fallback: preferred WN3 BigQuery is
        # followed by WN3 statistics Zarr before AccuWeather/Open-Meteo are
        # considered.  WN2 is only queried when explicitly pinned (model=
        # weathernext_2) - it is a different schema, not a drop-in fallback.
        try:
            return self._fetch_surface_chain(lat, lon, product, start, **kwargs)
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

    # ------------------------------------------------------------------
    # WeatherNext surface chain
    # ------------------------------------------------------------------

    def _fetch_surface_chain(self, lat: float, lon: float, product: str, start_time: float, **kwargs) -> ProviderResult:
        requested_model = (kwargs.get("model") or "weathernext_3").lower().replace("-", "_")
        if requested_model in {"weathernext_3", "wn3", "3", "3.0.0", "weathernext_3_0_0"}:
            # No silent cross-model substitution: WN2 tables speak a different
            # schema (ERA5-style leaf names, different table ids), so falling
            # back from WN3 to WN2 used to emit schema_mismatch on every
            # request whenever the newest WN3 partition was not delivered yet.
            # WN2 remains available via an explicit model=weathernext_2 pin.
            chain = [("weathernext_3", "bigquery"), ("weathernext_3", "gcs_statistics")]
        elif requested_model in {"weathernext_2", "wn2", "2", "2.0.0", "weathernext_2_0_0"}:
            chain = [("weathernext_2", "bigquery"), ("weathernext_2", "gcs_statistics")]
        else:
            return ProviderResult(success=False, error=f"Unsupported WeatherNext model: {requested_model}",
                                  error_code="unsupported_model",
                                  fallback_reason={"provider": self.name.value, "reason": "unsupported_model", "model": requested_model},
                                  latency_ms=(time.perf_counter() - start_time) * 1000)

        attempts: list[dict] = []
        for model, surface in chain:
            child_kwargs = {**kwargs, "model": model}
            if surface == "bigquery":
                result = self._fetch_bigquery(lat, lon, product, start_time, **child_kwargs)
            else:
                result = self._fetch_gcs_statistics(lat, lon, product, start_time, **child_kwargs)
            if result.success:
                if result.forecast:
                    result.forecast.provenance.fallback_reasons.extend(attempts)
                if attempts:
                    result.fallback_reason = {
                        "provider": self.name.value,
                        "reason": "surface_fallback",
                        "selected_surface": surface,
                        "selected_model": model,
                        "attempts": attempts,
                    }
                return result
            reason = dict(result.fallback_reason or {})
            reason.setdefault("provider", self.name.value)
            reason.setdefault("model", model)
            reason.setdefault("surface", surface)
            attempts.append(reason)

        if any(attempt.get("reason") not in _NON_TRANSIENT_CODES for attempt in attempts):
            self.record_failure()
        # Keep the first actionable reason at the top level for existing mobile
        # clients (for example live_credentials_required/table_not_found), while
        # retaining every attempted surface for operator diagnostics.
        failure = dict(attempts[0]) if attempts else {
            "provider": self.name.value, "reason": "surface_chain_exhausted", "model": requested_model,
        }
        failure.setdefault("provider", self.name.value)
        failure.setdefault("model", requested_model)
        failure["attempts"] = attempts
        failure["chain_error"] = "surface_chain_exhausted"
        return ProviderResult(
            success=False,
            error="All WeatherNext surfaces unavailable",
            error_code=failure.get("reason", "weathernext_surfaces_unavailable"),
            fallback_reason=failure,
            latency_ms=(time.perf_counter() - start_time) * 1000,
        )

    # ------------------------------------------------------------------
    # BigQuery surface (live)
    # ------------------------------------------------------------------

    def _cache_key(self, lat: float, lon: float, product: str, **kwargs) -> Optional[str]:
        cfg = get_config().weathernext
        model = kwargs.get("model", "weathernext_3")
        try:
            table = cfg.bq.table_for(model)
        except ValueError:
            return None
        if not table:
            return None
        res = 0.05 if "0p05" in table else 0.1
        cell_lat = round(round(lat / res) * res, 3)
        cell_lon = round(round(lon / res) * res, 3)
        horizon = self._horizon_hours(**kwargs)
        table_short = table.rsplit(".", 1)[-1]
        return f"weathernext:{model}:{table_short}:{cfg.bq.column_profile}:{cell_lat}:{cell_lon}:{horizon}"

    def _horizon_hours(self, **kwargs) -> int:
        cfg = get_config().weathernext
        days = kwargs.get("forecast_days") or 7
        try:
            days = int(days)
        except (TypeError, ValueError):
            days = 7
        days = max(1, days)
        # +24 h so the local "today" bucket (which started before now) is
        # complete and the last requested day is not truncated.
        return int(min(days * 24 + 24, cfg.run_policy.max_horizon_hours))

    @staticmethod
    def _restamp(cached: NormalizedForecast, requested_source: str, freshness: FreshnessStatus) -> NormalizedForecast:
        """Return a shallow copy with request-specific provenance (cache entries are shared)."""
        provenance = dataclasses.replace(
            cached.provenance,
            requested_source=requested_source,
            served_at_utc=datetime.now(timezone.utc),
            freshness_status=freshness,
            is_stale=freshness != FreshnessStatus.FRESH,
            query_diagnostics={**(cached.provenance.query_diagnostics or {}), "served_from_cache": True},
        )
        return dataclasses.replace(cached, provenance=provenance)

    def _failure(self, reason: str, message: str, start_time: float, *, table: Optional[str], transient: bool, extra: Optional[dict] = None) -> ProviderResult:
        if transient:
            self.record_failure()
        fallback = {
            "provider": self.name.value,
            "reason": reason,
            "surface": "bigquery",
            "table": table,
            "message": message[:200],
        }
        if extra:
            fallback.update(extra)
        return ProviderResult(
            success=False,
            error=f"WeatherNext BigQuery: {reason}: {message[:200]}",
            error_code=_ERROR_CODE_BY_REASON.get(reason, "unavailable"),
            fallback_reason=fallback,
            latency_ms=(time.perf_counter() - start_time) * 1000,
        )

    def _fetch_bigquery(self, lat: float, lon: float, product: str, start_time: float, **kwargs) -> ProviderResult:
        """Bounded point query against the WeatherNext 3 BigQuery surface table."""
        cfg = get_config().weathernext
        model = kwargs.get("model", "weathernext_3")
        try:
            table = cfg.bq.table_for(model)
        except ValueError:
            table = None

        try:
            from services.weathernext_bigquery import WeatherNextQueryError, get_bigquery_adapter
            from services.weathernext_normalize import normalize_point_forecast
        except ImportError as exc:  # pragma: no cover - only when google libs are absent
            return self._failure("missing_dependency_bigquery", str(exc), start_time, table=table, transient=False)

        requested_source = kwargs.get("requested_source", "auto")
        mode = kwargs.get("mode", "everyone")
        horizon = self._horizon_hours(**kwargs)
        forecast_days = kwargs.get("forecast_days") or 7

        try:
            adapter = get_bigquery_adapter()
            result = adapter.fetch_point_forecast(
                lat, lon, horizon_hours=horizon, run_id=kwargs.get("run_id") or None,
                model=model, high_resolution=bool(kwargs.get("high_resolution", False)),
            )
        except CredentialsUnavailable as exc:
            return self._failure(
                exc.code, str(exc), start_time, table=table, transient=False,
                extra={"credential_attempts": exc.attempts},
            )
        except WeatherNextQueryError as exc:
            extra = {
                k: v for k, v in exc.details.items()
                if k in ("required_bytes", "attempted_runs", "attempts")
            }
            # Keep the byte-limit failure actionable without exposing the full
            # BigQuery request.  This is a hard pre-execution estimate failure,
            # not a transient error: retrying the same query or stepping through
            # older runs cannot make the selected leaf columns cheaper.
            if exc.code == "bytes_billed_limit_exceeded":
                configured_cap = int(cfg.bq.max_bytes_billed)
                required = extra.get("required_bytes")
                extra.update({
                    "configured_max_bytes_billed": configured_cap,
                    "configured_max_gib": round(configured_cap / 1024 ** 3, 3),
                    "required_gib": round(required / 1024 ** 3, 3) if required else None,
                    "retryable": False,
                    "remediation": "Run the uncapped dry-run probe, then raise WEATHERNEXT_BQ_MAX_BYTES_BILLED or choose the minimal column profile.",
                })
            return self._failure(
                exc.code, str(exc), start_time, table=table,
                transient=exc.code not in _NON_TRANSIENT_CODES,
                extra=extra,
            )
        except ImportError as exc:
            return self._failure("missing_dependency_bigquery", str(exc), start_time, table=table, transient=False)
        except Exception as exc:  # defensive: never let the chain crash
            return self._failure(f"exception_{type(exc).__name__}", str(exc), start_time, table=table, transient=True)

        try:
            normalized = normalize_point_forecast(
                result,
                lat=lat,
                lon=lon,
                requested_source=requested_source,
                mode=mode,
                forecast_days=int(forecast_days),
                freshness_hours=cfg.run_policy.freshness_hours,
                # Classify freshness on the same clock that selected the run.
                # Splitting the time source (adapter clock for run selection,
                # wall clock for freshness) made results randomly "stale" and
                # broke the injectable-clock contract the tests rely on.
                now=adapter.now(),
            )
        except Exception as exc:
            return self._failure(f"normalization_failed_{type(exc).__name__}", str(exc), start_time, table=table, transient=True)

        cache_key = self._cache_key(lat, lon, product, **kwargs)
        if cache_key and not kwargs.get("run_id"):
            try:
                from services.forecast_cache import get_cache
                get_cache().set(cache_key, normalized, ttl_seconds=cfg.run_policy.cache_ttl_seconds)
            except Exception:
                pass

        self.record_success()
        return ProviderResult(
            success=True,
            forecast=normalized,
            latency_ms=(time.perf_counter() - start_time) * 1000,
            is_stale=normalized.provenance.is_stale,
        )

    def _fetch_gcs_statistics(self, lat: float, lon: float, product: str, start_time: float, **kwargs) -> ProviderResult:
        """Fetch the WN2/WN3 statistics Zarr and normalize it like BigQuery."""
        model = kwargs.get("model", "weathernext_3")
        cfg = get_config().weathernext
        try:
            from services.weathernext_gcs import WeatherNextGCSQueryError, get_gcs_adapter
            from services.weathernext_normalize import normalize_point_forecast
            raw = get_gcs_adapter().fetch_point_forecast(
                lat, lon, model=model, horizon_hours=self._horizon_hours(**kwargs),
                run_id=kwargs.get("run_id") or None,
            )
            normalized = normalize_point_forecast(
                raw,
                lat=lat,
                lon=lon,
                requested_source=kwargs.get("requested_source", "auto"),
                mode=kwargs.get("mode", "everyone"),
                forecast_days=int(kwargs.get("forecast_days") or 7),
                freshness_hours=cfg.run_policy.freshness_hours,
            )
            self.record_success()
            return ProviderResult(
                success=True,
                forecast=normalized,
                latency_ms=(time.perf_counter() - start_time) * 1000,
            )
        except WeatherNextGCSQueryError as exc:
            return ProviderResult(
                success=False,
                error=str(exc),
                error_code=exc.code,
                fallback_reason={
                    "provider": self.name.value,
                    "reason": exc.code,
                    "surface": "gcs_statistics",
                    "model": model,
                    "bucket": cfg.gcs.root_for(model, statistics=True),
                    "message": str(exc)[:200],
                    **exc.details,
                },
                latency_ms=(time.perf_counter() - start_time) * 1000,
            )
        except ImportError as exc:
            return ProviderResult(
                success=False,
                error=str(exc),
                error_code="missing_dependency_gcs",
                fallback_reason={"provider": self.name.value, "reason": "missing_dependency_gcs", "surface": "gcs_statistics", "model": model},
                latency_ms=(time.perf_counter() - start_time) * 1000,
            )
        except Exception as exc:
            return ProviderResult(
                success=False,
                error=str(exc),
                error_code=f"gcs_{type(exc).__name__}",
                fallback_reason={"provider": self.name.value, "reason": f"gcs_{type(exc).__name__}", "surface": "gcs_statistics", "model": model, "message": str(exc)[:200]},
                latency_ms=(time.perf_counter() - start_time) * 1000,
            )

    def _get_credentials(self):
        """Backward-compatible helper: (CredentialBundle | None, error | None)."""
        from services.weathernext_auth import build_google_credentials
        return build_google_credentials()

    def _mock_forecast(self, lat: float, lon: float, product: str, start_time: float, **kwargs) -> ProviderResult:
        """Generate mock forecast for testing when WEATHERNEXT_MOCK_DATA=1.

        This mock is clearly labeled and only used for offline tests.
        It does NOT fabricate real weather - it's synthetic test data.
        """
        from datetime import datetime, timezone, timedelta
        import math

        # Generate deterministic mock based on lat/lon for reproducibility
        base_temp = 25.0 + (lat % 10) - 5  # pseudo-random but deterministic
        now = datetime.now(timezone.utc)

        hourly = []
        for i in range(24 * 3):  # 3 days
            t = now + timedelta(hours=i)
            # Simple diurnal cycle
            temp = base_temp + 5 * math.sin((i % 24) / 24 * 2 * math.pi)
            hourly.append(ForecastPoint(
                time_utc=t,
                temperature_c=round(temp, 1),
                humidity_percent=60 + (i % 20),
                wind_speed_kmh=10 + (i % 15),
                precipitation_mm=0.1 if i % 10 == 0 else 0.0,
                precipitation_probability=20 if i % 10 == 0 else 5,
                condition="Partly cloudy",
            ))

        daily = []
        for i in range(7):
            daily.append({
                "date": (now + timedelta(days=i)).date().isoformat(),
                "high_c": round(base_temp + 5, 1),
                "low_c": round(base_temp - 5, 1),
                "rain_probability": 20,
                "rain_mm": 1.0,
                "condition": "Partly cloudy",
                "source": "weathernext_mock",
            })

        current = ForecastPoint(
            time_utc=now,
            temperature_c=base_temp,
            humidity_percent=65,
            wind_speed_kmh=12,
            condition="Partly cloudy (mock)",
            precipitation_mm=0.0,
        )

        provenance = ForecastProvenance(
            requested_source=kwargs.get("requested_source", "auto"),
            selected_source=ProviderName.WEATHERNEXT,
            product=ProductType.FORECAST,
            model="weathernext_3_0_0_mock",
            model_version="mock_1.0",
            run_id=f"mock_{now.strftime('%Y%m%d%H')}",
            init_time_utc=now - timedelta(hours=1),
            served_at_utc=now,
            requested_lat=lat,
            requested_lon=lon,
            sampled_lat=lat,
            sampled_lon=lon,
            resolution_deg=0.1,
            spatial_method="nearest",
            sources=["weathernext_mock"],
            expected_member_count=64,
            valid_member_count=64,
            coverage_completeness=1.0,
        )

        normalized = NormalizedForecast(
            location={"lat": lat, "lon": lon},
            current=current,
            hourly=hourly,
            daily=daily,
            provenance=provenance,
            mode=kwargs.get("mode", "everyone"),
            ensemble={
                "members": 64,
                "note": "Mock ensemble data for testing",
                "variables": ["temperature_2m", "total_precipitation_1hr"],
            },
        )

        # Cache it
        try:
            from services.forecast_cache import get_cache
            cache = get_cache()
            cache.set(f"weathernext_{lat:.2f}_{lon:.2f}_{product}", normalized, ttl_seconds=3600)
        except Exception:
            pass

        self.record_success()
        return ProviderResult(
            success=True,
            forecast=normalized,
            latency_ms=(time.perf_counter() - start_time) * 1000,
        )

    def fetch_ensemble(self, lat: float, lon: float, variable: str, **kwargs) -> ProviderResult:
        """Fetch full ensemble for researcher mode (bounded)."""
        # This would fetch all 64 members for a variable
        # Requires explicit authorization and is only for researcher mode
        # For now, delegate to regular fetch with ensemble flag
        kwargs["product"] = "ensemble"
        kwargs["variable"] = variable
        return self.fetch(lat, lon, product="ensemble", **kwargs)

    def fetch_profile(self, lat: float, lon: float, valid_time: datetime, **kwargs) -> ProviderResult:
        """Fetch upper-air profile for researcher mode."""
        kwargs["product"] = "profile"
        kwargs["valid_time"] = valid_time
        return self.fetch(lat, lon, product="profile", **kwargs)
