"""IMD provider: official India forecast + station observations.

For a point inside India:
1. ``cityforecastloc`` (all stations, cached) -> nearest city-forecast station
   within ``IMD_MAX_STATION_KM``; its row carries the 7-day max/min/text forecast,
   today's observed extremes, 24 h rainfall, humidity and sunrise/sunset.
2. ``current_wx`` -> that station's latest synoptic observation (temperature,
   MSLP, wind, humidity, present weather, nebulosity). Observations older than
   ``IMD_OBSERVATION_MAX_AGE_HOURS`` are not presented as "now".

IMD publishes no hourly series, rain probability or UV; the supplement layer
fills those from Open-Meteo with per-field attribution.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from weathergpt.config import settings
from weathergpt.imd import client, stations
from weathergpt.imd.parse import IST, IST_OFFSET_SECONDS, local_stamp, number, observation_time_utc, parse_date, text
from weathergpt.weather.codes import from_imd_forecast_text, from_imd_present_weather
from weathergpt.weather.models import DayPoint, Forecast, HourPoint, Provenance, ProviderResult
from weathergpt.weather.providers.base import Provider

# Generous India bounding box (incl. Andaman & Nicobar and Lakshadweep).
INDIA_BBOX = (6.0, 37.6, 67.0, 98.0)


def in_india(lat: float, lon: float) -> bool:
    return INDIA_BBOX[0] <= lat <= INDIA_BBOX[1] and INDIA_BBOX[2] <= lon <= INDIA_BBOX[3]


def parse_city_forecast(row: dict, today_ist) -> tuple[list[DayPoint], dict, Optional[object]]:
    """Station row -> (daily from today on, observed extremes, issue date)."""
    issued = parse_date(text(row, "Date", "Date of Observation"))
    daily: list[DayPoint] = []
    if issued is not None:
        for n in range(1, 8):
            if n == 1:
                hi = number(row, "Todays_Forecast_Max_Temp", "Todays_Forecast_Max_temp", "Day_1_Max_Temp", low=-50, high=60)
                lo = number(row, "Todays_Forecast_Min_temp", "Todays_Forecast_Min_Temp", "Day_1_Min_temp", low=-60, high=50)
                words = text(row, "Todays_Forecast", "Day_1_Forecast")
            else:
                hi = number(row, f"Day_{n}_Max_Temp", f"Day_{n}_Max_temp", low=-50, high=60)
                lo = number(row, f"Day_{n}_Min_temp", f"Day_{n}_Min_Temp", low=-60, high=50)
                words = text(row, f"Day_{n}_Forecast")
            day = issued + timedelta(days=n - 1)
            if day < today_ist:
                continue
            if hi is None and lo is None and words is None:
                continue
            code, condition = from_imd_forecast_text(words)
            daily.append(DayPoint(
                date=day.isoformat(), high_c=hi, low_c=lo, weather_code=code, condition=condition,
                forecast_text=words, sunrise=local_stamp(day, text(row, "Sunrise_time", "Sunrise")) if n == 1 else None,
                sunset=local_stamp(day, text(row, "Sunset_time", "Sunset")) if n == 1 else None,
                statistic="official_forecast", source="imd", precipitation_interval=None,
            ))
    observed = {
        "date": issued.isoformat() if issued else None,
        "max_temp_c": number(row, "Today_Max_temp", "Today_Max_Temp", low=-50, high=60),
        "max_departure_c": number(row, "Today_Max_Departure_from_Normal", low=-40, high=40),
        "min_temp_c": number(row, "Today_Min_temp", "Today_Min_Temp", low=-60, high=50),
        "min_departure_c": number(row, "Today_Min_Departure_from_Normal", low=-40, high=40),
        "past_24h_rainfall_mm": number(row, "Past_24_hrs_Rainfall", low=0, high=2000),
        "humidity_0830_percent": number(row, "Relative_Humidity_at_0830", low=0, high=100),
        "humidity_1730_percent": number(row, "Relative_Humidity_at_1730", low=0, high=100),
        "moonrise": text(row, "Moonrise_time"),
        "moonset": text(row, "Moonset_time"),
    }
    return daily, observed, issued


def parse_observation(row: dict, now: datetime, max_age_hours: float) -> tuple[Optional[HourPoint], dict]:
    observed_at = observation_time_utc(row)
    ww = number(row, "Weather Code", "Weather_Code", "WEATHER_CODE", low=0, high=99)
    okta = number(row, "Nebulosity", "NEBULOSITY", low=0, high=9)
    code, condition = from_imd_present_weather(int(ww) if ww is not None else None, okta)
    wind_dir = number(row, "Wind Direction", "Wind_Direction", "WIND_DIRECTION", low=0, high=360)
    wind_kmh = number(row, "Wind Speed KMPH", "Wind Speed", "Wind Speed (KMPH)", "Wind_Speed", "WIND_SPEED", low=0, high=400)
    message = text(row, "WEATHER_MESSAGE")
    if message and (ww is None or ww >= 4):
        # IMD's own words ("Smoke Fog", "Haze", "Light Rain") beat our generic label.
        condition = message[:1].upper() + message[1:]
    meta = {
        "observed_at_utc": observed_at.isoformat() if observed_at else None,
        "station": text(row, "Station", "Station Name"),
        "last_24h_rainfall_mm": number(row, "Last 24 hrs Rainfall", "Last_24_hrs_Rainfall", low=0, high=2000),
        "present_weather_code": int(ww) if ww is not None else None,
        "nebulosity_okta": okta,
    }
    if observed_at is None:
        meta["rejected"] = "no_observation_time"
        return None, meta
    age_h = (now - observed_at).total_seconds() / 3600.0
    if age_h > max_age_hours or age_h < -1:
        meta["rejected"] = f"observation_age_{age_h:.1f}h"
        return None, meta
    point = HourPoint(
        time_utc=observed_at,
        temperature_c=number(row, "Temperature", "Temperature (deg C)", "CURR_TEMP", low=-60, high=60),
        humidity_percent=number(row, "Humidity", "Humidity (%)", "RH", low=0, high=100),
        feels_like_c=number(row, "Feel Like", "Feels Like", low=-60, high=70),
        pressure_hpa=number(row, "Mean Sea Level Pressure", "M.S.L.P", "MSLP", "M.S.L.P (hPa)", low=800, high=1100),
        pressure_type="msl",
        wind_speed_kmh=wind_kmh,
        # Direction code 0 means calm: there is no direction to report.
        wind_direction_deg=wind_dir if wind_dir not in (None, 0.0) else None,
        weather_code=code, condition=condition,
        cloud_cover_percent=round(okta / 8 * 100) if okta is not None and okta <= 8 else None,
    )
    return point, meta


class IMDProvider(Provider):
    name = "imd"

    def availability(self, lat, lon):
        cfg = settings().imd
        if not cfg.enabled:
            return False, "disabled", "IMD_ENABLED=0"
        if not in_india(lat, lon):
            return False, "out_of_coverage", "IMD serves locations in India"
        if not cfg.configured:
            return False, "not_configured", f"Set {' and '.join(cfg.missing())}"
        return True, None, None

    def fetch(self, lat, lon, *, forecast_days, **options) -> ProviderResult:
        started = time.perf_counter()
        cfg = settings().imd

        def fail(reason: str, message: str, transient: bool = False, **extra) -> ProviderResult:
            return ProviderResult(False, reason=reason, message=message, transient=transient, extra=extra,
                                  latency_ms=(time.perf_counter() - started) * 1000)

        try:
            station = stations.nearest_city_station(lat, lon)
        except client.IMDError as exc:
            return fail(exc.reason, str(exc), exc.transient)
        if station is None:
            return fail("no_data", "IMD returned no city-forecast stations with coordinates", True)
        if station.distance_km > cfg.max_station_km:
            return fail("no_station_nearby",
                        f"Nearest IMD city station {station.name} is {station.distance_km:.0f} km away "
                        f"(limit {cfg.max_station_km:.0f} km)", station=station.to_dict())

        now = datetime.now(timezone.utc)
        today_ist = now.astimezone(IST).date()
        daily, observed, issued = parse_city_forecast(station.row, today_ist)
        notes: list[str] = []

        current: Optional[HourPoint] = None
        obs_meta: dict = {}
        obs_station = station
        try:
            obs_row = stations.observation_for(station)
            if obs_row is None:
                nearest = stations.nearest_observation(lat, lon, cfg.max_station_km)
                if nearest is not None:
                    obs_row, obs_station = nearest
                    notes.append(f"observation from nearest reporting station {obs_station.name} "
                                 f"({obs_station.distance_km:.0f} km)")
            if obs_row is None:
                notes.append("no current_wx observation within range")
            else:
                current, obs_meta = parse_observation(obs_row, now, cfg.observation_max_age_hours)
                if current is None:
                    notes.append(f"observation not used: {obs_meta.get('rejected')}")
        except client.IMDError as exc:
            notes.append(f"current_wx unavailable: {exc.reason}")

        if not daily and current is None:
            return fail("no_data", f"IMD station {station.name} has no current forecast", True, station=station.to_dict())

        if issued is None:
            freshness = "unknown"
        else:
            age_days = (today_ist - issued).days
            freshness = "fresh" if age_days <= 1 else "stale" if age_days <= 3 else "expired"

        forecast = Forecast(
            location={"lat": lat, "lon": lon, "timezone": "Asia/Kolkata", "utc_offset_seconds": IST_OFFSET_SECONDS,
                      "timezone_source": "imd", "name": station.name},
            current=current,
            current_kind="observation" if current is not None else None,
            hourly=[],
            daily=daily[:forecast_days],
            provenance=Provenance(
                source="imd", model="imd_city_forecast", product="forecast",
                issued_at_utc=datetime(issued.year, issued.month, issued.day, tzinfo=IST).astimezone(timezone.utc) if issued else None,
                observed_at_utc=current.time_utc if current else None,
                freshness_status=freshness, requested_lat=lat, requested_lon=lon,
                sampled_lat=station.lat, sampled_lon=station.lon, distance_km=round(station.distance_km, 2),
                spatial_method="nearest_city_station", station={**station.to_dict(), "observation": obs_meta or None,
                                                                "observation_station": obs_station.to_dict() if current else None,
                                                                "observed": observed},
                sources=["imd:cityforecastloc"] + (["imd:current_wx"] if current else []),
                methods={
                    "daily": "IMD official city forecast (max/min + forecast text)",
                    "condition": "WMO class derived from IMD forecast text / present-weather code",
                    "current": "IMD station observation" if current else "not available",
                },
                notes=notes,
            ),
        )
        forecast.location["observed"] = observed
        return ProviderResult(True, forecast=forecast, latency_ms=(time.perf_counter() - started) * 1000)
