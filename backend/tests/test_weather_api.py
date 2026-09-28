from datetime import datetime, timedelta, timezone

import pytest

from weathergpt.weather.providers import open_meteo
from weathergpt.weather.providers.base import CircuitBreaker
from weathergpt.weather.service import service

# Keys the shared weather parsers in weathergpt-app and weathergpt-android read.
V2_KEYS = {"current", "hourly", "daily", "air_quality", "location", "field_sources", "degraded", "provenance",
           "temperature_spread", "precip_next_24h", "hourly_available", "fetched_at", "status"}
FLAT_KEYS = {"temperature_c", "feels_like_c", "condition", "weather_code", "high_c", "low_c", "humidity", "wind_kmh",
             "wind_direction", "pressure_hpa", "rain_probability", "uv_index", "sunrise", "sunset", "aqi", "pm2_5",
             "forecast", "timezone", "source", "selected_source", "requested_source", "fallback_reasons",
             "providers_used", "selection_policy_version"}
HOURLY_KEYS = {"time", "time_utc", "temperature_c", "rain_probability", "precipitation_probability", "precipitation_mm",
               "wind_kmh", "wind_speed_kmh", "wind_direction_deg", "humidity", "humidity_percent", "feels_like_c",
               "pressure_hpa", "cloud_cover_percent", "uv_index", "condition", "weather_code", "is_ensemble_mean",
               "missing_reason"}
DAILY_KEYS = {"date", "high_c", "low_c", "condition", "rain_probability", "precipitation_mm", "rain_mm",
              "precipitation_interval", "covers_full_day", "wind_kmh_max", "weather_code", "high_p90_c", "low_p10_c",
              "sunrise", "sunset", "uv_index_max", "hours_covered", "source", "statistic", "field_sources"}


@pytest.mark.parametrize("path", ["/v2/weather", "/weather"])
def test_payload_carries_nested_and_flat_shapes(client, upstreams, path):
    r = client.get(path, params={"lat": 23.02, "lon": 72.57, "forecast_days": 5, "hourly_hours": 6})
    assert r.status_code == 200, r.text
    body = r.json()
    assert V2_KEYS | FLAT_KEYS <= body.keys()
    assert HOURLY_KEYS <= body["hourly"][0].keys()
    assert DAILY_KEYS <= body["daily"][0].keys()
    assert body["forecast"] == body["daily"] and len(body["daily"]) == 5 and len(body["hourly"]) == 6
    assert body["selected_source"] == "open_meteo" and body["requested_source"] == "auto"
    assert body["temperature_c"] == 31.0 and body["weather_code"] == 2 and body["aqi"] == 42
    assert body["location"]["utc_offset_seconds"] == 19800
    assert r.headers["X-Request-ID"]


def test_open_meteo_local_times_are_converted_to_utc(upstreams):
    fc = service().select(23.02, 72.57, requested_source="open_meteo").forecast
    first = upstreams.open_meteo["hourly"]["time"][0]  # local midnight
    local = datetime.fromisoformat(first)
    assert fc.hourly[0].time_utc == (local - timedelta(hours=5, minutes=30)).replace(tzinfo=timezone.utc)


def test_hourly_starts_at_the_bucket_containing_now(client, upstreams):
    body = client.get("/v2/weather", params={"lat": 23, "lon": 72, "hourly_hours": 2}).json()
    first = datetime.fromisoformat(body["hourly"][0]["time_utc"])
    now = datetime.now(timezone.utc)
    assert first <= now < first + timedelta(hours=1)


def test_missing_values_stay_null(client, upstreams):
    upstreams.open_meteo["current"].pop("weather_code")
    upstreams.open_meteo["daily"]["precipitation_probability_max"] = [None] * 8
    upstreams.open_meteo["hourly"]["precipitation_probability"] = [None] * 192
    body = client.get("/v2/weather", params={"lat": 23, "lon": 72}).json()
    assert body["current"]["weather_code"] is None and body["current"]["condition"] is None
    # The flat field falls back to today's representative code, exactly like the client parser.
    assert body["weather_code"] == body["daily"][0]["weather_code"]
    assert body["rain_probability"] is None


def test_imd_primary_is_supplemented_and_attributed(client, upstreams, imd_keys):
    body = client.get("/v2/weather", params={"lat": 23.03, "lon": 72.58, "hourly_hours": 24}).json()
    assert body["selected_source"] == "imd"
    assert body["current"]["kind"] == "observation" and body["current"]["station"]["name"] == "Ahmedabad"
    fs = body["field_sources"]
    assert fs["temperature_c"] == "imd"
    assert fs["uv_index"] == "open_meteo" and fs["hourly"] == "open_meteo" and fs["air_quality"] == "open_meteo"
    assert len(body["hourly"]) == 24          # IMD has no hourly series; Open-Meteo fills it, attributed
    assert body["daily"][0]["field_sources"]["high_c"] == "imd"
    assert body["daily"][0]["field_sources"]["rain_probability"] == "open_meteo"
    assert body["daily"][2]["field_sources"]["high_c"] == "open_meteo"   # IMD said "NA"
    assert body["daily"][0]["forecast_text"].startswith("Partly cloudy")
    assert body["observed"]["max_temp_c"] == 33.4
    assert body["degraded"] is False


def test_pinned_source_never_substitutes(client, upstreams):
    body = client.get("/v2/weather", params={"lat": 23, "lon": 72, "requested_source": "imd"}).json()
    assert body["status"] == "unavailable" and body["requested_source"] == "imd"
    assert body["fallback_reasons"][0]["reason"] == "not_configured"
    r = client.get("/weather", params={"lat": 23, "lon": 72, "requested_source": "weathernext"})
    assert r.status_code == 502 and r.json()["detail"]["requested_source"] == "weathernext"


@pytest.mark.parametrize("path", ["/v2/weather", "/weather", "/advisory"])
def test_removed_provider_is_rejected(client, upstreams, path):
    key = "source" if path == "/advisory" else "requested_source"
    assert client.get(path, params={"lat": 23, "lon": 72, key: "accuweather"}).status_code == 422


def test_invalid_mode_is_rejected(client, upstreams):
    assert client.get("/v2/weather", params={"lat": 23, "lon": 72, "mode": "admin"}).status_code == 400


def test_supplement_can_be_disabled(client, upstreams, imd_keys):
    body = client.get("/v2/weather", params={"lat": 23.03, "lon": 72.58, "supplement": "false"}).json()
    assert body["field_sources"] == {} and body["hourly"] == []


def test_total_failure(client, upstreams):
    upstreams.fail.add("api.open-meteo.com")
    body = client.get("/v2/weather", params={"lat": 23, "lon": 72}).json()
    assert body["status"] == "unavailable"
    assert client.get("/weather", params={"lat": 23, "lon": 72}).status_code == 502


def test_outside_india_skips_imd_without_degrading(client, upstreams, imd_keys):
    body = client.get("/v2/weather", params={"lat": 51.5, "lon": -0.12}).json()
    assert body["selected_source"] == "open_meteo"
    assert body["fallback_reasons"][0]["reason"] == "out_of_coverage"
    assert body["degraded"] is False and body["alerts_status"] == "not_covered"


def test_weathernext_mock_is_selected_with_spread(client, upstreams, monkeypatch):
    from weathergpt.config import reset_settings
    monkeypatch.setenv("WEATHERNEXT_ENABLED", "1")
    monkeypatch.setenv("WEATHERNEXT_MOCK_DATA", "1")
    reset_settings()
    body = client.get("/v2/weather", params={"lat": 23, "lon": 72}).json()
    assert body["selected_source"] == "weathernext"
    assert body["temperature_spread"]["p90_c"] > body["temperature_spread"]["p10_c"]
    assert body["location"]["timezone"] == "Asia/Kolkata"   # supplement replaces the mock's UTC


def test_priority_env_is_respected(upstreams, monkeypatch):
    from weathergpt.config import parse_priority
    assert parse_priority("open_meteo,imd") == ("open_meteo", "imd")
    assert parse_priority("accuweather,open-meteo") == ("open_meteo",)
    assert parse_priority("") == ("imd", "weathernext", "open_meteo")


def test_circuit_breaker_recovers():
    b = CircuitBreaker(threshold=2, cooldown_seconds=0.05)
    b.record(False)
    b.record(False)
    assert not b.allow()
    import time
    time.sleep(0.06)
    assert b.allow()          # half-open after cooldown
    b.record(True)
    assert b.failures == 0 and b.allow()


def test_open_meteo_parse_prefers_msl_pressure():
    fc = open_meteo.parse(__import__("tests.conftest", fromlist=["x"]).open_meteo_payload(), 23, 72, 3)
    assert fc.current.pressure_hpa == 1006.0 and fc.current.pressure_type == "msl"
    assert len(fc.daily) == 3


def test_alerts_in_payload(client, upstreams):
    body = client.get("/v2/weather", params={"lat": 23.02, "lon": 72.57}).json()
    assert body["alerts_status"] == "ok"
    assert [a["id"] for a in body["alerts"]] == ["sachet:111"]


def test_series_and_health(client, upstreams):
    s = client.get("/v2/weather/series", params={"lat": 23, "lon": 72, "variable": "temperature_2m"}).json()
    assert s["status"] == "ok" and s["values"]
    h = client.get("/v2/weather/health").json()
    assert h["provider_priority"] == ["imd", "weathernext", "open_meteo"]
    assert set(h["provider_health"]) == {"imd", "weathernext", "open_meteo"}
