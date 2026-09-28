"""Offline test harness: one fake transport answers every upstream by URL.

Real parsing, selection, supplementing and payload code runs; only the network is fake.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from weathergpt import http

IST = timezone(timedelta(hours=5, minutes=30))
CLEAR_ENV = ("GROQ_API_KEY", "IMD_API_KEY", "IMD_JWT_TOKEN", "WEATHERNEXT_ENABLED", "WEATHERNEXT_MOCK_DATA",
             "WEATHER_PROVIDER_PRIORITY", "TYPESAFE_API_KEY", "BHASHINI_USER_ID", "BHASHINI_ULCA_API_KEY",
             "BHASHINI_API_KEY", "ADMIN_TOKEN", "WEATHER_SUPPLEMENT_ENABLED", "WEATHER_ALERTS_ENABLED")


def open_meteo_payload(offset_seconds: int = 19800, tz: str = "Asia/Kolkata") -> dict:
    """Open-Meteo `timezone=auto` response: naive LOCAL timestamps, 8 days hourly."""
    now_local = (datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)).replace(tzinfo=None)
    start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    times = [start + timedelta(hours=h) for h in range(24 * 8)]
    dates = [(start + timedelta(days=d)).date().isoformat() for d in range(8)]
    n = len(times)
    return {
        "latitude": 23.0, "longitude": 72.6, "timezone": tz, "timezone_abbreviation": "IST",
        "utc_offset_seconds": offset_seconds, "elevation": 55,
        "current": {"time": now_local.strftime("%Y-%m-%dT%H:%M"), "temperature_2m": 31.0, "apparent_temperature": 34.0,
                    "relative_humidity_2m": 60, "weather_code": 2, "wind_speed_10m": 9.0, "wind_direction_10m": 250,
                    "wind_gusts_10m": 20.0, "pressure_msl": 1006.0, "surface_pressure": 1000.0, "precipitation": 0.0,
                    "cloud_cover": 40, "uv_index": 5.5},
        "hourly": {"time": [t.strftime("%Y-%m-%dT%H:%M") for t in times], "temperature_2m": [30.0] * n,
                   "apparent_temperature": [33.0] * n, "relative_humidity_2m": [60] * n,
                   "precipitation_probability": [10] * n, "precipitation": [0.0] * n, "weather_code": [1] * n,
                   "wind_speed_10m": [8.0] * n, "wind_direction_10m": [240] * n, "wind_gusts_10m": [15.0] * n,
                   "pressure_msl": [1006.0] * n, "cloud_cover": [20] * n, "uv_index": [3.0] * n},
        "daily": {"time": dates, "temperature_2m_max": [34.0] * 8, "temperature_2m_min": [25.0] * 8,
                  "precipitation_probability_max": [20] * 8, "precipitation_sum": [0.4] * 8, "weather_code": [2] * 8,
                  "sunrise": [f"{d}T06:24" for d in dates], "sunset": [f"{d}T18:21" for d in dates],
                  "uv_index_max": [8.0] * 8, "wind_speed_10m_max": [14.0] * 8},
    }


def imd_city_rows() -> list[dict]:
    today = datetime.now(IST).date()
    return [
        {"Date": today.isoformat(), "Station_Code": "42647", "Station_Name": "Ahmedabad", "Latitude": "23.07",
         "Longitude": "72.63", "Today_Max_temp": "33.4", "Today_Min_temp": "24.9", "Past_24_hrs_Rainfall": "Trace",
         "Relative_Humidity_at_0830": "78", "Relative_Humidity_at_1730": "52", "Sunrise_time": "06:25",
         "Sunset_time": "18:20", "Todays_Forecast_Max_Temp": "34", "Todays_Forecast_Min_temp": "25",
         "Todays_Forecast": "Partly cloudy sky with possibility of rain or Thunderstorm",
         "Day_2_Max_Temp": "33", "Day_2_Min_temp": "24", "Day_2_Forecast": "Thunderstorm with rain",
         "Day_3_Max_Temp": "NA", "Day_3_Min_temp": "24", "Day_3_Forecast": "Generally cloudy sky with light rain",
         **{f"Day_{n}_{k}": v for n in range(4, 8) for k, v in (("Max_Temp", "33"), ("Min_temp", "24"),
                                                              ("Forecast", "Mainly Clear sky"))}},
        {"Date": today.isoformat(), "Station_Code": "42182", "Station_Name": "New Delhi (Safdarjung)",
         "Latitude": "28.58", "Longitude": "77.20", "Todays_Forecast_Max_Temp": "36", "Todays_Forecast_Min_temp": "26",
         "Todays_Forecast": "Haze"},
    ]


def imd_current_rows() -> list[dict]:
    obs = datetime.now(timezone.utc) - timedelta(minutes=40)
    return [{"Station Id": "42647", "Station": "Ahmedabad", "Date of Observation": obs.date().isoformat(),
             "Time of Observation": obs.strftime("%H:%M"), "M.S.L.P": "1005.2", "Wind Direction": "270",
             "Wind Speed": "11", "Temperature": "32.8", "Weather Code": "05", "Nebulosity": "4",
             "Humidity": "55", "Last 24 hrs Rainfall": "0.0"}]


def district_warning_rows() -> list[dict]:
    today = datetime.now(IST).date().isoformat()
    return [{"Obj_id": "210", "Date": today, "UTC": "0600", "District": "AHMADABAD",
             "Day_1": "4,2", "Day_2": "1", "Day_3": "2", "Day_4": "1", "Day_5": "1",
             "Day1_Color": "2", "Day2_Color": "4", "Day3_Color": "3", "Day4_Color": "4", "Day5_Color": "4"},
            {"Obj_id": "573", "Date": today, "District": "NICOBAR", "Day_1": "1", "Day1_Color": "4"}]


def sachet_rows() -> list[dict]:
    end = (datetime.now(IST) + timedelta(hours=3)).strftime("%a %b %d %H:%M:%S IST %Y")
    start = (datetime.now(IST) - timedelta(hours=1)).strftime("%a %b %d %H:%M:%S IST %Y")
    return [
        {"identifier": 111, "severity": "WARNING", "effective_start_time": start, "effective_end_time": end,
         "disaster_type": "Thunderstorm", "area_description": "Ahmedabad district", "severity_color": "orange",
         "warning_message": "Thunderstorm with lightning likely in Ahmedabad", "actual_lang": "en",
         "centroid": "72.60,23.03", "area_covered": "8000", "alert_source": "IMD Ahmedabad"},
        {"identifier": 222, "severity": "ALERT", "effective_start_time": start, "effective_end_time": end,
         "disaster_type": "Lightning", "area_description": "Far away", "severity_color": "yellow",
         "warning_message": "Lightning elsewhere", "centroid": "88.3,22.5", "area_covered": "300"},
    ]


class FakeUpstreams:
    """Routes requests by URL fragment; records every call."""

    def __init__(self):
        self.calls: list[tuple[str, dict, dict]] = []
        self.open_meteo = open_meteo_payload()
        self.imd_rows = {"cityforecastloc": imd_city_rows(), "current_wx": imd_current_rows(),
                         "districtwarning": district_warning_rows(), "districtnowcast": []}
        self.imd_status: int = 200
        self.imd_error: str = ""
        self.sachet = sachet_rows()
        self.polygon = "<alert><polygon>22.8,72.3 23.3,72.3 23.3,72.9 22.8,72.9 22.8,72.3</polygon></alert>"
        self.fail: set[str] = set()

    def __call__(self, method, url, params, headers, body, timeout):
        self.calls.append((url, dict(params), dict(headers)))
        for key in self.fail:
            if key in url:
                raise http.httpx.ConnectError("offline")
        if "air-quality-api" in url:
            return self._json({"current": {"european_aqi": 42, "us_aqi": 88, "pm2_5": 21.5, "pm10": 40, "time": "x"}})
        if "archive-api" in url:
            var = params["daily"]
            start, end = int(params["start_date"][:4]), int(params["end_date"][:4])
            days = [f"{y}-01-01" for y in range(start, end + 1) for _ in range(365)]
            return self._json({"daily": {"time": days, var: [2.0] * len(days)}})
        if url.startswith("https://api.open-meteo.com"):
            return self._json(deepcopy(self.open_meteo))
        if "geocoding-api" in url:
            name = params["name"].lower()
            if name.startswith("pune"):
                return self._json({"results": [{"name": "Pune", "latitude": 18.52, "longitude": 73.85, "country_code": "IN"}]})
            if name.startswith("ahmedabad"):
                return self._json({"results": [{"name": "Ahmedabad", "latitude": 23.02, "longitude": 72.57, "country_code": "IN"}]})
            return self._json({})
        if "nominatim" in url and "reverse" in url:
            return self._json({"address": {"state_district": "Ahmedabad", "state": "Gujarat", "country_code": "in"}})
        if "nominatim" in url:
            return self._json([])
        if "FetchAllAlertDetails" in url:
            return self._json(self.sachet)
        if "FetchPolygonXMLFile" in url:
            if str(params.get("identifier")) == "111":
                return http.Reply(200, {"content-type": "application/xml"}, self.polygon.encode())
            return http.Reply(200, {"content-type": "application/xml"}, b"<alert></alert>")
        if "api.imd.gov.in" in url:
            if self.imd_status != 200:
                return self._json({"error": self.imd_error}, self.imd_status)
            if not headers.get("X-API-Key") or not headers.get("Authorization", "").startswith("Bearer "):
                return self._json({"error": "API key missing"}, 401)
            path = url.rsplit("/", 1)[-1]
            rows = self.imd_rows.get(path, [])
            if params.get("id") and path == "current_wx":
                rows = [r for r in rows if r.get("Station Id") == params["id"]]
            return self._json(rows)
        return self._json({"error": f"unmocked {url}"}, 404)

    @staticmethod
    def _json(obj, status: int = 200):
        return http.Reply(status, {"content-type": "application/json"}, json.dumps(obj).encode())

    def urls(self, fragment: str) -> list[str]:
        return [u for u, _, _ in self.calls if fragment in u]


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    from weathergpt.config import reset_settings
    from weathergpt.runtime import clear_all_caches
    from weathergpt.weather.service import reset_service
    from weathergpt import geo

    for key in CLEAR_ENV:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(geo, "_throttle", lambda: None)
    reset_settings()
    clear_all_caches()
    reset_service()
    yield
    http.set_transport(None)
    reset_settings()
    clear_all_caches()
    reset_service()


@pytest.fixture
def upstreams() -> FakeUpstreams:
    fake = FakeUpstreams()
    http.set_transport(fake)
    return fake


@pytest.fixture
def imd_keys(monkeypatch):
    from weathergpt.config import reset_settings
    monkeypatch.setenv("IMD_API_KEY", "test-key")
    monkeypatch.setenv("IMD_JWT_TOKEN", "test.jwt.token")
    reset_settings()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from weathergpt.app import create_app
    return TestClient(create_app())
