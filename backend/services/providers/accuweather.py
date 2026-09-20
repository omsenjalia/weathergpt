"""AccuWeather provider adapter for forecast (not just current).

Existing fusion.py only fetched current conditions. This adapter adds
forecast support with proper capability checks and provenance.

Requires ACCUWEATHER_KEY.

AccuWeather portal migration (9 Sep 2025) — READ THIS BEFORE DEBUGGING 401s
---------------------------------------------------------------------------
AccuWeather retired the legacy developer portal and every key issued by it.
The self-serve APIs now sit behind a new gateway (developer.accuweather.com,
Zuplo on Akamai) and the documented contract changed:

  * Auth: ``Authorization: Bearer <API_KEY>`` on **every** request. The old
    ``?apikey=`` query parameter is a legacy-portal artefact; new-portal keys
    are rejected with ``401 {"Code": "Unauthorized", "Message": "API
    authorization failed"}``. We send the bearer header by default and only
    fall back to the query parameter when ``ACCUWEATHER_AUTH_MODE=query``
    (or when auto-detect proves the key is a legacy one).
  * HTTPS only — plain HTTP is upgraded or refused.
  * ``Accept-Encoding: gzip,deflate`` is recommended by AccuWeather (~83 %
    smaller payloads).
  * Error bodies are now RFC-7807-ish: ``{"type", "title", "status", "Code",
    "Message", "Reference"}``. We surface ``Code``/``Message`` instead of
    swallowing them, so a dead key reads as a dead key and not as a
    "geocode failure".
  * There is no free tier any more: a 14-day / 500-calls-per-day trial, then
    the paid Starter ($2/mo) plan, which is capped at **5-day daily** and
    **12-hour hourly** forecasts. Asking for ``daily/10day`` or ``daily/15day``
    on that plan returns ``403 Forbidden`` ("Check your subscription limits"),
    so the horizon is clamped via ``ACCUWEATHER_MAX_FORECAST_DAYS`` (default 5)
    and a 403 on a wide horizon transparently retries the 5-day endpoint.

Each forecast still costs 2 calls (geoposition + daily forecast, plus 1 more
for current conditions), which is brutal against a 15,000-calls/month plan, so
resolved location keys are cached for ``ACCUWEATHER_LOCATION_KEY_TTL_HOURS``
(default 720 h = 30 days; location keys are stable).
"""

from __future__ import annotations

import os
import time
from dataclasses import replace
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Optional

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

BASE_URL = "https://dataservice.accuweather.com"
GEOPOSITION_URL = f"{BASE_URL}/locations/v1/cities/geoposition/search"
CURRENT_CONDITIONS_URL = f"{BASE_URL}/currentconditions/v1"
DAILY_FORECAST_URL = f"{BASE_URL}/forecasts/v1/daily"

# AccuWeather only sells 1/5/10/15-day daily endpoints; a requested horizon is
# rounded up to the next available product.
DAILY_HORIZONS = (1, 5, 10, 15)

# Starter ($2/mo) and Standard ($25/mo) are capped at 5-day daily forecasts;
# 10-day needs Prime, 15-day needs Elite. Default to what the cheapest plan
# actually serves so we do not burn calls on guaranteed 403s.
DEFAULT_MAX_FORECAST_DAYS = 5

SUPPORTED_PRODUCTS = ("forecast", "current", "daily", "hourly", "auto")


def _env_float(name: str, default: float) -> float:
    try:
        raw = os.getenv(name)
        if raw is None or not str(raw).strip():
            return default
        return float(raw)
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        raw = os.getenv(name)
        if raw is None or not str(raw).strip():
            return default
        return int(float(raw))
    except (TypeError, ValueError):
        return default


def _num(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _metric(block: Any, *path: str) -> Optional[float]:
    """Read a metric value out of an AccuWeather unit envelope.

    AccuWeather returns both unit systems side by side (``{"Metric": {"Value":
    31.7, "Unit": "C"}, "Imperial": {...}}``) whenever ``details=true`` is
    requested, independently of the ``metric`` flag. Reading ``.Metric.Value``
    explicitly keeps normalization honest even if the account's default unit
    system is Imperial.
    """
    node: Any = block
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    if not isinstance(node, dict):
        return None
    return _num((node.get("Metric") or {}).get("Value"))


def _error_detail(response: httpx.Response) -> dict[str, Any]:
    """Extract the gateway's own error Code/Message without ever raising."""
    detail: dict[str, Any] = {}
    try:
        body = response.json()
    except Exception:
        return detail
    if isinstance(body, dict):
        for key in ("Code", "Message", "title", "type"):
            value = body.get(key)
            if isinstance(value, str) and value:
                detail[key.lower()] = value[:200]
    return detail


def pick_daily_horizon(days: int) -> int:
    """Round a requested day count up to an endpoint AccuWeather actually sells."""
    for horizon in DAILY_HORIZONS:
        if days <= horizon:
            return horizon
    return DAILY_HORIZONS[-1]


class AccuWeatherProvider(BaseForecastProvider):
    def __init__(self) -> None:
        super().__init__()
        self._location_keys: dict[str, tuple[str, float]] = {}
        self._lock = RLock()
        # Auth style proven for the current key ("bearer" | "query"), so we do
        # not pay a wasted 401 round-trip on every request.
        self._auth_mode: Optional[str] = None
        # Diagnostics surfaced by GET /v2/weather/health and GET /dev.
        self.last_error: Optional[str] = None
        self.last_status_code: Optional[int] = None
        self.last_success_at: Optional[datetime] = None
        self.credential_failure_count: int = 0
        self._credential_latch_until: float = 0.0

    @property
    def name(self) -> ProviderName:
        return ProviderName.ACCUWEATHER

    @property
    def capability(self):
        capability = get_accuweather_capability()
        plan_cap = self.plan_max_forecast_days
        if plan_cap and plan_cap < capability.max_forecast_days:
            # Report the horizon the subscription actually serves, not the
            # theoretical API maximum.
            capability = replace(capability, max_forecast_days=plan_cap)
        return capability

    # ---------------------------------------------------------------- config

    @property
    def plan_max_forecast_days(self) -> int:
        """Daily-forecast horizon the subscription allows (1|5|10|15)."""
        requested = _env_int("ACCUWEATHER_MAX_FORECAST_DAYS", DEFAULT_MAX_FORECAST_DAYS)
        return pick_daily_horizon(max(1, min(requested, 15)))

    @property
    def auth_mode(self) -> str:
        """bearer (new portal, default) | query (legacy) | auto (probe both)."""
        configured = (os.getenv("ACCUWEATHER_AUTH_MODE") or "bearer").strip().lower()
        return configured if configured in ("bearer", "query", "auto") else "bearer"

    @property
    def credential_cooldown_seconds(self) -> float:
        return max(0.0, _env_float("ACCUWEATHER_CREDENTIAL_COOLDOWN_SECONDS", 900.0))

    @property
    def location_key_ttl_seconds(self) -> float:
        return max(0.0, _env_float("ACCUWEATHER_LOCATION_KEY_TTL_HOURS", 720.0) * 3600.0)

    def _get_key(self) -> Optional[str]:
        for env_key in ("ACCUWEATHER_KEY", "VITE_ACCUWEATHER_KEY"):
            val = os.getenv(env_key)
            if val and not val.startswith("your_"):
                return val.strip()
        return None

    def is_configured(self) -> bool:
        return self._get_key() is not None

    def is_eligible(self, product: str, lat: float, lon: float) -> tuple[bool, Optional[str]]:
        if not self.is_configured():
            return False, "missing_credentials"

        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return False, "invalid_coordinates"

        if product not in SUPPORTED_PRODUCTS:
            return False, f"unsupported_product_{product}"

        # A key the gateway already rejected is latched out for a cooldown so a
        # dead AccuWeather subscription cannot tax every auto-mode request with
        # two failed round-trips before Open-Meteo is tried. A cooldown of 0
        # disables the latch (retry every request).
        if self._credentials_latched():
            return False, "credentials_rejected_cooldown"

        return True, None

    def _credentials_latched(self) -> bool:
        """True while a rejected key is being cooled down (0 s cooldown = never)."""
        if self.credential_cooldown_seconds <= 0 or not self._credential_latch_until:
            return False
        return time.monotonic() < self._credential_latch_until

    def diagnostics(self) -> dict[str, Any]:
        """Provider self-report for /v2/weather/health and /dev (never contains the key)."""
        with self._lock:
            latched = self._credentials_latched()
            cached_keys = len(self._location_keys)
        return {
            "configured": self.is_configured(),
            "auth_mode": self.auth_mode,
            "auth_mode_proven": self._auth_mode,
            "plan_max_forecast_days": self.plan_max_forecast_days,
            "credential_failures": self.credential_failure_count,
            "credentials_latched_out": latched,
            "cached_location_keys": cached_keys,
            "last_status_code": self.last_status_code,
            "last_error": self.last_error,
            "last_success_at": self.last_success_at.isoformat() if self.last_success_at else None,
            "portal_note": (
                "AccuWeather retired the legacy free tier and its keys on 2025-09-09; "
                "new-portal keys authenticate with 'Authorization: Bearer' and paid "
                "plans cap the daily horizon (Starter/Standard = 5 days)."
            ),
        }

    # ------------------------------------------------------------- internals

    def _headers(self, api_key: str, mode: str) -> dict[str, str]:
        headers = {"Accept": "application/json", "Accept-Encoding": "gzip,deflate"}
        if mode == "bearer":
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    def _request(
        self,
        client: httpx.Client,
        url: str,
        params: dict[str, Any],
        api_key: str,
        *,
        timeout: float = 12.0,
    ) -> httpx.Response:
        """GET with the portal-correct auth, retrying once in legacy mode on 401.

        ``ACCUWEATHER_AUTH_MODE=bearer`` (default) sends only the header.
        ``query`` reproduces the pre-2025 behaviour. ``auto`` tries the header
        first and, on a 401, retries with ``?apikey=`` so enterprise keys that
        still expect the query parameter keep working.
        """
        configured = self.auth_mode
        order = ["bearer", "query"] if configured == "auto" else [configured]
        proven = self._auth_mode
        if proven and proven in order:
            order = [proven] + [m for m in order if m != proven]

        last_response: Optional[httpx.Response] = None
        for mode in order:
            request_params = dict(params)
            if mode == "query":
                request_params["apikey"] = api_key
            response = client.get(
                url,
                params=request_params,
                headers=self._headers(api_key, mode),
                timeout=timeout,
            )
            last_response = response
            if response.status_code != 401:
                self._auth_mode = mode
                return response
            # A 401 is recorded once by the caller (which knows whether the whole
            # fetch failed), so probing both auth styles cannot double-count and
            # trip the circuit breaker on a single request.
        assert last_response is not None  # order is never empty
        return last_response

    def _note_failure(self, error: str, status_code: Optional[int], *, credential: bool = False) -> None:
        self.last_error = error
        self.last_status_code = status_code
        self.record_failure()
        if credential:
            self.credential_failure_count += 1
            cooldown = self.credential_cooldown_seconds
            if cooldown > 0:
                self._credential_latch_until = time.monotonic() + cooldown

    def _note_success(self) -> None:
        self.last_error = None
        self.last_status_code = None
        self.last_success_at = datetime.now(timezone.utc)
        self.credential_failure_count = 0
        self._credential_latch_until = 0.0
        self.record_success()

    def _cache_key(self, lat: float, lon: float) -> str:
        # ~100 m granularity; AccuWeather location keys are city-scale and stable.
        return f"{round(lat, 3):.3f},{round(lon, 3):.3f}"

    def _cached_location_key(self, lat: float, lon: float) -> Optional[str]:
        ttl = self.location_key_ttl_seconds
        if ttl <= 0:
            return None
        cache_key = self._cache_key(lat, lon)
        with self._lock:
            entry = self._location_keys.get(cache_key)
            if not entry:
                return None
            value, stored_at = entry
            if (time.time() - stored_at) > ttl:
                self._location_keys.pop(cache_key, None)
                return None
            return value

    def _store_location_key(self, lat: float, lon: float, location_key: str) -> None:
        if self.location_key_ttl_seconds <= 0:
            return
        with self._lock:
            if len(self._location_keys) >= 512:
                # Bounded: drop the oldest entry rather than grow without limit.
                oldest = min(self._location_keys, key=lambda k: self._location_keys[k][1])
                self._location_keys.pop(oldest, None)
            self._location_keys[self._cache_key(lat, lon)] = (location_key, time.time())

    def _geocode_location(
        self, client: httpx.Client, lat: float, lon: float, api_key: str
    ) -> tuple[Optional[str], Optional[httpx.Response]]:
        """Resolve lat/lon to an AccuWeather location key.

        Returns ``(location_key, failed_response)``. The failed response is
        handed back so the caller can report the gateway's real reason (401 vs
        403 vs 429) instead of a generic "geocode failed".
        """
        cached = self._cached_location_key(lat, lon)
        if cached:
            return cached, None

        response = self._request(
            client,
            GEOPOSITION_URL,
            {"q": f"{lat},{lon}"},
            api_key,
            timeout=10.0,
        )
        if response.status_code != 200:
            return None, response
        try:
            data = response.json() or {}
        except Exception:
            return None, response
        location_key = data.get("Key") if isinstance(data, dict) else None
        if not location_key:
            return None, None
        self._store_location_key(lat, lon, str(location_key))
        return str(location_key), None

    def _fetch_current_point(
        self, client: httpx.Client, location_key: str, api_key: str
    ) -> Optional[ForecastPoint]:
        """Current conditions are a nice-to-have: never fail the forecast for them."""
        try:
            response = self._request(
                client,
                f"{CURRENT_CONDITIONS_URL}/{location_key}",
                {"details": "true"},
                api_key,
                timeout=8.0,
            )
            if response.status_code != 200:
                return None
            payload = response.json() or [{}]
            data = (payload[0] if isinstance(payload, list) else payload) or {}
        except Exception:
            return None

        temperature = _metric(data, "Temperature")
        return ForecastPoint(
            time_utc=datetime.now(timezone.utc),
            temperature_c=temperature,
            feels_like_c=_metric(data, "RealFeelTemperature"),
            humidity_percent=_num(data.get("RelativeHumidity")),
            wind_speed_kmh=_metric(data, "Wind", "Speed"),
            wind_direction_deg=_num((data.get("Wind") or {}).get("Direction", {}).get("Degrees")),
            pressure_hpa=_metric(data, "Pressure"),
            uv_index=_num(data.get("UVIndex")),
            condition=data.get("WeatherText"),
        )

    @staticmethod
    def _normalize_daily(day: dict[str, Any]) -> dict[str, Any]:
        """Map one AccuWeather DailyForecasts entry onto the shared daily shape."""
        date_str = str(day.get("Date") or "")[:10]
        day_part = day.get("Day") or {}
        night_part = day.get("Night") or {}

        high_c = _metric(day, "TemperatureMax")
        low_c = _metric(day, "TemperatureMin")
        if high_c is None:
            # Older payloads / minimal detail levels expose Temperature.Maximum instead.
            high_c = _metric((day.get("Temperature") or {}).get("Maximum"))
        if low_c is None:
            low_c = _metric((day.get("Temperature") or {}).get("Minimum"))

        rain_prob = (
            _num(day_part.get("PrecipitationProbability"))
            if day_part.get("PrecipitationProbability") is not None
            else _num(night_part.get("PrecipitationProbability"))
        )
        rain_mm = _metric(day_part, "PrecipitationTotal")
        if rain_mm is None:
            rain_mm = _metric(night_part, "PrecipitationTotal")

        icon_phrase = day_part.get("IconPhrase") or night_part.get("IconPhrase") or "Unknown"
        entry: dict[str, Any] = {
            "date": date_str,
            "high_c": high_c,
            "low_c": low_c,
            "rain_probability": rain_prob,
            "rain_mm": rain_mm,
            "condition": icon_phrase,
            "sunrise": None,
            "sunset": None,
            "uv_index": _num(day.get("UVIndex")),
            "source": "accuweather",
        }

        # Astronomy is only present with details=true; it is local time, so it
        # is passed through verbatim and the supplement layer keeps attribution.
        astro = day.get("Astronomy") or {}
        if isinstance(astro, dict):
            entry["sunrise"] = astro.get("Sunrise") or None
            entry["sunset"] = astro.get("Sunset") or None

        epoch_date = _num(day.get("EpochDate"))
        if epoch_date:
            entry["time_utc"] = datetime.fromtimestamp(epoch_date, tz=timezone.utc).isoformat()

        return entry

    # ------------------------------------------------------------------ fetch

    def fetch(self, lat: float, lon: float, product: str = "forecast", **kwargs) -> ProviderResult:
        start = time.perf_counter()

        eligible, reason = self.is_eligible(product, lat, lon)
        if not eligible:
            if reason == "missing_credentials":
                error_code = "missing_credentials"
            elif reason == "credentials_rejected_cooldown":
                # The gateway already refused this key; say so instead of implying
                # nothing was configured.
                error_code = "invalid_credentials"
            else:
                error_code = "unsupported"
            return ProviderResult(
                success=False,
                error=f"AccuWeather not eligible: {reason}",
                error_code=error_code,
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
                location_key, failed = self._geocode_location(client, lat, lon, api_key)
                if not location_key:
                    status_code = failed.status_code if failed is not None else None
                    detail = _error_detail(failed) if failed is not None else {}
                    if status_code == 401:
                        error_code = "invalid_credentials"
                        reason_code = "invalid_credentials"
                        message = (
                            "AccuWeather rejected the API key (401). Keys from the legacy "
                            "developer portal were retired on 2025-09-09 — issue a new key at "
                            "developer.accuweather.com and send it as 'Authorization: Bearer'."
                        )
                    elif status_code == 403:
                        error_code = "not_granted"
                        reason_code = "subscription_limit"
                        message = (
                            "AccuWeather returned 403: the subscription does not include this "
                            "endpoint (geoposition search / requested horizon)."
                        )
                    elif status_code == 429:
                        error_code = "rate_limited"
                        reason_code = "rate_limited"
                        message = "AccuWeather quota exceeded (429)."
                    else:
                        error_code = "unavailable"
                        reason_code = "geocode_failed"
                        message = "Failed to resolve AccuWeather location key"
                    if detail.get("message"):
                        message = f"{message} Upstream: {detail['message']}"
                    if status_code:
                        self._note_failure(message, status_code, credential=status_code in (401, 403))
                    return ProviderResult(
                        success=False,
                        error=message,
                        error_code=error_code,
                        fallback_reason={
                            "provider": self.name.value,
                            "reason": reason_code,
                            "status_code": status_code,
                            "detail": detail or None,
                        },
                        latency_ms=(time.perf_counter() - start) * 1000,
                    )

                # Horizon the subscription is allowed to ask for.
                requested_days = int(kwargs.get("forecast_days") or DEFAULT_MAX_FORECAST_DAYS)
                horizon = min(pick_daily_horizon(requested_days), self.plan_max_forecast_days)

                daily_forecasts, endpoint_used, error_result = self._fetch_daily(
                    client, location_key, api_key, horizon, start
                )
                if error_result is not None:
                    return error_result

                daily_list = [self._normalize_daily(day) for day in daily_forecasts if isinstance(day, dict)]

                current_point = self._fetch_current_point(client, location_key, api_key)

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
                    horizon_hours=24 * len(daily_list) or None,
                    query_diagnostics={
                        "endpoint": endpoint_used,
                        "auth_mode": self._auth_mode,
                        "requested_days": requested_days,
                        "served_days": len(daily_list),
                        "location_key_cached": self._cached_location_key(lat, lon) is not None,
                    },
                )

                normalized = NormalizedForecast(
                    location={"lat": lat, "lon": lon},
                    current=current_point,
                    daily=daily_list,
                    # Hourly lives on a separate endpoint (12 h on Starter) and is
                    # intentionally omitted; the supplement layer fills hourly
                    # nulls from Open-Meteo with attribution.
                    hourly=[],
                    provenance=provenance,
                    mode=kwargs.get("mode", "everyone"),
                )

                self._note_success()
                return ProviderResult(
                    success=True,
                    forecast=normalized,
                    latency_ms=(time.perf_counter() - start) * 1000,
                )

        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            detail = _error_detail(exc.response)
            error_code = (
                "invalid_credentials" if status == 401
                else "not_granted" if status == 403
                else "rate_limited" if status == 429
                else "unavailable" if status >= 500
                else "invalid"
            )
            message = f"AccuWeather HTTP {status}"
            if detail.get("message"):
                message = f"{message}: {detail['message']}"
            self._note_failure(message, status, credential=status in (401, 403))
            return ProviderResult(
                success=False,
                error=message,
                error_code=error_code,
                fallback_reason={
                    "provider": self.name.value,
                    "reason": f"http_{status}",
                    "status_code": status,
                    "detail": detail or None,
                },
                latency_ms=(time.perf_counter() - start) * 1000,
            )
        except httpx.TimeoutException as exc:
            self._note_failure(f"AccuWeather timeout: {exc}", None)
            return ProviderResult(
                success=False,
                error=f"AccuWeather timeout: {exc}",
                error_code="timeout",
                fallback_reason={"provider": self.name.value, "reason": "timeout"},
                latency_ms=(time.perf_counter() - start) * 1000,
            )
        except httpx.TransportError as exc:
            # DNS/TLS/connection refused: the gateway was never reached, which is a
            # different diagnosis from a rejected key and must not read as "unknown".
            message = f"AccuWeather unreachable ({type(exc).__name__}): {exc}"
            self._note_failure(message, None)
            return ProviderResult(
                success=False,
                error=message,
                error_code="unavailable",
                fallback_reason={
                    "provider": self.name.value,
                    "reason": f"network_{type(exc).__name__}",
                },
                latency_ms=(time.perf_counter() - start) * 1000,
            )
        except Exception as exc:
            self._note_failure(str(exc), None)
            return ProviderResult(
                success=False,
                error=str(exc),
                error_code="unknown",
                fallback_reason={"provider": self.name.value, "reason": f"exception_{type(exc).__name__}"},
                latency_ms=(time.perf_counter() - start) * 1000,
            )

    def _fetch_daily(
        self,
        client: httpx.Client,
        location_key: str,
        api_key: str,
        horizon: int,
        start: float,
    ) -> tuple[list[dict[str, Any]], Optional[str], Optional[ProviderResult]]:
        """Fetch the daily forecast, degrading to 5 days when the plan says 403."""
        attempted = horizon
        endpoint_used: Optional[str] = None

        while True:
            url = f"{DAILY_FORECAST_URL}/{attempted}day/{location_key}"
            endpoint_used = f"/forecasts/v1/daily/{attempted}day"
            response = self._request(
                client, url, {"details": "true", "metric": "true"}, api_key, timeout=12.0
            )

            if response.status_code == 200:
                try:
                    data = response.json() or {}
                except Exception as exc:
                    self._note_failure(f"AccuWeather returned a non-JSON body: {exc}", 200)
                    return [], endpoint_used, ProviderResult(
                        success=False,
                        error="AccuWeather returned a non-JSON body",
                        error_code="invalid",
                        fallback_reason={"provider": self.name.value, "reason": "invalid_payload"},
                        latency_ms=(time.perf_counter() - start) * 1000,
                    )
                forecasts = data.get("DailyForecasts") or []
                if not isinstance(forecasts, list):
                    forecasts = []
                return forecasts, endpoint_used, None

            detail = _error_detail(response)

            # 403 = the plan does not sell this horizon (10/15-day need Prime/Elite).
            # Retry once on the 5-day product before giving up.
            if response.status_code == 403 and attempted > DEFAULT_MAX_FORECAST_DAYS:
                attempted = DEFAULT_MAX_FORECAST_DAYS
                continue

            status = response.status_code
            if status == 401:
                error_code, reason_code = "invalid_credentials", "invalid_credentials"
            elif status == 403:
                error_code, reason_code = "not_granted", "subscription_limit"
            elif status == 429:
                error_code, reason_code = "rate_limited", "rate_limited"
            elif status >= 500:
                error_code, reason_code = "unavailable", f"http_{status}"
            else:
                error_code, reason_code = "invalid", f"http_{status}"

            message = f"AccuWeather daily/{attempted}day HTTP {status}"
            if detail.get("message"):
                message = f"{message}: {detail['message']}"
            self._note_failure(message, status, credential=status in (401, 403))
            return [], endpoint_used, ProviderResult(
                success=False,
                error=message,
                error_code=error_code,
                fallback_reason={
                    "provider": self.name.value,
                    "reason": reason_code,
                    "status_code": status,
                    "detail": detail or None,
                },
                latency_ms=(time.perf_counter() - start) * 1000,
            )
