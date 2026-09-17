"""Offline unit tests for the fusion engine — no network, no API keys."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from services import fusion
from services.fusion import PROVIDER_WEIGHTS, ProviderReading, fuse_readings, reading_from_open_meteo_current


def _r(name, temp, **kw):
    return ProviderReading(name=name, weight=PROVIDER_WEIGHTS[name], temp=temp, **kw)


def test_priority_order_open_meteo_then_accuweather():
    ranked = sorted(PROVIDER_WEIGHTS, key=PROVIDER_WEIGHTS.get, reverse=True)
    assert ranked[0] == "Open-Meteo (ECMWF)"
    assert ranked[1] == "AccuWeather"
    assert PROVIDER_WEIGHTS["AccuWeather"] > max(
        PROVIDER_WEIGHTS[n] for n in ("WeatherAPI.com", "Tomorrow.io", "OpenWeatherMap")
    )


def test_weighted_mean_uses_weights():
    fused = fuse_readings([
        _r("Open-Meteo (ECMWF)", 30.0, code=1),
        _r("AccuWeather", 32.0, condition="Sunny"),
    ])
    # (30*2.0 + 32*1.5) / 3.5 = 30.857
    assert fused["temperature_2m"] == pytest.approx(30.9, abs=0.05)
    assert fused["providers_used"] == ["Open-Meteo (ECMWF)", "AccuWeather"]
    assert fused["weathercode"] == 1
    assert fused["condition"] == "Mainly clear"  # from highest-weighted provider with a condition
    assert fused["confidence"] == "medium"
    assert fused["warning"] is None


def test_missing_metrics_are_not_defaulted():
    fused = fuse_readings([
        _r("Open-Meteo (ECMWF)", 30.0, humidity=None),
        _r("OpenWeatherMap", 30.0, humidity=40),
    ])
    assert fused["relative_humidity_2m"] == 40  # only provider that reported it
    assert fused["wind_speed_10m"] is None


def test_outlier_excluded_from_mean_but_reported():
    fused = fuse_readings([
        _r("Open-Meteo (ECMWF)", 30.0),
        _r("AccuWeather", 30.5),
        _r("WeatherAPI.com", 45.0),  # implausible vs baseline
    ])
    assert "WeatherAPI.com" not in fused["providers_used"]
    flagged = [p for p in fused["providers"] if p["name"] == "WeatherAPI.com"][0]
    assert flagged["outlier"] is True
    assert fused["temperature_2m"] == pytest.approx(30.2, abs=0.05)


def test_single_source():
    fused = fuse_readings([_r("Open-Meteo (ECMWF)", 28.4, code=61)])
    assert fused["temperature_2m"] == 28.4
    assert fused["confidence"] == "single-source"
    assert fused["warning"] == "Only one provider returned usable data."
    assert fused["condition"] == "Slight rain"


def test_no_readings_is_error():
    assert "error" in fuse_readings([])


def test_reading_from_open_meteo_handles_both_code_keys():
    old = reading_from_open_meteo_current({"temperature_2m": 25, "weathercode": 3})
    new = reading_from_open_meteo_current({"temperature_2m": 25, "weather_code": 3})
    assert old.code == new.code == 3
    assert reading_from_open_meteo_current({}) is None


def test_configured_providers_ignores_placeholder_keys(monkeypatch):
    for env in ("ACCUWEATHER_KEY", "WEATHERAPI_KEY", "TOMORROW_KEY", "OPENWEATHER_KEY"):
        monkeypatch.delenv(env, raising=False)
        monkeypatch.delenv("VITE_" + env, raising=False)
    monkeypatch.setenv("ACCUWEATHER_KEY", "your_accuweather_key_here")
    assert fusion.configured_providers() == ["Open-Meteo (ECMWF)"]
    monkeypatch.setenv("ACCUWEATHER_KEY", "real-key")
    assert fusion.configured_providers() == ["Open-Meteo (ECMWF)", "AccuWeather"]


def test_fuse_current_weather_uses_prefetched_open_meteo(monkeypatch):
    """When Open-Meteo `current` is supplied and no keys are set, no HTTP call is made."""
    for env in ("ACCUWEATHER_KEY", "WEATHERAPI_KEY", "TOMORROW_KEY", "OPENWEATHER_KEY"):
        monkeypatch.delenv(env, raising=False)
        monkeypatch.delenv("VITE_" + env, raising=False)

    def boom(*a, **k):
        raise AssertionError("network should not be used")

    monkeypatch.setattr(fusion.httpx, "Client", boom)
    fused = fusion.fuse_current_weather(0, 0, open_meteo_current={"temperature_2m": 21.0, "weather_code": 0})
    assert fused["temperature_2m"] == 21.0
    assert fused["providers_used"] == ["Open-Meteo (ECMWF)"]
