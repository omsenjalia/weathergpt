from datetime import datetime, timedelta, timezone

import pytest

from weathergpt.imd import client as imd_client
from weathergpt.imd import endpoints
from weathergpt.imd.parse import number, parse_hhmm
from weathergpt.weather.codes import from_imd_forecast_text, from_imd_present_weather
from weathergpt.weather.service import service


def test_registry_covers_every_published_api():
    # The 21 APIs in the account docs, all verified live; the rest of the public list 404s.
    assert len(endpoints.ENDPOINTS) == 21
    assert len({e.key for e in endpoints.ENDPOINTS}) == 21
    assert all(e.verified and e.in_account_docs for e in endpoints.ENDPOINTS)
    assert endpoints.get("cyclone_track") is None
    assert endpoints.get("city_forecast_warning").path == "cityforecastwarning"
    assert endpoints.get("current_weather").path == "current_wx"


def test_path_can_be_overridden(monkeypatch):
    monkeypatch.setenv("IMD_ENDPOINT_TOURIST_FORECAST", "touristforecast_v2")
    assert endpoints.get("tourist_forecast").resolved_path() == "touristforecast_v2"


def test_client_sends_both_auth_headers(upstreams, imd_keys):
    resp = imd_client.fetch("current_weather", {"id": "42647"})
    assert resp.rows[0]["Station"] == "Ahmedabad"
    _, params, headers = upstreams.calls[-1]
    assert headers["X-API-KEY"] == "test-key"
    assert headers["Authorization"].startswith("Bearer ") and len(headers["Authorization"]) > 40
    assert params == {"id": "42647"}


def test_client_classifies_gateway_errors(upstreams, imd_keys):
    upstreams.imd_status, upstreams.imd_error = 401, "Invalid or expired JWT token"
    with pytest.raises(imd_client.IMDError) as exc:
        imd_client.fetch("port_warning")
    assert exc.value.reason == "token_invalid_or_expired"
    upstreams.imd_status, upstreams.imd_error = 403, "Forbidden"
    with pytest.raises(imd_client.IMDError) as exc:
        imd_client.fetch("coastal_bulletin")
    assert exc.value.reason == "forbidden_ip_not_whitelisted"


def test_not_configured_makes_no_request(upstreams):
    with pytest.raises(imd_client.IMDError) as exc:
        imd_client.fetch("coastal_bulletin")
    assert exc.value.reason == "not_configured"
    assert upstreams.urls("api.imd.gov.in") == []


def test_imd_is_primary_with_station_observation(upstreams, imd_keys):
    sel = service().select(23.03, 72.58, forecast_days=7)
    assert sel.selected_source == "imd"
    fc = sel.forecast
    assert fc.current_kind == "observation"
    assert fc.current.temperature_c == 32.8
    assert fc.current.pressure_type == "msl"
    assert fc.current.weather_code == 45 and fc.current.condition == "Haze"   # IMD's own WEATHER_MESSAGE
    assert fc.current.feels_like_c == 35.1
    assert fc.provenance.station["name"] == "Ahmedabad"
    assert fc.location["utc_offset_seconds"] == 19800
    today = fc.daily[0]
    assert (today.high_c, today.low_c) == (34, 25)
    assert today.weather_code == 2  # "partly cloudy ... possibility of rain" shows cloud, not rain
    assert today.sunrise.endswith("T06:25")
    assert fc.daily[1].weather_code == 95
    assert fc.daily[2].high_c is None  # "NA" stays null
    assert fc.location["observed"]["past_24h_rainfall_mm"] == 0.0  # "NIL" means no rain, not unknown


def test_observation_comes_from_nearest_reporting_station(upstreams, imd_keys):
    # Forecast station "Mumbai City" sends no current_wx; Santacruz (about 15 km away) does.
    fc = service().select(18.97, 72.83).forecast
    assert fc.provenance.station["name"] == "Mumbai City (forecast only)"
    assert fc.current_kind == "observation" and fc.current.temperature_c == 30.0
    assert fc.current.wind_direction_deg is None                         # direction 0 = calm
    assert fc.provenance.station["observation_station"]["name"] == "Mumbai-Santacruz"


def test_imd_far_from_any_station_is_not_a_degradation(upstreams, imd_keys):
    sel = service().select(15.3, 74.1)  # Goa: nearest fake station is hundreds of km away
    assert sel.selected_source == "open_meteo"
    assert sel.fallback_reasons[0]["reason"] == "no_station_nearby"
    assert sel.degraded is False


def test_stale_observation_is_not_presented_as_now(upstreams, imd_keys):
    old = datetime.now(timezone.utc) - timedelta(hours=9)
    for row in upstreams.imd_rows["current_wx"]:
        row.update({"Date of Observation": old.date().isoformat(), "Time": str(old.hour)})
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
    assert parse_hhmm("12") == (12, 0)          # current_wx "Time" is the UTC hour alone
    assert parse_hhmm("12:15:00") == (12, 15)   # aws_data TIME
    assert number({"r": "NIL"}, "r") == 0.0


def test_proxy_and_catalog(client, upstreams, imd_keys, admin):
    cat = client.get("/v2/imd").json()
    assert cat["count"] == 21 and cat["status"]["configured"] is True
    body = client.get("/v2/imd/district_warning", params={"limit": 1}, headers=admin).json()
    assert body["count"] == 2 and len(body["data"]) == 1 and body["truncated"] is True
    assert client.get("/v2/imd/sun_moon", headers=admin).status_code == 422      # lat/lon required
    assert client.get("/v2/imd/unknown", headers=admin).status_code == 404


def test_raw_proxy_is_not_public_by_default(client, upstreams, imd_keys, admin, monkeypatch):
    # IMD terms prohibit redistribution: raw data needs the admin token unless opted in.
    assert client.get("/v2/imd/district_warning").status_code == 401
    assert client.get("/v2/imd/nearest", params={"lat": 23, "lon": 72}).status_code == 401
    from weathergpt.config import reset_settings
    monkeypatch.setenv("IMD_PUBLIC_PROXY", "1")
    reset_settings()
    assert client.get("/v2/imd/district_warning").status_code == 200


def test_tokens_are_minted_and_renewed(upstreams, monkeypatch):
    from weathergpt.config import reset_settings
    monkeypatch.setenv("IMD_API_KEY", "k")
    monkeypatch.setenv("IMD_EMAIL", "me@example.com")
    monkeypatch.setenv("IMD_PASSWORD", "pw")
    reset_settings()
    assert imd_client.fetch("current_weather").rows
    assert len(upstreams.issued_tokens) == 1
    imd_client.fetch("district_warning")
    assert len(upstreams.issued_tokens) == 1              # reused while fresh
    # The gateway rejects the token early -> renewed once and the call succeeds.
    upstreams.reject_tokens.add(upstreams.issued_tokens[0])
    assert imd_client.fetch("basin_qpf", use_cache=False) is not None
    assert len(upstreams.issued_tokens) == 2
    st = imd_client.status()
    assert st["token_source"] == "minted" and st["auto_renew"] is True and st["jwt_expired"] is False
    login = [c for c in upstreams.calls if "oauth/token.php" in c[0]]
    assert login and all("pw" not in str(c[1]) for c in login)   # password only in the body, never the URL


def test_near_expiry_env_token_is_replaced_by_minting(upstreams, monkeypatch):
    from tests.conftest import make_token
    from weathergpt.config import reset_settings
    monkeypatch.setenv("IMD_API_KEY", "k")
    monkeypatch.setenv("IMD_JWT_TOKEN", make_token(30))   # inside the 2-minute renewal margin
    monkeypatch.setenv("IMD_EMAIL", "me@example.com")
    monkeypatch.setenv("IMD_PASSWORD", "pw")
    reset_settings()
    imd_client.fetch("current_weather")
    assert len(upstreams.issued_tokens) == 1


def test_wrong_password_is_reported(upstreams, monkeypatch):
    from weathergpt.config import reset_settings
    monkeypatch.setenv("IMD_API_KEY", "k")
    monkeypatch.setenv("IMD_EMAIL", "me@example.com")
    monkeypatch.setenv("IMD_PASSWORD", "wrong")
    reset_settings()
    with pytest.raises(imd_client.IMDError) as exc:
        imd_client.fetch("current_weather")
    assert exc.value.reason == "login_rejected"
    assert imd_client.status()["last_renewal_error"]["reason"] == "login_rejected"


def test_proxy_without_credentials_is_503(client, upstreams, admin):
    r = client.get("/v2/imd/tourist_forecast", headers=admin)
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
        imd_client.fetch("sea_bulletin")
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
