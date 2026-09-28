from datetime import datetime, timedelta, timezone

import pytest

from weathergpt.weathernext import bigquery
from weathergpt.weathernext.bigquery import (PointForecastResult, QueryDiagnostics, WeatherNextQueryError,
                                             build_point_query, candidate_init_times, parse_run_id)
from weathergpt.weathernext.normalize import normalize, rain_probability_lower_bound


def test_candidate_runs_respect_latency_synoptic_hours_and_expiry():
    now = datetime(2026, 9, 28, 12, 30, tzinfo=timezone.utc)
    runs = candidate_init_times(now, (0, 6, 12, 18), 7.0, 3, 168, 360, 24.0)
    assert runs == [datetime(2026, 9, 28, 0, tzinfo=timezone.utc), datetime(2026, 9, 27, 18, tzinfo=timezone.utc),
                    datetime(2026, 9, 27, 12, tzinfo=timezone.utc)]
    # A 6 h freshness budget expires runs older than 12 h: none qualify here, so nothing is queried.
    assert candidate_init_times(now, (0, 6, 12, 18), 7.0, 10, 168, 360, 6.0) == []


def test_run_id_parsing():
    assert parse_run_id("weathernext_3_0_0_2026092800") == datetime(2026, 9, 28, 0, tzinfo=timezone.utc)
    assert parse_run_id("2026092806").hour == 6
    with pytest.raises(WeatherNextQueryError):
        candidate_init_times(datetime.now(timezone.utc), (0,), 7, 3, 24, 360, 24, run_id="garbage")


def test_query_enforces_cost_rules():
    sql, params = build_point_query("p.d.t", ("temperature_2m_mean", "2m_temperature"), 23, 72,
                                    datetime(2026, 9, 28, tzinfo=timezone.utc), 48, 9)
    assert "t.init_time = @init_time" in sql and "ST_DWITHIN" in sql and "SELECT *" not in sql
    assert "f.`2m_temperature`" in sql and "f.temperature_2m_mean" in sql
    assert dict((n, v) for n, _, v in params)["radius_m"] == 9000.0
    with pytest.raises(WeatherNextQueryError):
        build_point_query("bad table", ("x",), 0, 0, datetime.now(timezone.utc), 1, 1)
    with pytest.raises(WeatherNextQueryError):
        build_point_query("p.d.t", ("x; drop",), 0, 0, datetime.now(timezone.utc), 1, 1)


def test_rain_probability_is_a_lower_bound():
    assert rain_probability_lower_bound({"p50": 0.2, "p90": 1.0}) == 50.0
    assert rain_probability_lower_bound({"p90": 0.0}) == 0.0
    assert rain_probability_lower_bound({}) is None


def test_normalize_converts_units_and_buckets_days_in_ist():
    init = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(hours=8)
    steps = [{"time": init + timedelta(hours=h), "temperature_2m_mean": 300.15, "temperature_2m_p10": 299.15,
              "temperature_2m_p90": 301.15, "dewpoint_temperature_2m_mean": 290.15,
              "total_precipitation_1hr_mean": 0.001, "total_precipitation_1hr_p50": 0.0,
              "total_precipitation_1hr_p90": 0.002, "wind_speed_10m_mean": 5.0, "total_cloud_cover_mean": 0.9,
              "mean_sea_level_pressure_mean": 100600.0} for h in range(1, 97)]
    raw = PointForecastResult(table="p.d.weathernext_3_0_0_0p1deg", model_id="weathernext_3_0_0", model_version="3.0.0",
                              init_time=init, horizon_hours=96, cell_lat=23.0, cell_lon=72.6, distance_km=1.2,
                              resolution_deg=0.1, columns=tuple(k for k in steps[0] if k != "time"), steps=steps,
                              diagnostics=QueryDiagnostics())
    fc = normalize(raw, lat=23.02, lon=72.57, forecast_days=3, freshness_hours=24)
    p = fc.hourly[0]
    assert p.temperature_c == 27.0 and p.precipitation_mm == 1.0 and p.wind_speed_kmh == 18.0
    assert p.pressure_hpa == 1006.0 and p.cloud_cover_percent == 90.0 and p.weather_code == 61
    assert p.precipitation_probability == 10.0
    assert fc.location["utc_offset_seconds"] == 19800 and fc.provenance.freshness_status == "fresh"
    assert fc.daily[0].high_p90_c == 28.0 and fc.provenance.run_id.startswith("weathernext_3_0_0_")


def test_wn2_uses_its_own_schema(monkeypatch):
    from weathergpt.config import settings, reset_settings
    monkeypatch.setenv("WEATHERNEXT_TABLE_2", "p.d.weathernext_2_0_0_mean")
    reset_settings()
    cfg = settings().weathernext
    assert cfg.columns_for("weathernext_2")[0] == "2m_temperature"
    assert cfg.table_for("wn2") == "p.d.weathernext_2_0_0_mean"


def test_not_configured_weathernext_is_skipped_quietly(upstreams, monkeypatch):
    from weathergpt.config import reset_settings
    from weathergpt.weather.service import service
    monkeypatch.setenv("WEATHERNEXT_ENABLED", "1")
    reset_settings()
    sel = service().select(23, 72)
    wn = next(r for r in sel.fallback_reasons if r["provider"] == "weathernext")
    assert wn["reason"] == "not_configured" and sel.degraded is False
    assert bigquery.NON_TRANSIENT >= {"permission_denied", "table_not_found"}
