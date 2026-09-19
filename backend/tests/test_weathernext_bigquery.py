"""Offline tests for the live WeatherNext BigQuery path.

No Google network calls: credentials and the BigQuery client are faked. The
tests pin down the contract the deployment plan relies on:

- credential chain precedence: SA JSON -> ADC -> OAuth refresh token
- every query is partition-filtered, parameterised, column-explicit and capped
- native units are converted once; derived fields are labelled; nothing is invented
- failures surface as honest ``fallback_reasons`` and never crash the chain
- ``/v2/weather?requested_source=weathernext`` returns ``selected_source=weathernext``
"""

from __future__ import annotations

import json
import math
import os
import sys
import types
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services import config as config_module  # noqa: E402
from services import weathernext_auth as auth  # noqa: E402
from services import weathernext_bigquery as wbq  # noqa: E402
from services.weathernext_normalize import (  # noqa: E402
    derive_condition,
    normalize_point_forecast,
    rain_probability_lower_bound,
    relative_humidity_from_dewpoint,
)

TABLE = "cool-archery-296710.weathernext.weathernext_3_0_0_0p1deg"
NOW = datetime(2026, 9, 19, 10, 30, tzinfo=timezone.utc)
SA_JSON = json.dumps({
    "type": "service_account",
    "project_id": "cool-archery-296710",
    "client_email": "weathergpt-backend@cool-archery-296710.iam.gserviceaccount.com",
    "private_key": "-----BEGIN PRIVATE KEY-----\nnot-a-real-key\n-----END PRIVATE KEY-----\n",
    "token_uri": "https://oauth2.googleapis.com/token",
})

WEATHERNEXT_ENV = {
    "WEATHERNEXT_ENABLED": "1",
    "WEATHERNEXT_AUTH_MODE": "oauth",  # what production runs with today
    "WEATHERNEXT_SURFACE": "bigquery",
    "GOOGLE_CLOUD_PROJECT": "cool-archery-296710",
    "GOOGLE_CLOUD_QUOTA_PROJECT": "cool-archery-296710",
    "WEATHERNEXT_TABLE": TABLE,  # plan alias for WEATHERNEXT_BQ_SURFACE_TABLE
    "WEATHERNEXT_BQ_COLUMN_PROFILE": "extended",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def clean_state(monkeypatch):
    """Isolate env/config/credential/adapter singletons per test."""
    for key in list(os.environ):
        if key.startswith(("WEATHERNEXT_", "GOOGLE_", "VERCEL", "WEATHER_PROVIDER")):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("VERCEL", "1")  # never probe the GCE metadata server in tests
    auth.reset_credentials_cache()
    wbq.set_bigquery_adapter(None)
    config_module.reload_config()
    from services import forecast, forecast_cache
    forecast_cache.clear_cache()
    forecast._forecast_service = None
    yield monkeypatch
    auth.reset_credentials_cache()
    wbq.set_bigquery_adapter(None)
    config_module.reload_config()
    forecast_cache.clear_cache()
    forecast._forecast_service = None


def _set_env(monkeypatch, **extra):
    for key, value in {**WEATHERNEXT_ENV, **extra}.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    return config_module.reload_config()


def _synthetic_steps(init_time: datetime, hours: int = 96) -> list[dict]:
    """Native-unit rows shaped like the BigQuery ``steps`` ARRAY<STRUCT>."""
    steps = []
    for h in range(1, hours + 1):
        t = init_time + timedelta(hours=h)
        temp_k = 300.15 + 4.0 * math.sin((h % 24) / 24 * 2 * math.pi)  # 27 C +/- 4
        rain_m = 0.0032 if 30 <= h <= 33 else 0.0  # 3.2 mm/h burst
        steps.append({
            "time": t,
            "temperature_2m_mean": temp_k,
            "temperature_2m_p10": temp_k - 1.5,
            "temperature_2m_p25": temp_k - 0.8,
            "temperature_2m_p50": temp_k,
            "temperature_2m_p75": temp_k + 0.8,
            "temperature_2m_p90": temp_k + 1.5,
            "dewpoint_temperature_2m_mean": 295.15,  # 22 C
            "total_precipitation_1hr_mean": rain_m,
            "total_precipitation_1hr_p10": 0.0,
            "total_precipitation_1hr_p25": 0.0,
            "total_precipitation_1hr_p50": rain_m * 0.8,
            "total_precipitation_1hr_p75": rain_m * 1.2,
            "total_precipitation_1hr_p90": rain_m * 1.5 if rain_m else 0.00005,
            "wind_speed_10m_mean": 4.0,   # 14.4 km/h
            "wind_speed_10m_p90": 7.0,
            "u_component_of_wind_10m_mean": -4.0,  # wind blowing towards west => from east (90 deg)
            "v_component_of_wind_10m_mean": 0.0,
            "total_cloud_cover_mean": 0.6,
            "mean_sea_level_pressure_mean": 100820.0,
        })
    return steps


class FakeJob:
    def __init__(self, rows, *, dry_run=False, error=None, bytes_billed=176_160_768):
        self._rows = rows
        self._error = error
        self.job_id = "job_fake_123"
        self.cache_hit = False
        self.total_bytes_processed = 4_190_000_000 if dry_run else bytes_billed
        self.total_bytes_billed = None if dry_run else bytes_billed
        self.slot_millis = 1200
        self.cancelled = False

    def result(self, timeout=None):
        if self._error:
            raise self._error
        return iter(self._rows)

    def cancel(self):
        self.cancelled = True


class FakeBigQueryClient:
    """Records every job; answers with rows keyed by the @init_time parameter."""

    def __init__(self, rows_by_init: dict, error=None):
        self.rows_by_init = rows_by_init
        self.error = error
        self.calls: list[dict] = []

    def query(self, sql, job_config=None, location=None):
        params = {p.name: p.value for p in job_config.query_parameters}
        self.calls.append({"sql": sql, "params": params, "config": job_config, "location": location})
        if self.error:
            if isinstance(self.error, Exception) and getattr(self.error, "_at_submit", False):
                raise self.error
            return FakeJob([], error=self.error)
        if job_config.dry_run:
            return FakeJob([], dry_run=True)
        init = params["init_time"]
        rows = self.rows_by_init.get(init, [])
        return FakeJob(rows)


def _row_for(init_time: datetime, hours: int = 96) -> dict:
    return {
        "cell_lat": 22.55,
        "cell_lon": 72.95,
        "distance_m": 1234.5,
        "steps": _synthetic_steps(init_time, hours),
    }


def _install_fake_adapter(monkeypatch, client: FakeBigQueryClient, *, now: datetime = NOW):
    bundle = auth.CredentialBundle(credentials=object(), source="service_account_json", project="cool-archery-296710", quota_project="cool-archery-296710")
    adapter = wbq.WeatherNextBigQueryAdapter(
        credentials_getter=lambda cfg=None, **kw: bundle,
        client_factory=lambda b, cfg: client,
        clock=lambda: now,
    )
    wbq.set_bigquery_adapter(adapter)
    return adapter


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def test_table_alias_and_profile_from_env(clean_state):
    cfg = _set_env(clean_state, GOOGLE_APPLICATION_CREDENTIALS_JSON=SA_JSON).weathernext
    assert cfg.bq.surface_table == TABLE
    assert cfg.bq.column_profile == "extended"
    assert "u_component_of_wind_10m_mean" in cfg.bq.columns
    assert cfg.has_service_account_json is True
    assert cfg.credential_sources() == ["service_account_json"]
    assert cfg.validate() == []


def test_oauth_mode_without_oauth_vars_is_valid_when_sa_json_present(clean_state):
    """Production runs auth_mode=oauth; adding SA JSON must not require the OAuth triple."""
    cfg = _set_env(clean_state, GOOGLE_APPLICATION_CREDENTIALS_JSON=SA_JSON).weathernext
    assert cfg.auth_mode == "oauth"
    assert cfg.validate() == []
    status = auth.validate_credentials(cfg)
    assert status.status == auth.AuthStatus.CONFIGURED
    assert status.redacted_info["has_service_account_json"] is True
    # Secrets never leak into the redacted view
    assert "private_key" not in json.dumps(status.redacted_info)


def test_oauth_mode_without_any_source_reports_missing(clean_state):
    cfg = _set_env(clean_state).weathernext
    errors = cfg.validate()
    assert any("GOOGLE_OAUTH_REFRESH_TOKEN" in e for e in errors)
    assert auth.validate_credentials(cfg).status == auth.AuthStatus.INVALID_CONFIG


def test_credentials_json_in_file_var_is_rejected(clean_state):
    cfg = _set_env(clean_state, GOOGLE_APPLICATION_CREDENTIALS='{"type":"service_account"}').weathernext
    assert any("GOOGLE_APPLICATION_CREDENTIALS_JSON instead" in e for e in cfg.validate())


def test_default_bytes_cap_allows_single_partition(clean_state):
    cfg = _set_env(clean_state, GOOGLE_APPLICATION_CREDENTIALS_JSON=SA_JSON).weathernext
    # A tiny cap makes every point query fail (estimate is a pre-pruning upper bound)
    assert cfg.bq.max_bytes_billed >= 10 * 1024 ** 3
    cfg2 = _set_env(clean_state, GOOGLE_APPLICATION_CREDENTIALS_JSON=SA_JSON, WEATHERNEXT_BQ_MAX_BYTES_BILLED="1073741824").weathernext
    assert cfg2.bq.max_bytes_billed == 1024 ** 3


def test_freshness_budget_is_config_driven(clean_state):
    from services.forecast_models import get_weathernest_capability
    _set_env(clean_state, GOOGLE_APPLICATION_CREDENTIALS_JSON=SA_JSON)
    assert get_weathernest_capability().freshness_budget_hours == 24.0
    _set_env(clean_state, GOOGLE_APPLICATION_CREDENTIALS_JSON=SA_JSON, WEATHERNEXT_FRESHNESS_HOURS="30")
    assert get_weathernest_capability().freshness_budget_hours == 30.0


# ---------------------------------------------------------------------------
# Credential chain
# ---------------------------------------------------------------------------

def _fake_google(monkeypatch, *, sa_ok=True, oauth_ok=True, record=None):
    """Install fake google.oauth2 / google.auth modules capturing which path ran."""
    record = record if record is not None else []

    class FakeSACreds:
        def __init__(self, info):
            self.info = info
            self.quota_project_id = None

        @classmethod
        def from_service_account_info(cls, info, scopes=None):
            record.append("service_account_json")
            if not sa_ok:
                raise ValueError("bad key")
            return cls(info)

    class FakeUserCreds:
        def __init__(self, **kw):
            self.kw = kw
            self.quota_project_id = kw.get("quota_project_id")

        def refresh(self, request):
            record.append("oauth_refresh_token")
            if not oauth_ok:
                raise RuntimeError("invalid_grant: Token has been expired or revoked. ya29.SECRET")

    google = types.ModuleType("google")
    oauth2 = types.ModuleType("google.oauth2")
    sa_mod = types.ModuleType("google.oauth2.service_account")
    sa_mod.Credentials = FakeSACreds
    cred_mod = types.ModuleType("google.oauth2.credentials")
    cred_mod.Credentials = FakeUserCreds
    gauth = types.ModuleType("google.auth")

    def _default(scopes=None):
        record.append("adc")
        raise RuntimeError("no ADC")

    gauth.default = _default
    gauth.load_credentials_from_file = lambda path, scopes=None: (_ for _ in ()).throw(FileNotFoundError(path))
    transport = types.ModuleType("google.auth.transport")
    requests_mod = types.ModuleType("google.auth.transport.requests")
    requests_mod.Request = lambda: object()

    for name, mod in {
        "google": google,
        "google.oauth2": oauth2,
        "google.oauth2.service_account": sa_mod,
        "google.oauth2.credentials": cred_mod,
        "google.auth": gauth,
        "google.auth.transport": transport,
        "google.auth.transport.requests": requests_mod,
    }.items():
        monkeypatch.setitem(sys.modules, name, mod)
    return record


def test_chain_prefers_service_account_json_over_oauth(clean_state):
    cfg = _set_env(
        clean_state,
        GOOGLE_APPLICATION_CREDENTIALS_JSON=SA_JSON,
        GOOGLE_OAUTH_CLIENT_ID="764086051850-abc.apps.googleusercontent.com",
        GOOGLE_OAUTH_CLIENT_SECRET="secret",
        GOOGLE_OAUTH_REFRESH_TOKEN="1//refresh",
    ).weathernext
    record = _fake_google(clean_state)
    bundle = auth.get_bigquery_credentials(cfg)
    assert bundle.source == "service_account_json"
    assert bundle.project == "cool-archery-296710"
    assert bundle.principal_hint == "...cool-archery-296710.iam.gserviceaccount.com"
    assert record == ["service_account_json"]  # OAuth never touched
    # cached on second call
    assert auth.get_bigquery_credentials(cfg) is bundle
    assert auth.get_active_credential_source() == "service_account_json"


def test_chain_falls_back_to_oauth_when_sa_json_invalid(clean_state):
    cfg = _set_env(
        clean_state,
        GOOGLE_APPLICATION_CREDENTIALS_JSON=SA_JSON,
        GOOGLE_OAUTH_CLIENT_ID="764086051850-abc.apps.googleusercontent.com",
        GOOGLE_OAUTH_CLIENT_SECRET="secret",
        GOOGLE_OAUTH_REFRESH_TOKEN="1//refresh",
    ).weathernext
    record = _fake_google(clean_state, sa_ok=False)
    bundle = auth.get_bigquery_credentials(cfg)
    assert bundle.source == "oauth_refresh_token"
    assert record == ["service_account_json", "oauth_refresh_token"]
    assert bundle.credentials.kw["client_id"].startswith("764086051850")
    assert bundle.credentials.kw["quota_project_id"] == "cool-archery-296710"


def test_chain_reports_live_credentials_required_without_secrets(clean_state):
    cfg = _set_env(
        clean_state,
        GOOGLE_OAUTH_CLIENT_ID="764086051850-abc.apps.googleusercontent.com",
        GOOGLE_OAUTH_CLIENT_SECRET="secret",
        GOOGLE_OAUTH_REFRESH_TOKEN="1//refresh",
    ).weathernext
    _fake_google(clean_state, oauth_ok=False)
    with pytest.raises(auth.CredentialsUnavailable) as excinfo:
        auth.get_bigquery_credentials(cfg)
    err = excinfo.value
    assert err.code == "live_credentials_required"
    flat = json.dumps(err.attempts)
    assert "oauth_refresh_token" in flat
    assert "ya29" not in flat and "[redacted-token]" in flat
    status = auth.get_credentials_factory_status()
    assert status["last_failure"]["attempts"]


# ---------------------------------------------------------------------------
# Query builder / run selection
# ---------------------------------------------------------------------------

def test_point_query_obeys_cost_rules():
    init = datetime(2026, 9, 19, 0, tzinfo=timezone.utc)
    cols = config_module.BQ_COLUMN_PROFILES["standard"]
    sql, params = wbq.build_point_query(TABLE, cols, 22.56, 72.95, init, 72, 9.0)
    assert "SELECT *" not in sql.upper()
    assert "t.init_time = @init_time" in sql            # exact partition filter
    assert "ST_DWITHIN(t.geography" in sql             # clustered column predicate
    assert f"`{TABLE}`" in sql
    assert "f.temperature_2m_mean" in sql and "f.forecast" not in sql
    names = {p[0] for p in params}
    assert names == {"lat", "lon", "init_time", "max_time", "radius_m"}
    by_name = {p[0]: p for p in params}
    assert by_name["init_time"][1] == "TIMESTAMP" and by_name["init_time"][2] == init
    assert by_name["max_time"][2] == init + timedelta(hours=72)
    assert by_name["radius_m"][2] == 9000.0
    assert "72.95" not in sql and "22.56" not in sql  # parameterised, never interpolated


def test_point_query_rejects_bad_identifiers():
    init = datetime(2026, 9, 19, 0, tzinfo=timezone.utc)
    with pytest.raises(wbq.WeatherNextQueryError) as e1:
        wbq.build_point_query("weathernext_3_0_0_0p1deg", ("temperature_2m_mean",), 22, 72, init, 24, 9)
    assert e1.value.code == "invalid_table"
    with pytest.raises(wbq.WeatherNextQueryError) as e2:
        wbq.build_point_query(TABLE, ("temperature_2m_mean; DROP TABLE x",), 22, 72, init, 24, 9)
    assert e2.value.code == "invalid_columns"


def test_candidate_runs_prefer_newest_delivered_synoptic_run():
    # 10:30Z with 7 h delivery latency -> latest allowed 03:30Z -> 00Z today, then 18Z, 12Z yesterday
    cands = wbq.candidate_init_times(NOW, (0, 6, 12, 18), 7.0, 3, 72, 360)
    assert [c.isoformat() for c in cands] == [
        "2026-09-19T00:00:00+00:00",
        "2026-09-18T18:00:00+00:00",
        "2026-09-18T12:00:00+00:00",
    ]
    # Interim (hourly) runs only carry 48 h - excluded for a 72 h request, allowed for 24 h
    interim = wbq.candidate_init_times(NOW, tuple(range(24)), 7.0, 2, 72, 360)
    assert all(c.hour % 6 == 0 for c in interim)
    short = wbq.candidate_init_times(NOW, tuple(range(24)), 7.0, 1, 24, 360)
    assert short[0].hour == 3
    # Pinned run id bypasses policy
    pinned = wbq.candidate_init_times(NOW, (0, 12), 7.0, 3, 72, 360, run_id="weathernext_3_0_0_2026091806")
    assert pinned == [datetime(2026, 9, 18, 6, tzinfo=timezone.utc)]
    assert wbq.parse_run_id("2026-09-18T06:00:00Z") == pinned[0]
    assert wbq.parse_run_id("garbage") is None


# ---------------------------------------------------------------------------
# Adapter: run stepping, cost diagnostics, error classification
# ---------------------------------------------------------------------------

def test_adapter_steps_back_when_newest_partition_empty(clean_state):
    _set_env(clean_state, GOOGLE_APPLICATION_CREDENTIALS_JSON=SA_JSON)
    init_18 = datetime(2026, 9, 18, 18, tzinfo=timezone.utc)
    client = FakeBigQueryClient({init_18: [_row_for(init_18)]})
    adapter = _install_fake_adapter(clean_state, client)

    result = adapter.fetch_point_forecast(22.56, 72.95, horizon_hours=72)
    assert result.init_time == init_18
    assert result.run_id == "weathernext_3_0_0_2026091818"
    assert result.attempted_inits == ["weathernext_3_0_0_2026091900", "weathernext_3_0_0_2026091818"]
    assert result.distance_km == 1.234
    assert result.diagnostics.total_bytes_billed == 176_160_768
    assert adapter.query_count == 2
    # every job carried the cap and the partition parameter
    for call in client.calls:
        assert call["config"].maximum_bytes_billed == config_module.DEFAULT_BQ_MAX_BYTES_BILLED
        assert "init_time" in call["params"]
        assert call["location"] == "US"


def test_adapter_reports_no_recent_run_when_nothing_delivered(clean_state):
    _set_env(clean_state, GOOGLE_APPLICATION_CREDENTIALS_JSON=SA_JSON)
    client = FakeBigQueryClient({})
    adapter = _install_fake_adapter(clean_state, client)
    with pytest.raises(wbq.WeatherNextQueryError) as excinfo:
        adapter.fetch_point_forecast(22.56, 72.95, horizon_hours=72)
    assert excinfo.value.code == "no_recent_run"
    assert len(excinfo.value.details["attempted_runs"]) == 3


def test_adapter_dry_run_estimate(clean_state):
    _set_env(clean_state, GOOGLE_APPLICATION_CREDENTIALS_JSON=SA_JSON)
    adapter = _install_fake_adapter(clean_state, FakeBigQueryClient({}))
    est = adapter.estimate_point_query(22.56, 72.95, horizon_hours=72)
    assert est["estimated_bytes_upper_bound"] == 4_190_000_000
    assert est["within_cap"] is True
    assert adapter.query_count == 0  # dry runs are not billed / counted


def test_error_classification_is_stable_and_redacted():
    from google.api_core import exceptions as gexc

    assert wbq.classify_bigquery_exception(gexc.Forbidden("Access Denied: Table x: User does not have permission")).code == "permission_denied"
    assert wbq.classify_bigquery_exception(gexc.Forbidden("Billing has not been enabled for this project")).code == "billing_disabled"
    assert wbq.classify_bigquery_exception(gexc.NotFound("Not found: Table cool:weathernext.x")).code == "table_not_found"
    limit = wbq.classify_bigquery_exception(gexc.BadRequest("Query exceeded limit for bytes billed: 1000000. 10485760 or higher required."))
    assert limit.code == "bytes_billed_limit_exceeded"
    assert limit.details["required_bytes"] == 10485760
    assert wbq.classify_bigquery_exception(gexc.BadRequest("Unrecognized name: temperature_2m_mean at [3:5]")).code == "schema_mismatch"
    assert wbq.classify_bigquery_exception(gexc.TooManyRequests("Exceeded rate limits")).code == "quota_exceeded"
    import concurrent.futures
    assert wbq.classify_bigquery_exception(concurrent.futures.TimeoutError()).code == "query_timeout"
    assert wbq.classify_bigquery_exception(auth.CredentialsUnavailable("none")).code == "live_credentials_required"


def test_adapter_timeout_cancels_job(clean_state):
    import concurrent.futures
    _set_env(clean_state, GOOGLE_APPLICATION_CREDENTIALS_JSON=SA_JSON)
    client = FakeBigQueryClient({}, error=concurrent.futures.TimeoutError())
    adapter = _install_fake_adapter(clean_state, client)
    with pytest.raises(wbq.WeatherNextQueryError) as excinfo:
        adapter.fetch_point_forecast(22.56, 72.95, horizon_hours=72)
    assert excinfo.value.code == "query_timeout"
    assert adapter.last_error["code"] == "query_timeout"


# ---------------------------------------------------------------------------
# Normalisation science
# ---------------------------------------------------------------------------

def test_unit_conversions_and_derived_fields():
    assert relative_humidity_from_dewpoint(27.0, 22.0) == pytest.approx(74.3, abs=0.5)
    assert relative_humidity_from_dewpoint(20.0, 20.0) == 100.0
    assert relative_humidity_from_dewpoint(None, 20.0) is None
    assert derive_condition(0.0, 10.0) == (0, "Clear sky")
    assert derive_condition(0.0, 60.0) == (2, "Partly cloudy")
    assert derive_condition(3.2, 60.0) == (63, "Moderate rain")
    assert derive_condition(12.0, None) == (65, "Heavy rain")
    assert derive_condition(0.0, None) == (None, None)  # no cloud cover -> no invented sky state
    # quantile brackets are lower bounds
    assert rain_probability_lower_bound({"p10": 0.5, "p50": 1, "p90": 2}) == 90.0
    assert rain_probability_lower_bound({"p10": 0.0, "p50": 0.2, "p90": 2}) == 50.0
    assert rain_probability_lower_bound({"p50": 0.0, "p90": 0.05}) == 0.0
    assert rain_probability_lower_bound({}) is None


def test_normalize_point_forecast_builds_honest_payload(clean_state):
    _set_env(clean_state, GOOGLE_APPLICATION_CREDENTIALS_JSON=SA_JSON)
    init = datetime(2026, 9, 19, 0, tzinfo=timezone.utc)
    result = wbq.PointForecastResult(
        table=TABLE, init_time=init, horizon_hours=96, run_horizon_hours=360,
        cell_lat=22.55, cell_lon=72.95, distance_km=1.234, resolution_deg=0.1,
        columns=config_module.BQ_COLUMN_PROFILES["extended"],
        steps=wbq._coerce_steps(_synthetic_steps(init, 96)),
        diagnostics=wbq.QueryDiagnostics(job_id="j1", total_bytes_billed=176_160_768, rows=1),
        attempted_inits=["weathernext_3_0_0_2026091900"], credential_source="service_account_json",
    )
    fc = normalize_point_forecast(result, lat=22.56, lon=72.95, requested_source="weathernext", mode="researcher", forecast_days=3, now=NOW)

    prov = fc.provenance
    assert prov.selected_source.value == "weathernext"
    assert prov.model == "weathernext_3_0_0" and prov.run_id == "weathernext_3_0_0_2026091900"
    assert prov.init_time_utc == init
    assert prov.freshness_status.value == "fresh" and prov.is_stale is False
    assert prov.spatial_method == "nearest_cell_centre" and prov.distance_km == 1.234
    assert prov.sampled_lat == 22.55 and prov.requested_lat == 22.56
    assert prov.table == TABLE and prov.horizon_hours == 96
    assert prov.expected_member_count == 64 and prov.valid_member_count is None
    assert prov.query_diagnostics["total_bytes_billed"] == 176_160_768
    assert prov.query_diagnostics["credential_source"] == "service_account_json"
    assert "lower_bound" in prov.methods["precipitation_probability"]

    # current = nearest step to now (10:30Z -> 10Z or 11Z), a forecast estimate
    assert abs((fc.current.time_utc - NOW).total_seconds()) <= 1800
    assert fc.current.is_ensemble_mean is True
    assert fc.current.pressure_type == "msl" and fc.current.pressure_hpa == pytest.approx(1008.2)
    assert fc.current.wind_speed_kmh == pytest.approx(14.4)
    assert fc.current.wind_direction_deg == pytest.approx(90.0)  # u=-4, v=0 -> from the east
    # Magnus RH for the actual (T, Td) pair of the selected hour, cross-checked independently
    assert fc.current.humidity_percent == pytest.approx(relative_humidity_from_dewpoint(fc.current.temperature_c, 22.0), abs=0.6)
    assert 60 < fc.current.humidity_percent < 80
    assert 22 < fc.current.temperature_c < 32

    # rain burst at lead 30-33 h: 3.2 mm/h converted from metres, moderate rain, p50 wet -> >= 50 %
    burst = [p for p in fc.hourly if p.precipitation_mm and p.precipitation_mm > 3]
    assert len(burst) == 4
    assert burst[0].weather_code == 63 and burst[0].precipitation_probability == 50.0
    dry = [p for p in fc.hourly if not p.precipitation_mm][0]
    assert dry.precipitation_probability == 0.0 and dry.weather_code in (1, 2)

    # daily: local (UTC+5 solar approx) buckets starting today, 3 days, honest coverage flags
    assert fc.location["utc_offset_hours_approx"] == 5
    assert [d["date"] for d in fc.daily][:3] == ["2026-09-19", "2026-09-20", "2026-09-21"]
    day = fc.daily[0]
    assert day["high_c"] > day["low_c"]
    assert day["high_p90_c"] >= day["high_c"] and day["low_p10_c"] <= day["low_c"]
    assert day["rain_mm"] == pytest.approx(0.0) or day["rain_mm"] >= 0
    assert fc.daily[1]["covers_full_day"] is True and fc.daily[1]["precipitation_interval"] == "24h"
    assert fc.daily[1]["rain_mm"] == pytest.approx(12.8, abs=0.05)  # 4 x 3.2 mm ensemble-mean, summed (linear)
    assert fc.daily[1]["rain_probability"] == 50.0
    assert day["sunrise"] is None  # not a WeatherNext product - never invented

    # ensemble block: statistics only, no member data, bounded series
    ens = fc.ensemble
    assert ens["members"] == 64 and ens["member_data"] is False
    temp_series = ens["series"]["temperature_2m"]
    assert temp_series["units"] == "C" and set(temp_series["statistics"]) >= {"mean", "p10", "p90"}
    assert len(temp_series["values"]) == 96
    assert temp_series["values"][0]["p10"] < temp_series["values"][0]["mean"] < temp_series["values"][0]["p90"]
    assert ens["series"]["total_precipitation_1hr"]["units"] == "mm"


# ---------------------------------------------------------------------------
# Provider + router end-to-end (fake BigQuery)
# ---------------------------------------------------------------------------

def _client_for_now(now: datetime = NOW, hours: int = 120) -> FakeBigQueryClient:
    init = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=7)
    init = init.replace(hour=(init.hour // 6) * 6)
    return FakeBigQueryClient({init: [_row_for(init, hours)]})


def test_v2_weather_requested_source_weathernext_is_live(clean_state):
    _set_env(clean_state, GOOGLE_APPLICATION_CREDENTIALS_JSON=SA_JSON)
    client = _client_for_now()
    _install_fake_adapter(clean_state, client)

    from fastapi.testclient import TestClient
    from main import app

    with TestClient(app) as tc:
        res = tc.get("/v2/weather", params={"lat": 22.56, "lon": 72.95, "mode": "researcher", "requested_source": "weathernext"})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["status"] == "ok"
        prov = body["provenance"]
        assert prov["selected_source"] == "weathernext"
        assert prov["requested_source"] == "weathernext"
        assert not any(r.get("provider") == "weathernext" for r in prov["fallback_reasons"])
        assert prov["run_id"].startswith("weathernext_3_0_0_")
        assert prov["table"] == TABLE
        assert prov["query_diagnostics"]["total_bytes_billed"] == 176_160_768
        assert body["source"] == "weathernext"
        assert body["current"]["temperature_c"] is not None
        assert len(body["hourly"]) == 24 and len(body["daily"]) == 3

        spread = body["temperature_spread"]
        assert spread and spread["p10_c"] < spread["p90_c"] and spread["members"] == 64 and spread["source"] == "weathernext"
        rain = body["precip_next_24h"]
        assert rain and rain["complete"] is True and rain["statistic"] == "ensemble_mean" and rain["total_mm"] >= 0

        # second call inside the same 0.1 deg cell is served from cache: no extra BigQuery job
        calls_before = len(client.calls)
        res2 = tc.get("/v2/weather", params={"lat": 22.58, "lon": 72.97, "requested_source": "weathernext"})
        assert res2.status_code == 200
        assert len(client.calls) == calls_before
        assert res2.json()["provenance"]["query_diagnostics"]["served_from_cache"] is True

        # auto mode also selects WeatherNext (IMD unconfigured, WeatherNext next in priority)
        res3 = tc.get("/v2/weather", params={"lat": 22.56, "lon": 72.95})
        assert res3.json()["provenance"]["selected_source"] == "weathernext"

        # health: eligible, no reason
        health = tc.get("/v2/weather/health").json()
        wn = health["provider_health"]["weathernext"]
        assert wn["configured"] is True and wn["eligible"] is True and wn["reason"] is None
        assert health["weathernext_bigquery"]["query_count"] >= 1
        assert health["weathernext_auth"]["status"] in ("configured", "ready")


def test_v2_weather_series_returns_requested_statistic(clean_state):
    _set_env(clean_state, GOOGLE_APPLICATION_CREDENTIALS_JSON=SA_JSON)
    _install_fake_adapter(clean_state, _client_for_now())

    from fastapi.testclient import TestClient
    from main import app

    with TestClient(app) as tc:
        res = tc.get("/v2/weather/series", params={"lat": 22.56, "lon": 72.95, "variable": "temperature_2m", "statistic": "p90", "requested_source": "weathernext"})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["status"] == "ok"
        assert body["units"] == "C" and "p90" in body["available_statistics"]
        assert body["values"] and body["values"][0]["value"] == body["values"][0]["p90"]
        assert body["points"]  # legacy shape preserved
        assert body["run_id"].startswith("weathernext_3_0_0_")

        res_bad = tc.get("/v2/weather/series", params={"lat": 22.56, "lon": 72.95, "variable": "temperature_2m", "statistic": "p99"})
        assert res_bad.status_code == 400


def test_v2_weather_without_credentials_falls_back_honestly(clean_state):
    """No credential source configured -> honest fallback with table in the reason."""
    _set_env(
        clean_state,
        GOOGLE_OAUTH_CLIENT_ID="764086051850-abc.apps.googleusercontent.com",
        GOOGLE_OAUTH_CLIENT_SECRET="secret",
        GOOGLE_OAUTH_REFRESH_TOKEN="1//refresh",
    )
    _fake_google(clean_state, oauth_ok=False)
    # Real adapter, real chain; only Google modules are faked (refresh fails)
    from fastapi.testclient import TestClient
    from main import app

    with TestClient(app) as tc:
        res = tc.get("/v2/weather", params={"lat": 22.56, "lon": 72.95, "mode": "researcher", "requested_source": "weathernext"})
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "unavailable"  # pinned source never substitutes another provider
        assert body["selected_source"] == "unavailable"
        reasons = [r for r in body["fallback_reasons"] if r["provider"] == "weathernext"]
        assert reasons and reasons[0]["reason"] == "live_credentials_required"
        assert reasons[0]["table"] == TABLE and reasons[0]["surface"] == "bigquery"
        assert "ya29" not in res.text and "1//refresh" not in res.text and "secret" not in json.dumps(reasons)

        series = tc.get("/v2/weather/series", params={"lat": 22.56, "lon": 72.95, "variable": "temperature_2m"}).json()
        assert series["status"] == "unavailable" and "live_credentials_required" in series["error"]


def test_v2_weather_permission_denied_does_not_trip_breaker(clean_state):
    from google.api_core import exceptions as gexc
    _set_env(clean_state, GOOGLE_APPLICATION_CREDENTIALS_JSON=SA_JSON)
    client = FakeBigQueryClient({}, error=gexc.Forbidden("Access Denied: User does not have bigquery.tables.getData permission"))
    _install_fake_adapter(clean_state, client)

    from fastapi.testclient import TestClient
    from main import app

    with TestClient(app) as tc:
        for _ in range(6):
            body = tc.get("/v2/weather", params={"lat": 22.56, "lon": 72.95, "requested_source": "weathernext"}).json()
        reasons = [r for r in body["fallback_reasons"] if r["provider"] == "weathernext"]
        assert reasons[0]["reason"] == "permission_denied"  # not circuit_breaker_open
        assert reasons[0]["table"] == TABLE

        # auto mode degrades to a lower-priority provider with the reason attached (network permitting)
        health = tc.get("/v2/weather/health").json()
        assert health["provider_health"]["weathernext"]["circuit_breaker_open"] is False


def test_bytes_cap_violation_surfaces_required_bytes(clean_state):
    from google.api_core import exceptions as gexc
    _set_env(clean_state, GOOGLE_APPLICATION_CREDENTIALS_JSON=SA_JSON, WEATHERNEXT_BQ_MAX_BYTES_BILLED="1000000")
    client = FakeBigQueryClient({}, error=gexc.BadRequest("Query exceeded limit for bytes billed: 1000000. 4194304000 or higher required."))
    _install_fake_adapter(clean_state, client)

    from services.forecast import get_forecast_service
    result = get_forecast_service().select_forecast(lat=22.56, lon=72.95, requested_source="weathernext")
    assert result.forecast is None
    reason = result.fallback_reasons[-1]
    assert reason["reason"] == "bytes_billed_limit_exceeded"
    assert reason["required_bytes"] == 4194304000


def test_legacy_weather_endpoint_accepts_requested_source(clean_state):
    _set_env(clean_state, GOOGLE_APPLICATION_CREDENTIALS_JSON=SA_JSON)
    _install_fake_adapter(clean_state, _client_for_now())
    from fastapi.testclient import TestClient
    from main import app

    with TestClient(app) as tc:
        res = tc.get("/weather", params={"lat": 22.56, "lon": 72.95, "requested_source": "weathernext", "mode": "researcher"})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["source"] == "weathernext" and body["requested_source"] == "weathernext"
        assert body["temperature_c"] is not None


def test_dev_weathernext_probe_reports_dry_run(clean_state):
    _set_env(clean_state, GOOGLE_APPLICATION_CREDENTIALS_JSON=SA_JSON)
    _install_fake_adapter(clean_state, FakeBigQueryClient({}))
    _fake_google(clean_state)
    from fastapi.testclient import TestClient
    from main import app

    with TestClient(app) as tc:
        body = tc.get("/dev/weathernext", params={"probe": 1}).json()
        assert body["connectivity"]["status"] == "ready"
        assert body["connectivity"]["credential_source"] == "service_account_json"
        assert body["connectivity"]["dry_run"]["within_cap"] is True
        assert body["config"]["credential_sources"] == ["service_account_json"]
        assert "private_key" not in json.dumps(body)
