"""Offline tests for the AccuWeather provider adapter — no network, no real key.

AccuWeather relaunched its developer portal on 2025-09-09: every legacy API key
was retired, authentication moved to ``Authorization: Bearer <key>``, the free
tier became a 14-day trial, and paid plans cap the daily horizon (Starter and
Standard sell 5-day daily forecasts only; 10-day needs Prime, 15-day Elite).

These tests pin the contract that keeps the provider honest after that change:

- new-portal auth (bearer header, HTTPS, gzip hint) with an opt-in legacy mode
- a rejected key is reported as a rejected key (401 -> invalid_credentials),
  never as a mystery "geocode failure", and is latched out so a dead
  subscription cannot tax every auto-mode request
- a 403 on a wide horizon degrades to the 5-day product instead of failing
- the requested horizon is clamped to what the plan actually sells
- metric values are read explicitly, so an Imperial-default account still
  normalizes to Celsius
- location keys are cached, because every forecast costs 2-3 paid calls
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Callable

import httpx
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.providers import accuweather as aw  # noqa: E402
from services.forecast_models import ProviderName  # noqa: E402

# httpx.Client is patched per-test, so keep a handle on the real class.
REAL_CLIENT = httpx.Client

LAT, LON = 22.5626, 88.3639  # Kolkata
LOCATION_KEY = "303938"

GATEWAY_401 = {
    "type": "https://httpproblems.com/http-status/401",
    "title": "Unauthorized",
    "status": 401,
    "Code": "Unauthorized",
    "Message": "API authorization failed",
}

GATEWAY_403 = {
    "type": "https://httpproblems.com/http-status/403",
    "title": "Forbidden",
    "status": 403,
    "Code": "Forbidden",
    "Message": "Your subscription does not allow access to this endpoint",
}


def _daily_payload(days: int = 5) -> dict[str, Any]:
    forecasts = []
    for i in range(days):
        forecasts.append({
            "Date": f"2026-09-{20 + i}T07:00:00+05:30",
            "EpochDate": 1789948800 + i * 86400,
            "TemperatureMax": {"Metric": {"Value": 31.0 + i, "Unit": "C"}, "Imperial": {"Value": 88 + i}},
            "TemperatureMin": {"Metric": {"Value": 25.0 + i, "Unit": "C"}, "Imperial": {"Value": 77 + i}},
            "Day": {
                "IconPhrase": "Mostly cloudy",
                "PrecipitationProbability": 40 + i,
                "PrecipitationTotal": {"Metric": {"Value": 2.5, "Unit": "mm"}},
            },
            "Night": {"IconPhrase": "Cloudy", "PrecipitationProbability": 20},
            "UVIndex": 7,
            "Astronomy": {"Sunrise": "5:18 AM", "Sunset": "5:28 PM"},
        })
    return {"DailyForecasts": forecasts}


def _current_payload() -> list[dict[str, Any]]:
    return [{
        "WeatherText": "Light rain",
        "Temperature": {"Metric": {"Value": 28.4, "Unit": "C"}, "Imperial": {"Value": 83}},
        "RealFeelTemperature": {"Metric": {"Value": 32.1, "Unit": "C"}},
        "RelativeHumidity": 84,
        "Wind": {"Speed": {"Metric": {"Value": 14.8, "Unit": "km/h"}}, "Direction": {"Degrees": 120}},
        "Pressure": {"Metric": {"Value": 1004.2, "Unit": "mb"}},
        "UVIndex": 3,
    }]


# --------------------------------------------------------------------------- harness


class Recorder:
    """Captures every request the provider makes so auth can be asserted."""

    def __init__(self, handler: Callable[[httpx.Request], httpx.Response]):
        self.handler = handler
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(request)

    @property
    def paths(self) -> list[str]:
        return [r.url.path for r in self.requests]

    def auth_headers(self) -> list[str | None]:
        return [r.headers.get("Authorization") for r in self.requests]

    def apikey_params(self) -> list[str | None]:
        return [r.url.params.get("apikey") for r in self.requests]


def _json_response(status: int, body: Any) -> httpx.Response:
    return httpx.Response(status, json=body)


def install_transport(monkeypatch, handler: Callable[[httpx.Request], httpx.Response]) -> Recorder:
    """Route every httpx.Client the provider builds through a MockTransport."""
    recorder = Recorder(handler)

    def _client(*args: Any, **kwargs: Any) -> httpx.Client:
        kwargs.pop("transport", None)
        return REAL_CLIENT(transport=httpx.MockTransport(recorder), **kwargs)

    monkeypatch.setattr(aw.httpx, "Client", _client)
    return recorder


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in (
        "ACCUWEATHER_KEY",
        "VITE_ACCUWEATHER_KEY",
        "ACCUWEATHER_AUTH_MODE",
        "ACCUWEATHER_MAX_FORECAST_DAYS",
        "ACCUWEATHER_CREDENTIAL_COOLDOWN_SECONDS",
        "ACCUWEATHER_LOCATION_KEY_TTL_HOURS",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ACCUWEATHER_KEY", "new-portal-key")
    yield


def _ok_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path.startswith("/locations/v1/cities/geoposition"):
        return _json_response(200, {"Key": LOCATION_KEY, "EnglishName": "Kolkata"})
    if request.url.path.startswith("/forecasts/v1/daily/"):
        days = int(request.url.path.split("/")[4].replace("day", ""))
        return _json_response(200, _daily_payload(days))
    if request.url.path.startswith("/currentconditions/v1/"):
        return _json_response(200, _current_payload())
    return _json_response(404, {"Message": "unexpected path"})


# --------------------------------------------------------------------------- auth


def test_bearer_auth_is_default_and_apikey_param_is_not_sent(monkeypatch):
    recorder = install_transport(monkeypatch, _ok_handler)
    result = aw.AccuWeatherProvider().fetch(LAT, LON, product="forecast", forecast_days=5)

    assert result.success, result.error
    assert recorder.auth_headers() and all(h == "Bearer new-portal-key" for h in recorder.auth_headers())
    assert all(p is None for p in recorder.apikey_params())
    assert all(str(r.url).startswith("https://dataservice.accuweather.com") for r in recorder.requests)
    assert all(r.headers.get("Accept-Encoding") == "gzip,deflate" for r in recorder.requests)


def test_legacy_query_mode_is_opt_in(monkeypatch):
    monkeypatch.setenv("ACCUWEATHER_AUTH_MODE", "query")
    recorder = install_transport(monkeypatch, _ok_handler)
    result = aw.AccuWeatherProvider().fetch(LAT, LON, product="forecast", forecast_days=5)

    assert result.success, result.error
    assert all(p == "new-portal-key" for p in recorder.apikey_params())
    assert all(h is None for h in recorder.auth_headers())


def test_auto_mode_falls_back_to_query_param_for_legacy_keys(monkeypatch):
    monkeypatch.setenv("ACCUWEATHER_AUTH_MODE", "auto")
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        # The gateway only accepts this particular key as a query parameter.
        if request.headers.get("Authorization"):
            return _json_response(401, GATEWAY_401)
        seen.append(request.url.path)
        return _ok_handler(request)

    install_transport(monkeypatch, handler)
    provider = aw.AccuWeatherProvider()
    result = provider.fetch(LAT, LON, product="forecast", forecast_days=5)

    assert result.success, result.error
    assert seen, "legacy query retry never happened"
    assert provider._auth_mode == "query"


# --------------------------------------------------------------------------- parsing


def test_daily_forecast_is_normalized_to_celsius_with_astronomy(monkeypatch):
    install_transport(monkeypatch, _ok_handler)
    result = aw.AccuWeatherProvider().fetch(LAT, LON, product="forecast", forecast_days=5)

    assert result.success, result.error
    daily = result.forecast.daily
    assert len(daily) == 5
    assert daily[0]["high_c"] == 31.0 and daily[0]["low_c"] == 25.0
    assert daily[0]["date"] == "2026-09-20"
    assert daily[0]["condition"] == "Mostly cloudy"
    assert daily[0]["rain_probability"] == 40
    assert daily[0]["rain_mm"] == 2.5
    assert daily[0]["sunrise"] == "5:18 AM" and daily[0]["sunset"] == "5:28 PM"
    assert daily[0]["source"] == "accuweather"

    current = result.forecast.current
    assert current.temperature_c == 28.4
    assert current.feels_like_c == 32.1
    assert current.humidity_percent == 84
    assert current.wind_speed_kmh == 14.8
    assert current.pressure_hpa == 1004.2
    assert current.condition == "Light rain"

    provenance = result.forecast.provenance
    assert provenance.selected_source == ProviderName.ACCUWEATHER
    assert provenance.sources == ["accuweather"]
    assert provenance.query_diagnostics["auth_mode"] == "bearer"
    assert provenance.query_diagnostics["endpoint"] == "/forecasts/v1/daily/5day"


def test_legacy_temperature_maximum_envelope_is_still_understood(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/forecasts/v1/daily/"):
            return _json_response(200, {"DailyForecasts": [{
                "Date": "2026-09-20T07:00:00+05:30",
                "Temperature": {
                    "Maximum": {"Metric": {"Value": 33.3, "Unit": "C"}},
                    "Minimum": {"Metric": {"Value": 26.1, "Unit": "C"}},
                },
                "Day": {"IconPhrase": "Sunny"},
            }]})
        return _ok_handler(request)

    install_transport(monkeypatch, handler)
    result = aw.AccuWeatherProvider().fetch(LAT, LON, product="forecast", forecast_days=5)

    assert result.success, result.error
    assert result.forecast.daily[0]["high_c"] == 33.3
    assert result.forecast.daily[0]["low_c"] == 26.1


def test_current_conditions_failure_never_fails_the_forecast(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/currentconditions/v1/"):
            return _json_response(403, GATEWAY_403)
        return _ok_handler(request)

    install_transport(monkeypatch, handler)
    result = aw.AccuWeatherProvider().fetch(LAT, LON, product="forecast", forecast_days=5)

    assert result.success, result.error
    assert result.forecast.current is None
    assert len(result.forecast.daily) == 5


# --------------------------------------------------------------------------- horizon


@pytest.mark.parametrize("requested,endpoint", [
    (1, "/forecasts/v1/daily/1day"),
    (3, "/forecasts/v1/daily/5day"),
    (7, "/forecasts/v1/daily/5day"),   # clamped: Starter/Standard sell 5 days
    (14, "/forecasts/v1/daily/5day"),  # clamped
])
def test_horizon_is_clamped_to_what_the_plan_sells(monkeypatch, requested, endpoint):
    recorder = install_transport(monkeypatch, _ok_handler)
    result = aw.AccuWeatherProvider().fetch(LAT, LON, product="forecast", forecast_days=requested)

    assert result.success, result.error
    assert any(path.startswith(endpoint + "/") for path in recorder.paths), recorder.paths


def test_elite_horizon_is_allowed_when_configured(monkeypatch):
    monkeypatch.setenv("ACCUWEATHER_MAX_FORECAST_DAYS", "15")
    recorder = install_transport(monkeypatch, _ok_handler)
    provider = aw.AccuWeatherProvider()
    result = provider.fetch(LAT, LON, product="forecast", forecast_days=12)

    assert result.success, result.error
    assert any(path.startswith("/forecasts/v1/daily/15day/") for path in recorder.paths), recorder.paths
    assert provider.capability.max_forecast_days == 15


def test_capability_reports_the_plan_horizon_by_default(monkeypatch):
    assert aw.AccuWeatherProvider().capability.max_forecast_days == 5


def test_403_on_wide_horizon_degrades_to_five_days(monkeypatch):
    monkeypatch.setenv("ACCUWEATHER_MAX_FORECAST_DAYS", "10")
    recorder = install_transport(monkeypatch, _ok_handler)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/forecasts/v1/daily/10day/303938"):
            return _json_response(403, GATEWAY_403)
        return _ok_handler(request)

    recorder.handler = handler
    result = aw.AccuWeatherProvider().fetch(LAT, LON, product="forecast", forecast_days=10)

    assert result.success, result.error
    assert any(path.startswith("/forecasts/v1/daily/5day/") for path in recorder.paths), recorder.paths


# --------------------------------------------------------------------------- failures


def test_missing_key_is_reported_as_missing_credentials(monkeypatch):
    monkeypatch.delenv("ACCUWEATHER_KEY", raising=False)
    provider = aw.AccuWeatherProvider()
    eligible, reason = provider.is_eligible("forecast", LAT, LON)

    assert (eligible, reason) == (False, "missing_credentials")
    result = provider.fetch(LAT, LON, product="forecast")
    assert not result.success
    assert result.error_code == "missing_credentials"
    assert result.fallback_reason["reason"] == "missing_credentials"


def test_placeholder_key_is_ignored(monkeypatch):
    monkeypatch.setenv("ACCUWEATHER_KEY", "your_accuweather_key_here")
    assert aw.AccuWeatherProvider().is_configured() is False


def test_retired_key_surfaces_401_and_not_a_geocode_failure(monkeypatch):
    install_transport(monkeypatch, lambda request: _json_response(401, GATEWAY_401))
    provider = aw.AccuWeatherProvider()
    result = provider.fetch(LAT, LON, product="forecast", forecast_days=5)

    assert not result.success
    assert result.error_code == "invalid_credentials"
    assert result.fallback_reason["reason"] == "invalid_credentials"
    assert result.fallback_reason["status_code"] == 401
    assert "2025-09-09" in result.error
    assert "geocode" not in result.error.lower()
    assert provider.diagnostics()["last_status_code"] == 401


def test_rejected_key_is_latched_out_for_a_cooldown(monkeypatch):
    install_transport(monkeypatch, lambda request: _json_response(401, GATEWAY_401))
    provider = aw.AccuWeatherProvider()

    assert provider.is_eligible("forecast", LAT, LON) == (True, None)
    provider.fetch(LAT, LON, product="forecast", forecast_days=5)

    eligible, reason = provider.is_eligible("forecast", LAT, LON)
    assert (eligible, reason) == (False, "credentials_rejected_cooldown")
    assert provider.diagnostics()["credentials_latched_out"] is True

    # The latch reports an invalid credential, not a missing one.
    latched = provider.fetch(LAT, LON, product="forecast", forecast_days=5)
    assert not latched.success
    assert latched.error_code == "invalid_credentials"
    assert latched.fallback_reason["reason"] == "credentials_rejected_cooldown"
    assert provider.credential_failure_count == 1  # one rejected fetch, counted once

    # ... and the latch is released by configuration for callers that want to retry.
    monkeypatch.setenv("ACCUWEATHER_CREDENTIAL_COOLDOWN_SECONDS", "0")
    assert provider.is_eligible("forecast", LAT, LON) == (True, None)


def test_quota_exceeded_maps_to_rate_limited(monkeypatch):
    body = {"Code": "ServiceUnavailable", "Message": "The allowed number of requests has been exceeded."}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/locations/"):
            return _json_response(429, body)
        return _ok_handler(request)

    install_transport(monkeypatch, handler)
    result = aw.AccuWeatherProvider().fetch(LAT, LON, product="forecast", forecast_days=5)

    assert not result.success
    assert result.error_code == "rate_limited"
    assert result.fallback_reason["status_code"] == 429
    assert "allowed number of requests" in result.error


def test_subscription_403_on_geoposition_is_not_granted(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/locations/"):
            return _json_response(403, GATEWAY_403)
        return _ok_handler(request)

    install_transport(monkeypatch, handler)
    result = aw.AccuWeatherProvider().fetch(LAT, LON, product="forecast", forecast_days=5)

    assert not result.success
    assert result.error_code == "not_granted"
    assert result.fallback_reason["reason"] == "subscription_limit"
    assert result.fallback_reason["detail"]["message"].startswith("Your subscription")


def test_timeout_is_reported_as_timeout(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("connection timed out", request=request)

    install_transport(monkeypatch, handler)
    result = aw.AccuWeatherProvider().fetch(LAT, LON, product="forecast", forecast_days=5)

    assert not result.success
    assert result.error_code == "timeout"
    assert result.fallback_reason["reason"] == "timeout"


def test_unreachable_gateway_is_reported_as_network_not_unknown(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("TLS/SSL connection has been closed", request=request)

    install_transport(monkeypatch, handler)
    result = aw.AccuWeatherProvider().fetch(LAT, LON, product="forecast", forecast_days=5)

    assert not result.success
    assert result.error_code == "unavailable"
    assert result.fallback_reason["reason"] == "network_ConnectError"
    assert "unreachable" in result.error


def test_non_json_body_does_not_crash(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/forecasts/"):
            return httpx.Response(200, text="<html>gateway error page</html>")
        return _ok_handler(request)

    install_transport(monkeypatch, handler)
    result = aw.AccuWeatherProvider().fetch(LAT, LON, product="forecast", forecast_days=5)

    assert not result.success
    assert result.error_code == "invalid"


# --------------------------------------------------------------------------- caching


def test_location_key_is_cached_across_fetches(monkeypatch):
    recorder = install_transport(monkeypatch, _ok_handler)
    provider = aw.AccuWeatherProvider()

    provider.fetch(LAT, LON, product="forecast", forecast_days=5)
    geocodes_after_first = sum(1 for p in recorder.paths if "geoposition" in p)
    provider.fetch(LAT, LON, product="forecast", forecast_days=5)
    geocodes_after_second = sum(1 for p in recorder.paths if "geoposition" in p)

    assert geocodes_after_first == 1
    assert geocodes_after_second == 1  # second call reused the cached key
    assert provider.diagnostics()["cached_location_keys"] == 1


def test_location_key_cache_can_be_disabled(monkeypatch):
    monkeypatch.setenv("ACCUWEATHER_LOCATION_KEY_TTL_HOURS", "0")
    recorder = install_transport(monkeypatch, _ok_handler)
    provider = aw.AccuWeatherProvider()

    provider.fetch(LAT, LON, product="forecast", forecast_days=5)
    provider.fetch(LAT, LON, product="forecast", forecast_days=5)

    assert sum(1 for p in recorder.paths if "geoposition" in p) == 2
    assert provider.diagnostics()["cached_location_keys"] == 0


def test_diagnostics_never_leak_the_key(monkeypatch):
    install_transport(monkeypatch, _ok_handler)
    provider = aw.AccuWeatherProvider()
    provider.fetch(LAT, LON, product="forecast", forecast_days=5)

    assert "new-portal-key" not in json.dumps(provider.diagnostics())


# --------------------------------------------------------------------------- fusion


def test_fusion_reports_a_retired_accuweather_key_instead_of_failing_silently(monkeypatch):
    from services import fusion

    monkeypatch.setenv("ACCUWEATHER_KEY", "retired-legacy-key")
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if "accuweather" in request.url.host:
            if request.headers.get("Authorization") == "Bearer retired-legacy-key":
                return _json_response(401, GATEWAY_401)
            return _json_response(401, GATEWAY_401)
        return _json_response(200, {"current": {"temperature_2m": 29.5, "weather_code": 1}})

    monkeypatch.setattr(
        fusion.httpx, "Client",
        lambda *a, **k: REAL_CLIENT(transport=httpx.MockTransport(handler)),
    )
    fused = fusion.fuse_current_weather(LAT, LON)

    assert fused["providers_used"] == ["Open-Meteo (ECMWF)"]
    assert "AccuWeather" in fused["provider_errors"]
    assert "401" in fused["provider_errors"]["AccuWeather"]
    assert "2025-09-09" in fused["provider_errors"]["AccuWeather"]


def test_fusion_sends_bearer_auth_for_accuweather(monkeypatch):
    from services import fusion

    monkeypatch.setenv("ACCUWEATHER_KEY", "new-portal-key")
    auth_seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "accuweather" in request.url.host:
            auth_seen.append(request.headers.get("Authorization"))
            if request.url.path.startswith("/locations/"):
                return _json_response(200, {"Key": LOCATION_KEY})
            return _json_response(200, _current_payload())
        return _json_response(200, {"current": {"temperature_2m": 29.5, "weather_code": 1}})

    monkeypatch.setattr(
        fusion.httpx, "Client",
        lambda *a, **k: REAL_CLIENT(transport=httpx.MockTransport(handler)),
    )
    fused = fusion.fuse_current_weather(LAT, LON)

    assert auth_seen == ["Bearer new-portal-key", "Bearer new-portal-key"]
    assert "AccuWeather" in fused["providers_used"]
    assert fused["provider_errors"] == {}
