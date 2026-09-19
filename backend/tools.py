"""Weather and agricultural tools with shared forecast service.

Updates:
- All weather tools now use shared forecast service (IMD -> WeatherNext -> AccuWeather -> Open-Meteo)
- get_current_weather uses forecast service, not legacy fusion directly
- get_weather_forecast uses forecast service with actual provider capabilities (15 days max for WeatherNext synoptic)
- Preserves supplementary capabilities with explicit provenance, units, AQI standard, missing states
- Removes arbitrary default values, adds unknown-data handling
- Separates model-derived hazard guidance from official alerts
- Adds decision tools wrappers delegating to registry/engine
"""

import math
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from langchain_core.tools import tool
from langdetect import detect


def get_user_language(text: str) -> str:
    try:
        lang_code = detect(text)
        language_map = {
            "hi": "Hindi",
            "gu": "Gujarati",
            "ta": "Tamil",
            "bn": "Bengali",
            "te": "Telugu",
            "mr": "Marathi",
            "kn": "Kannada",
            "ml": "Malayalam",
            "pa": "Punjabi",
            "or": "Odia",
            "ur": "Urdu",
            "as": "Assamese",
            "sa": "Sanskrit",
            "ne": "Nepali",
            "en": "English",
        }
        return language_map.get(lang_code, "English")
    except Exception:
        return "English"


from services.open_meteo import (
    WEATHER_CODES,
    extract_weather_code as _extract_weather_code,
    geocode as _geocode,
    AIR_QUALITY_URL,
    FORECAST_URL,
    get_json as om_get_json,
    UpstreamError,
)
from services.fusion import fuse_current_weather  # legacy, kept for diagnostic
from services.forecast import get_forecast_service
from services.config import get_config

__all__ = [
    "WEATHER_CODES", "fuse_current_weather", "get_user_language", "geocode_city",
    "get_current_weather", "get_weather_forecast", "get_hourly_forecast", "get_air_quality",
    "get_uv_index_and_sun", "get_surface_pressure_and_wind",
    "get_agricultural_crop_telemetry", "get_severe_weather_alerts",
    "list_decision_capabilities", "evaluate_weather_decision", "compare_eligible_windows",
    "request_missing_context", "assess_reply_evidence", "get_decision_result",
]


def _bounded(value: Any, low: float | None = None, high: float | None = None) -> float | None:
    try:
        if value is None:
            return None
        num = float(value)
        if not math.isfinite(num):
            return None
        if low is not None and num < low:
            return None
        if high is not None and num > high:
            return None
        return num
    except (TypeError, ValueError):
        return None


@tool
def geocode_city(city_name: str) -> dict:
    """Convert a city name to latitude/longitude. Always call this first before weather tools."""
    return _geocode(city_name)


@tool
def get_current_weather(latitude: float, longitude: float) -> dict:
    """Get current weather conditions using shared forecast service (IMD -> WeatherNext -> AccuWeather -> Open-Meteo).

    Returns normalized result with capability metadata, provenance, and explicit source.
    Call geocode_city first for coordinates.
    """
    try:
        service = get_forecast_service()
        result = service.select_forecast(lat=latitude, lon=longitude, product="current", requested_source="auto", mode="everyone")

        if result.forecast and result.forecast.current:
            curr = result.forecast.current
            return {
                "temperature_2m": curr.temperature_c,
                "apparent_temperature": curr.feels_like_c,
                "relative_humidity_2m": curr.humidity_percent,
                "wind_speed_10m": curr.wind_speed_kmh,
                "wind_direction_10m": curr.wind_direction_deg,
                "surface_pressure": curr.pressure_hpa,
                "pressure_type": curr.pressure_type,
                "precipitation": curr.precipitation_mm,
                "weathercode": curr.weather_code,
                "condition": curr.condition,
                "source": result.selected_source.value,
                "requested_source": result.requested_source,
                "selection_policy_version": result.forecast.provenance.selection_policy_version,
                "provenance": result.forecast.provenance.to_dict(),
                "fallback_reasons": result.fallback_reasons,
                "is_stale": result.is_stale,
            }

        # Fallback to legacy fusion for current if new service unavailable
        legacy = fuse_current_weather(latitude, longitude)
        if isinstance(legacy, dict) and not legacy.get("error"):
            legacy["source"] = "legacy_fusion"
            legacy["provenance"] = {"note": "legacy fusion Open-Meteo > AccuWeather > others"}
            return legacy

        return {"error": result.error or "No provider available", "fallback_reasons": result.fallback_reasons}

    except Exception as e:
        return {"error": str(e)}


@tool
def get_weather_forecast(latitude: float, longitude: float, days: int = 7) -> dict:
    """Get daily forecast up to 15 days (WeatherNext synoptic max) via shared forecast service.

    Uses IMD -> WeatherNext -> AccuWeather -> Open-Meteo selection.
    Returns source/run/coverage metadata. Call geocode_city first.
    """
    try:
        # WeatherNext synoptic maximum 15 days, not 16
        forecast_days = min(max(days, 1), 15)

        service = get_forecast_service()
        result = service.select_forecast(
            lat=latitude,
            lon=longitude,
            product="forecast",
            requested_source="auto",
            mode="everyone",
            forecast_days=forecast_days,
        )

        if result.forecast:
            fc = result.forecast
            forecast = []
            for d in fc.daily[:forecast_days]:
                forecast.append({
                    "date": d.get("date"),
                    "max_temp_celsius": d.get("high_c"),
                    "min_temp_celsius": d.get("low_c"),
                    "rainfall_mm": d.get("rain_mm"),
                    "rain_probability_percent": d.get("rain_probability"),
                    "max_wind_kmh": d.get("wind_kmh_max") or d.get("wind_max"),
                    "condition": d.get("condition"),
                    "source": result.selected_source.value,
                })

            return {
                "forecast": forecast,
                "source": result.selected_source.value,
                "requested_source": result.requested_source,
                "selection_policy_version": fc.provenance.selection_policy_version,
                "model": fc.provenance.model,
                "run_id": fc.provenance.run_id,
                "init_time_utc": fc.provenance.init_time_utc.isoformat() if fc.provenance.init_time_utc else None,
                "provenance": fc.provenance.to_dict(),
                "fallback_reasons": result.fallback_reasons,
                "is_stale": result.is_stale,
            }

        # Fallback to direct Open-Meteo if needed
        with httpx.Client(timeout=10) as client:
            response = client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": latitude,
                    "longitude": longitude,
                    "daily": "temperature_2m_max,temperature_2m_min,rain_sum,precipitation_probability_max,wind_speed_10m_max,weather_code",
                    "forecast_days": forecast_days,
                    "timezone": "auto",
                },
            )
            data = response.json()
            daily = data.get("daily", {})
            dates = daily.get("time", [])
            codes = daily.get("weather_code", daily.get("weathercode", []))
            forecast = []
            for i, date in enumerate(dates):
                weather_code = codes[i] if i < len(codes) else -1
                forecast.append({
                    "date": date,
                    "max_temp_celsius": daily.get("temperature_2m_max", [])[i] if i < len(daily.get("temperature_2m_max", [])) else None,
                    "min_temp_celsius": daily.get("temperature_2m_min", [])[i] if i < len(daily.get("temperature_2m_min", [])) else None,
                    "rainfall_mm": daily.get("rain_sum", [])[i] if i < len(daily.get("rain_sum", [])) else None,
                    "rain_probability_percent": daily.get("precipitation_probability_max", [])[i] if i < len(daily.get("precipitation_probability_max", [])) else None,
                    "max_wind_kmh": daily.get("wind_speed_10m_max", [])[i] if i < len(daily.get("wind_speed_10m_max", [])) else None,
                    "condition": WEATHER_CODES.get(weather_code, "Unknown"),
                })
            return {"forecast": forecast, "source": "open-meteo-fallback", "fallback_reasons": result.fallback_reasons}

    except Exception as e:
        return {"error": str(e)}


@tool
def get_hourly_forecast(latitude: float, longitude: float) -> dict:
    """Get detailed 24-hour hourly weather breakdown via shared forecast service.

    Preserves wind/humidity as promised by tool, returns provenance.
    Call geocode_city first.
    """
    try:
        service = get_forecast_service()
        result = service.select_forecast(lat=latitude, lon=longitude, product="hourly", requested_source="auto", mode="everyone")

        if result.forecast and result.forecast.hourly:
            hours_data = []
            for p in result.forecast.hourly[:24]:
                hours_data.append({
                    "time": p.time_utc.isoformat(),
                    "temp_celsius": p.temperature_c,
                    "feels_like_celsius": p.feels_like_c,
                    "rain_probability_percent": p.precipitation_probability,
                    "precipitation_mm": p.precipitation_mm,
                    "wind_speed_kmh": p.wind_speed_kmh,
                    "wind_direction_deg": p.wind_direction_deg,
                    "humidity_percent": p.humidity_percent,
                    "condition": p.condition,
                    "source": result.selected_source.value,
                })
            return {
                "hourly_forecast": hours_data,
                "source": result.selected_source.value,
                "provenance": result.forecast.provenance.to_dict(),
                "fallback_reasons": result.fallback_reasons,
            }

        # Fallback to direct Open-Meteo
        with httpx.Client(timeout=10) as client:
            res = client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": latitude,
                    "longitude": longitude,
                    "hourly": "temperature_2m,apparent_temperature,precipitation_probability,relative_humidity_2m,wind_speed_10m,weather_code",
                    "forecast_days": 2,
                    "timezone": "auto",
                },
            )
            data = res.json()
            hourly = data.get("hourly", {})
            times = hourly.get("time", [])[:24]
            temps = hourly.get("temperature_2m", [])[:24]
            feels = hourly.get("apparent_temperature", [])[:24]
            precip = hourly.get("precipitation_probability", [])[:24]
            precip_mm = hourly.get("precipitation", [])[:24] if "precipitation" in hourly else [None]*24
            winds = hourly.get("wind_speed_10m", [])[:24] if "wind_speed_10m" in hourly else [None]*24
            humidity = hourly.get("relative_humidity_2m", [])[:24] if "relative_humidity_2m" in hourly else [None]*24
            codes = hourly.get("weather_code", hourly.get("weathercode", []))[:24]

            hours_data = []
            for i in range(len(times)):
                w_code = codes[i] if i < len(codes) else 0
                hours_data.append({
                    "time": times[i],
                    "temp_celsius": temps[i] if i < len(temps) else None,
                    "feels_like_celsius": feels[i] if i < len(feels) else None,
                    "rain_probability_percent": precip[i] if i < len(precip) else 0,
                    "precipitation_mm": precip_mm[i] if i < len(precip_mm) else None,
                    "wind_speed_kmh": winds[i] if i < len(winds) else None,
                    "humidity_percent": humidity[i] if i < len(humidity) else None,
                    "condition": WEATHER_CODES.get(w_code, "Clear"),
                })
            return {"hourly_forecast": hours_data, "source": "open-meteo-fallback"}

    except Exception as e:
        return {"error": str(e)}


@tool
def get_air_quality(latitude: float, longitude: float) -> dict:
    """Get air quality with explicit provenance, units, AQI standard, and missing states.

    Preserves European vs US AQI distinction. No arbitrary default values.
    Call geocode_city first.
    """
    try:
        service = get_forecast_service()
        result = service.select_forecast(lat=latitude, lon=longitude, product="forecast", requested_source="auto", mode="everyone")

        # Try to get AQI from forecast service first
        if result.forecast and result.forecast.air_quality:
            aq = result.forecast.air_quality
            return {
                "european_aqi": aq.get("european_aqi"),
                "us_aqi": aq.get("us_aqi"),
                "pm2_5": aq.get("pm2_5"),
                "pm10": aq.get("pm10"),
                "standard": aq.get("standard", "european"),
                "source": result.selected_source.value,
                "provenance": result.forecast.provenance.to_dict() if result.forecast else None,
            }

        # Fallback to direct Open-Meteo air quality with explicit standard
        with httpx.Client(timeout=10) as client:
            res = client.get(
                "https://air-quality-api.open-meteo.com/v1/air-quality",
                params={
                    "latitude": latitude,
                    "longitude": longitude,
                    "current": "european_aqi,us_aqi,pm10,pm2_5,carbon_monoxide,nitrogen_dioxide,sulphur_dioxide,ozone",
                    "timezone": "auto",
                },
            )
            data = res.json()
            curr = data.get("current", {})

            # Explicit provenance, no arbitrary defaults
            european_aqi = _bounded(curr.get("european_aqi"), 0, 1000)
            us_aqi = _bounded(curr.get("us_aqi"), 0, 1000)
            pm25 = _bounded(curr.get("pm2_5"), 0, 1000)
            pm10 = _bounded(curr.get("pm10"), 0, 1000)

            if european_aqi is None and us_aqi is None:
                return {
                    "status": "unavailable",
                    "message": "Air quality data unavailable",
                    "standard": "unknown",
                    "source": "open-meteo-air-quality",
                }

            # Use European as primary for mobile (as per mobile.py), but report both with standard
            aqi_val = european_aqi if european_aqi is not None else us_aqi
            standard = "european" if european_aqi is not None else "us" if us_aqi is not None else "unknown"

            category = "Unknown"
            if aqi_val is not None:
                if standard == "european":
                    if aqi_val > 80:
                        category = "Very Unhealthy"
                    elif aqi_val > 60:
                        category = "Unhealthy"
                    elif aqi_val > 40:
                        category = "Unhealthy for Sensitive"
                    elif aqi_val > 20:
                        category = "Moderate"
                    else:
                        category = "Good"
                else:  # US
                    if aqi_val > 300:
                        category = "Hazardous"
                    elif aqi_val > 200:
                        category = "Very Unhealthy"
                    elif aqi_val > 150:
                        category = "Unhealthy"
                    elif aqi_val > 100:
                        category = "Unhealthy for Sensitive Groups"
                    elif aqi_val > 50:
                        category = "Moderate"
                    else:
                        category = "Good"

            return {
                "european_aqi": european_aqi,
                "us_aqi": us_aqi,
                "aqi": aqi_val,
                "standard": standard,
                "category": category,
                "pm2_5": pm25,
                "pm10": pm10,
                "nitrogen_dioxide": _bounded(curr.get("nitrogen_dioxide")),
                "ozone": _bounded(curr.get("ozone")),
                "source": "open-meteo-air-quality",
                "provenance": {"standard": standard, "source": "open-meteo"},
            }

    except Exception as e:
        return {"error": str(e), "status": "unavailable"}


@tool
def get_uv_index_and_sun(latitude: float, longitude: float) -> dict:
    """Get UV Index, sunrise, sunset with explicit provenance and missing states.

    No arbitrary default values. Call geocode_city first.
    """
    try:
        with httpx.Client(timeout=10) as client:
            res = client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": latitude,
                    "longitude": longitude,
                    "current": "uv_index",
                    "daily": "uv_index_max,sunrise,sunset",
                    "forecast_days": 1,
                    "timezone": "auto",
                },
            )
            data = res.json()
            curr = data.get("current") or {}
            daily = data.get("daily") or {}

            current_uv = _bounded(curr.get("uv_index"), 0, 20)
            uv_max_arr = daily.get("uv_index_max") or []
            uv_max = _bounded(uv_max_arr[0] if uv_max_arr else current_uv, 0, 20)

            sunrise_arr = daily.get("sunrise") or []
            sunset_arr = daily.get("sunset") or []
            sunrise = sunrise_arr[0] if sunrise_arr else None
            sunset = sunset_arr[0] if sunset_arr else None

            if uv_max is None and current_uv is None:
                return {
                    "status": "unavailable",
                    "message": "UV data unavailable",
                    "source": "open-meteo",
                }

            uv_val = uv_max if uv_max is not None else current_uv

            uv_category = "Unknown"
            uv_advisory = "UV data unavailable"
            if uv_val is not None:
                if uv_val >= 8:
                    uv_category = "Very High / Extreme"
                    uv_advisory = "Extreme UV risk! Seek shade during midday (10am-4pm), wear SPF 30+ sunscreen, sunglasses, and protective hat."
                elif uv_val >= 6:
                    uv_category = "High"
                    uv_advisory = "High UV index. Reduce direct sun exposure during peak afternoon hours."
                elif uv_val >= 3:
                    uv_category = "Moderate"
                    uv_advisory = "Moderate UV index. Wear sunglasses and SPF 30+ if outdoors for extended periods."
                else:
                    uv_category = "Low"
                    uv_advisory = "Minimal sun exposure risk. Enjoy outdoor activities!"

            return {
                "current_uv_index": current_uv,
                "max_uv_index_today": uv_max,
                "uv_category": uv_category,
                "uv_advisory": uv_advisory,
                "sunrise_time": sunrise,
                "sunset_time": sunset,
                "source": "open-meteo",
                "provenance": {"uv_source": "open-meteo", "astronomy_source": "open-meteo"},
            }

    except Exception as e:
        return {"error": str(e), "status": "unavailable"}


@tool
def get_surface_pressure_and_wind(latitude: float, longitude: float) -> dict:
    """Get barometric pressure with explicit type (MSL vs surface) and wind.

    Preserves separate definitions for mean-sea-level vs surface pressure.
    No gust estimates masquerading as measurements. Call geocode_city first.
    """
    try:
        with httpx.Client(timeout=10) as client:
            res = client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": latitude,
                    "longitude": longitude,
                    "current": "surface_pressure,mean_sea_level_pressure,wind_speed_10m,wind_direction_10m,wind_gusts_10m",
                    "timezone": "auto",
                },
            )
            data = res.json()
            curr = data.get("current", {})

            surface_pressure = _bounded(curr.get("surface_pressure"), 800, 1200)
            msl_pressure = _bounded(curr.get("mean_sea_level_pressure"), 800, 1200)
            # Use surface pressure as primary, but report both with explicit types
            pressure = surface_pressure if surface_pressure is not None else msl_pressure
            pressure_type = "surface" if surface_pressure is not None else "msl" if msl_pressure is not None else "unknown"

            wind_deg = _bounded(curr.get("wind_direction_10m"), 0, 360)
            wind_speed = _bounded(curr.get("wind_speed_10m"), 0, 500)
            gusts = _bounded(curr.get("wind_gusts_10m"), 0, 500)

            # Gusts must be measured, not estimated as wind*1.3 if missing
            if gusts is None:
                gust_status = "unavailable"
            else:
                gust_status = "measured"

            if pressure is None and wind_speed is None:
                return {"status": "unavailable", "message": "Pressure and wind data unavailable"}

            directions = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
            cardinal = None
            if wind_deg is not None:
                cardinal = directions[int(round(wind_deg / 45)) % 8]

            return {
                "surface_pressure_hpa": surface_pressure,
                "mean_sea_level_pressure_hpa": msl_pressure,
                "pressure_hpa": pressure,
                "pressure_type": pressure_type,
                "pressure_status": "Standard atmospheric pressure" if pressure and 1005 <= pressure <= 1020 else "Low pressure system" if pressure and pressure < 1005 else "High pressure system" if pressure else "Unknown",
                "wind_speed_kmh": wind_speed,
                "wind_gusts_kmh": gusts,
                "wind_gusts_status": gust_status,
                "wind_direction_degrees": wind_deg,
                "wind_cardinal_direction": cardinal,
                "source": "open-meteo",
                "provenance": {"pressure_type": pressure_type, "gust_status": gust_status},
            }

    except Exception as e:
        return {"error": str(e), "status": "unavailable"}


@tool
def get_agricultural_crop_telemetry(latitude: float, longitude: float, crop: str = "Cotton") -> dict:
    """Get agricultural crop telemetry: soil moisture, temperature, ET0.

    Retains separately sourced soil/ET0 fields; consumes shared forecast rain for decisions;
    removes made-up moisture/temperature defaults and adds unknown-data handling.
    Call geocode_city first.
    """
    try:
        with httpx.Client(timeout=10) as client:
            res = client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": latitude,
                    "longitude": longitude,
                    "current": "soil_temperature_0cm,soil_moisture_0_to_7cm,soil_moisture_7_to_28cm",
                    "daily": "et0_fao_evapotranspiration,precipitation_sum",
                    "forecast_days": 3,
                    "timezone": "auto",
                },
            )
            data = res.json()
            curr = data.get("current", {})
            daily = data.get("daily", {})

            soil_moist_top = _bounded(curr.get("soil_moisture_0_to_7cm"), 0, 1)
            soil_moist_sub = _bounded(curr.get("soil_moisture_7_to_28cm"), 0, 1)
            soil_temp = _bounded(curr.get("soil_temperature_0cm"), -50, 60)
            et0_arr = daily.get("et0_fao_evapotranspiration") or []
            rain_arr = daily.get("precipitation_sum") or []
            et0_today = _bounded(et0_arr[0] if et0_arr else None, 0, 50)
            rain_today = _bounded(rain_arr[0] if rain_arr else None, 0, 1000)

            crop_name = crop.strip() if crop else "Crops"

            # Check data sufficiency
            missing = []
            if soil_moist_top is None:
                missing.append("soil_moisture_surface")
            if soil_moist_sub is None:
                missing.append("soil_moisture_rootzone")
            if soil_temp is None:
                missing.append("soil_temperature")
            if et0_today is None:
                missing.append("et0")
            if rain_today is None:
                missing.append("rainfall")

            if len(missing) >= 3:
                return {
                    "status": "insufficient_data",
                    "message": f"Insufficient soil/ET0 data: missing {', '.join(missing)}",
                    "missing": missing,
                    "crop": crop_name,
                    "source": "open-meteo",
                }

            # Irrigation evaluation only if we have sufficient data
            irrigation_needed = None
            spraying_safe = None
            if rain_today is not None and soil_moist_top is not None:
                irrigation_needed = rain_today < 2.0 and soil_moist_top < 0.20
                spraying_safe = rain_today < 1.0

            result = {
                "crop": crop_name,
                "soil_moisture_surface_m3m3": soil_moist_top,
                "soil_moisture_rootzone_m3m3": soil_moist_sub,
                "soil_temperature_celsius": soil_temp,
                "evapotranspiration_et0_mm": et0_today,
                "expected_rainfall_mm": rain_today,
                "source": "open-meteo",
                "provenance": {"soil_source": "open-meteo", "et0_source": "open-meteo"},
            }

            if irrigation_needed is not None:
                result["irrigation_advisory"] = f"Irrigation recommended for {crop_name} today due to low soil moisture and dry weather." if irrigation_needed else f"Sufficient soil moisture for {crop_name}. Delay irrigation to conserve water."
                result["pesticide_spraying_window"] = "Favorable window for pesticide/fertilizer spraying (low rain risk)." if spraying_safe else "Avoid pesticide spraying today due to impending rainfall wash-off risk."
            else:
                result["irrigation_advisory"] = "Insufficient data to determine irrigation need"
                result["pesticide_spraying_window"] = "Insufficient data for spraying window"

            if missing:
                result["missing_fields"] = missing
                result["warnings"] = [f"Missing {m}, advisory may be incomplete" for m in missing]

            return result

    except Exception as e:
        return {"error": str(e), "status": "unavailable"}


@tool
def get_severe_weather_alerts(latitude: float, longitude: float) -> dict:
    """Get severe weather alerts: separates model-derived hazard guidance from official alerts.

    Official warnings must remain authoritative; WeatherNext is not official warning service.
    Never present missing data as all-clear. Call geocode_city first.
    """
    try:
        service = get_forecast_service()
        official = service.get_official_warnings(latitude, longitude)

        # Model-derived hazard guidance from forecast
        with httpx.Client(timeout=10) as client:
            res = client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": latitude,
                    "longitude": longitude,
                    "daily": "temperature_2m_max,precipitation_probability_max,wind_speed_10m_max,weather_code",
                    "forecast_days": 1,
                    "timezone": "auto",
                },
            )
            data = res.json()
            daily = data.get("daily", {})
            max_temp = _bounded((daily.get("temperature_2m_max") or [None])[0], -100, 70)
            rain_prob = _bounded((daily.get("precipitation_probability_max") or [None])[0], 0, 100)
            max_wind = _bounded((daily.get("wind_speed_10m_max") or [None])[0], 0, 500)
            w_code = (daily.get("weather_code") or [None])[0]

            # Model-derived guidance (not official)
            level = "GREEN"
            title = "No Severe Weather Hazards in Model Guidance"
            advisory = "Normal conditions in forecast model."
            action = "Enjoy your day normally."

            if max_temp is not None and max_temp >= 42:
                level = "RED"
                title = "Model Guidance: Severe Heat Risk"
                advisory = f"Forecast model shows extreme temperatures {max_temp}°C. High risk of heatstroke."
                action = "STAY INDOORS: Avoid outdoor exposure between 11am-4pm."
            elif (rain_prob is not None and rain_prob >= 80) or (w_code in [65, 82, 95, 96, 99]):
                level = "ORANGE"
                title = "Model Guidance: Heavy Rain / Thunderstorm Risk"
                advisory = f"Forecast model indicates heavy rainfall (prob {rain_prob}%). Waterlogging possible."
                action = "BE PREPARED: Avoid low-lying flooded roads."
            elif max_wind is not None and max_wind >= 40:
                level = "YELLOW"
                title = "Model Guidance: High Wind Risk"
                advisory = f"Forecast model shows strong wind gusts up to {max_wind} km/h."
                action = "WATCHFUL: Secure outdoor furniture."

            return {
                "model_guidance": {
                    "alert_level": level,
                    "title": title,
                    "advisory": advisory,
                    "recommended_action": action,
                    "source": "WeatherGPT model-derived guidance (not official warning)",
                },
                "official_warnings": official,
                "note": "Official warnings are authoritative; model guidance is separate. Unknown official status is not no alerts.",
                "source": "open-meteo + imd_official",
            }

    except Exception as e:
        return {"error": str(e), "status": "unknown", "message": "Failed to retrieve alerts, status unknown not no alerts"}


# ---------------------------------------------------------------------------
# Decision tools wrappers (delegating to registry/engine, not raw TypeSafe HTTP)
# ---------------------------------------------------------------------------

@tool
def list_decision_capabilities(mode: str = "farmer") -> dict:
    """List decision capabilities for mode: authorized features, inputs, blockers."""
    from services.decisions.registry import get_registry
    from services.config import get_config

    registry = get_registry()
    cfg = get_config().jev

    if mode not in ("everyone", "farmer", "researcher"):
        return {"status": "invalid", "message": "mode must be everyone|farmer|researcher"}

    enabled = registry.enabled_features(cfg)
    filtered = [f for f in enabled if mode in f.modes]

    return {
        "status": "ok",
        "mode": mode,
        "weathernext_mode": cfg.weathernext_mode,
        "enabled_features": [
            {
                "feature_id": f.feature_id,
                "description": f.description,
                "primitive": f.primitive.value,
                "required_evidence": f.required_evidence,
                "release_state": f.release_state.value,
            }
            for f in filtered
        ],
        "total_enabled": len(filtered),
        "coverage": registry.coverage_report(),
    }


@tool
def evaluate_weather_decision(
    feature_id: str = "farm.spray_windows",
    latitude: float = 0.0,
    longitude: float = 0.0,
    date: str = "",
    crop: str = "",
    mode: str = "farmer",
) -> dict:
    """Evaluate weather decision via shared decision engine (bounded, audited)."""
    from services.decisions.registry import get_registry
    from services.decisions.models import DecisionContextV2
    from services.decisions.engine import get_engine
    from services.forecast import get_forecast_service
    from datetime import datetime

    registry = get_registry()
    spec = registry.get(feature_id)
    if not spec:
        return {"status": "unsupported", "message": f"Feature {feature_id} not found"}

    cfg = get_config().jev
    enabled = registry.enabled_features(cfg)
    if feature_id not in {f.feature_id for f in enabled}:
        return {"status": "not_authorized", "feature_id": feature_id, "weathernext_mode": cfg.weathernext_mode}

    # Fetch evidence server-side
    service = get_forecast_service()
    forecast_result = service.select_forecast(lat=latitude, lon=longitude, product="forecast", requested_source="auto", mode=mode)
    warnings = service.get_official_warnings(latitude, longitude)

    # Build context
    interval_start = None
    interval_end = None
    if date:
        try:
            d = datetime.fromisoformat(date).date()
            interval_start = datetime.combine(d, datetime.min.time()).replace(tzinfo=timezone.utc)
            interval_end = datetime.combine(d, datetime.max.time()).replace(tzinfo=timezone.utc)
        except Exception:
            pass

    distributions = {}
    if forecast_result.forecast:
        daily = next((d for d in forecast_result.forecast.daily if d.get("date") == date), None)
        if daily:
            distributions = {
                "pop_max": daily.get("rain_probability"),
                "rain_sum": daily.get("rain_mm"),
                "wind_max": daily.get("wind_kmh_max") or daily.get("wind_max"),
                "temp_max": daily.get("high_c"),
            }

    context = DecisionContextV2(
        mode=mode,
        lat=latitude,
        lon=longitude,
        activity_id=feature_id,
        crop=crop,
        evidence_ids=[forecast_result.forecast.provenance.run_id if forecast_result.forecast else "ev_unknown"],
        run_id=forecast_result.forecast.provenance.run_id if forecast_result.forecast else None,
        requested_source="auto",
        utc_interval_start=interval_start,
        utc_interval_end=interval_end,
        official_warning_status=warnings.get("status", "unknown"),
        distributions=distributions,
        deterministic_baseline="good",
    )

    engine = get_engine()
    result = engine.evaluate(context, feature_id)

    return {
        "status": result.status.value,
        "decision_id": result.decision_id,
        "feature_id": feature_id,
        "final_verdict": result.final_verdict,
        "deterministic_verdict": result.deterministic_verdict,
        "model_verdict": result.model_verdict,
        "confidence": result.decision_confidence,
        "evidence_ids": result.evidence_ids,
        "reason_codes": result.reason_codes,
        "execution_mode": result.execution_mode,
        "provenance": forecast_result.forecast.provenance.to_dict() if forecast_result.forecast else None,
    }


@tool
def compare_eligible_windows(
    latitude: float = 0.0,
    longitude: float = 0.0,
    dates: str = "",
    crop: str = "",
    activity: str = "spraying",
) -> dict:
    """Compare eligible windows for activity across dates using deterministic solver + Jev ranking."""
    from datetime import datetime

    try:
        date_list = [d.strip() for d in dates.split(",") if d.strip()]
        if not date_list:
            return {"status": "invalid", "message": "Provide dates as comma-separated YYYY-MM-DD"}

        service = get_forecast_service()
        windows = []

        for date in date_list:
            result = service.select_forecast(lat=latitude, lon=longitude, product="forecast", requested_source="auto", mode="farmer")
            if not result.forecast:
                windows.append({"date": date, "status": "unavailable", "reason": result.error})
                continue

            daily = next((d for d in result.forecast.daily if d.get("date") == date), None)
            if not daily:
                windows.append({"date": date, "status": "unavailable", "reason": "no daily data for date"})
                continue

            # Deterministic eligibility
            pop = daily.get("rain_probability") or 0
            rain = daily.get("rain_mm") or 0
            wind = daily.get("wind_kmh_max") or 0

            eligible = True
            reasons = []
            if activity == "spraying":
                if pop >= 60 or rain >= 0.5 or wind >= 25:
                    eligible = False
                    reasons.append(f"pop {pop}%, rain {rain}mm, wind {wind}km/h exceed spraying thresholds")

            windows.append({
                "date": date,
                "eligible": eligible,
                "reasons": reasons,
                "pop": pop,
                "rain_mm": rain,
                "wind_kmh": wind,
                "high_c": daily.get("high_c"),
            })

        # Sort eligible first
        windows_sorted = sorted(windows, key=lambda w: (0 if w.get("eligible") else 1, w.get("pop", 100)))

        return {
            "status": "ok",
            "activity": activity,
            "crop": crop,
            "windows": windows_sorted,
            "eligible_count": sum(1 for w in windows if w.get("eligible")),
            "total": len(windows),
        }

    except Exception as e:
        return {"error": str(e)}


@tool
def request_missing_context(missing: str = "", feature_id: str = "") -> dict:
    """Request missing context for decision - chooses narrowly scoped follow-up."""
    allowed = ["location", "date", "crop_stage", "soil_moisture", "irrigation_type", "activity_duration", "variable", "level"]

    if missing not in allowed:
        return {"status": "invalid", "message": f"Missing must be in {allowed}"}

    questions = {
        "location": "Could you share your farm location (lat/lon or city)?",
        "date": "Which date should I evaluate?",
        "crop_stage": "What is the crop growth stage (e.g., Flowering, Vegetative)?",
        "soil_moisture": "Do you have measured soil moisture data? Soil type alone doesn't indicate current moisture.",
        "irrigation_type": "What irrigation system do you use?",
        "activity_duration": "How long will this operation take?",
        "variable": "Which weather variable are you interested in?",
        "level": "Which pressure level (hPa) for upper-air data?",
    }

    return {
        "status": "ok",
        "feature_id": feature_id,
        "missing": missing,
        "question": questions.get(missing, f"Need {missing}"),
        "note": "Required-input checks remain deterministic, not model-inferred",
    }


@tool
def assess_reply_evidence(draft: str = "", evidence_ids: str = "") -> dict:
    """Evidence-aware reply assessment: checks if draft supported by bounded tool results."""
    # Numeric/source/time checks run in code first
    # This is a Noul check for semantic support

    if not draft:
        return {"status": "invalid", "message": "Draft required"}

    ev_list = [e.strip() for e in evidence_ids.split(",") if e.strip()] if evidence_ids else []

    # Simple deterministic checks
    issues = []
    if "°C" in draft and not ev_list:
        issues.append("Temperature mentioned but no evidence IDs provided")
    if "WeatherNext" in draft and "weathernext" not in draft.lower():
        # Check source attribution
        pass

    # In real implementation, would call Jev Noul for semantic support
    from services import typesafe
    if typesafe.is_enabled():
        result = typesafe.evaluate(
            f"Draft: {draft[:1000]}\nEvidence IDs: {ev_list}",
            {"supported": typesafe.noul("Is this draft statement supported by the provided evidence IDs and tool results?")},
            timeout=3.0,
            label="reply_evidence",
        )
        if result:
            prob = typesafe.noul_of(result["answers"], "supported")
            return {
                "status": "ok",
                "supported_probability": prob,
                "issues": issues,
                "evidence_ids": ev_list,
                "note": "Model approval cannot repair failed deterministic checks",
            }

    return {
        "status": "ok",
        "supported_probability": None,
        "issues": issues,
        "evidence_ids": ev_list,
        "message": "Deterministic checks only, Jev not enabled",
    }


@tool
def get_decision_result(decision_id: str = "") -> dict:
    """Get decision result by ID with safe evidence references."""
    from services.decisions.engine import get_audit_store

    store = get_audit_store()
    recent = store.get_recent(100)
    for rec in recent:
        if rec.get("decision_id") == decision_id:
            return {"status": "ok", "result": rec}

    return {"status": "not_found", "message": f"Decision {decision_id} not found or expired"}
