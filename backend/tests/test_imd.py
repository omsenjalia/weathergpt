from datetime import datetime, timedelta, timezone

import pytest

from weathergpt.imd import client as imd_client
from weathergpt.imd import endpoints
from weathergpt.imd.parse import number, parse_hhmm
from weathergpt.weather.codes import from_imd_forecast_text, from_imd_present_weather
from weathergpt.weather.service import service


def test_registry_covers_every_published_api():
    # 28 APIs in the public reference + the two documented mapping helpers.
    assert len(endpoints.ENDPOINTS) == 30
    assert len({e.key for e in endpoints.ENDPOINTS}) == 30
    documented = [e for e in endpoints.ENDPOINTS if e.verified]
    assert len(documented) == 22
    assert endpoints.get("current_weather").path == "current_wx"
    assert endpoints.get("cyclone_cone").path == "cyclone_cou"


def test_unverified_path_can_be_overridden(monkeypatch):
    monkeypatch.setenv("IMD_ENDPOINT_AGROMET", "agromet_advisory")
    ep = endpoints.get("agromet")
    assert ep.resolved_path() == "agromet_advisory"
    assert ep.to_dict()["path_verified"] is True


def test_client_sends_both_auth_headers(upstreams, imd_keys):
    resp = imd_client.fetch("current_weather", {"id": "42647"})
    assert resp.rows[0]["Station"] == "Ahmedabad"
    _, params, headers = upstreams.calls[-1]
    assert headers["X-API-Key"] == "test-key"
    assert headers["Authorization"] == "Bearer test.jwt.token"
    assert params == {"id": "42647"}


def test_client_classifies_gateway_errors(upstreams, imd_keys):
    upstreams.imd_status, upstreams.imd_error = 401, "Invalid or expired JWT token"
    with pytest.raises(imd_client.IMDError) as exc:
        imd_client.fetch("cyclone_track")
    assert exc.value.reason == "token_invalid_or_expired"
    upstreams.imd_status, upstreams.imd_error = 403, "Forbidden"
    with pytest.raises(imd_client.IMDError) as exc:
        imd_client.fetch("coastal_bulletin")
    assert exc.value.reason == "forbidden_ip_not_whitelisted"


def test_not_configured_makes_no_request(upstreams):
    with pytest.raises(imd_client.IMDError) as exc:
        imd_client.fetch("cyclone_track")
    assert exc.value.reason == "not_configured"
    assert upstreams.urls("api.imd.gov.in") == []


def test_imd_is_primary_with_station_observation(upstreams, imd_keys):
    sel = service().select(23.03, 72.58, forecast_days=7)
    assert sel.selected_source == "imd"
    fc = sel.forecast
    assert fc.current_kind == "observation"
    assert fc.current.temperature_c == 32.8
    assert fc.current.pressure_type == "msl"
    assert fc.current.weather_code == 45 and "haze" in fc.current.condition.lower()
    assert fc.provenance.station["name"] == "Ahmedabad"
    assert fc.location["utc_offset_seconds"] == 19800
    today = fc.daily[0]
    assert (today.high_c, today.low_c) == (34, 25)
    assert today.weather_code == 2  # "partly cloudy ... possibility of rain" shows cloud, not rain
    assert today.sunrise.endswith("T06:25")
    assert fc.daily[1].weather_code == 95
    assert fc.daily[2].high_c is None  # "NA" stays null
    assert fc.location["observed"]["past_24h_rainfall_mm"] == 0.0  # "Trace"


def test_imd_far_from_any_station_is_not_a_degradation(upstreams, imd_keys):
    sel = service().select(19.07, 72.88)  # Mumbai: nearest fake station is ~450 km away
    assert sel.selected_source == "open_meteo"
    assert sel.fallback_reasons[0]["reason"] == "no_station_nearby"
    assert sel.degraded is False


def test_stale_observation_is_not_presented_as_now(upstreams, imd_keys):
    old = datetime.now(timezone.utc) - timedelta(hours=9)
    upstreams.imd_rows["current_wx"][0].update({"Date of Observation": old.date().isoformat(),
                                                "Time of Observation": old.strftime("%H:%M")})
    fc = service().select(23.03, 72.58).forecast
    assert fc.current is None
    assert any("observation_age" in n for n in fc.provenance.notes)


def test_rejected_credentials_fall_back_and_are_degraded(upstreams, imd_keys):
    upstreams.imd_status, upstreams.imd_error = 401, "Invalid or expired JWT token"
    sel = service().select(23.03, 72.58)
    assert sel.selected_source == "open_meteo"
    assert sel.fallback_reasons[0]["reason"] == "token_invalid_or_expired"
    assert sel.degraded is True


def test_imd_text_and_present_weather_mapping():
    assert from_imd_forecast_text("Heavy rain with thunderstorm")[0] == 95
    assert from_imd_forecast_text("Generally cloudy sky with light rain")[0] == 61
    assert from_imd_forecast_text("Mainly Clear sky")[0] == 1
    assert from_imd_forecast_text("NA") == (None, None)
    assert from_imd_present_weather(2, 7) == (3, "Overcast")          # sky evolution -> nebulosity
    assert from_imd_present_weather(95, 8)[0] == 95
    assert from_imd_present_weather(None, 0) == (0, "Clear sky")


def test_parse_helpers():
    assert number({"Temperature": " 31.5 "}, "temperature") == 31.5
    assert number({"M.S.L.P": "1005.2 hPa"}, "MSLP") == 1005.2
    assert number({"x": "--"}, "x") is None
    assert parse_hhmm("6:05 PM") == (18, 5)
    assert parse_hhmm("0612") == (6, 12)


def test_proxy_and_catalog(client, upstreams, imd_keys):
    cat = client.get("/v2/imd").json()
    assert cat["count"] == 30 and cat["status"]["configured"] is True
    body = client.get("/v2/imd/district_warning", params={"limit": 1}).json()
    assert body["count"] == 2 and len(body["data"]) == 1 and body["truncated"] is True
    assert client.get("/v2/imd/sun_moon").status_code == 422      # lat/lon required
    assert client.get("/v2/imd/unknown").status_code == 404


def test_proxy_without_credentials_is_503(client, upstreams):
    r = client.get("/v2/imd/cyclone_track")
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "imd_not_configured"


def _token(exp: float) -> str:
    import base64, json
    head = base64.urlsafe_b64encode(json.dumps({"uid": 1, "exp": exp}).encode()).decode().rstrip("=")
    return f"{head}.signature"


def test_expired_jwt_fails_fast_without_a_request(upstreams, monkeypatch):
    import time
    from weathergpt.config import reset_settings
    monkeypatch.setenv("IMD_API_KEY", "k")
    monkeypatch.setenv("IMD_JWT_TOKEN", _token(time.time() - 60))
    reset_settings()
    with pytest.raises(imd_client.IMDError) as exc:
        imd_client.fetch("cyclone_track")
    assert exc.value.reason == "token_expired"
    assert upstreams.urls("api.imd.gov.in") == []
    assert imd_client.status()["jwt_expired"] is True
    sel = service().select(23.03, 72.58)
    assert sel.selected_source == "open_meteo" and sel.fallback_reasons[0]["reason"] == "token_expired"
    assert sel.degraded is True


def test_valid_jwt_expiry_is_reported(upstreams, monkeypatch):
    import time
    from weathergpt.config import reset_settings
    monkeypatch.setenv("IMD_API_KEY", "k")
    monkeypatch.setenv("IMD_JWT_TOKEN", _token(time.time() + 3600))
    reset_settings()
    assert imd_client.status()["jwt_expired"] is False and imd_client.status()["jwt_expires_at"]
    assert imd_client.fetch("current_weather").rows
