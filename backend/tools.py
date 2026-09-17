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
)
from services.fusion import fuse_current_weather  # re-exported for backwards compatibility

__all__ = [
    "WEATHER_CODES", "fuse_current_weather", "get_user_language", "geocode_city",
    "get_current_weather", "get_weather_forecast", "get_hourly_forecast", "get_air_quality",
    "get_uv_index_and_sun", "get_surface_pressure_and_wind",
    "get_agricultural_crop_telemetry", "get_severe_weather_alerts",
]


@tool
def geocode_city(city_name: str) -> dict:
    """Convert a city name to latitude/longitude. Always call this first before weather tools."""
    return _geocode(city_name)


@tool
def get_current_weather(latitude: float, longitude: float) -> dict:
    """Get current weather conditions using multi-source telemetry fusion (Open-Meteo > AccuWeather > WeatherAPI, Tomorrow.io, OpenWeather). Call geocode_city first for coordinates."""
    return fuse_current_weather(latitude, longitude)


@tool
def get_weather_forecast(latitude: float, longitude: float, days: int = 7) -> dict:
    """Get daily forecast up to 16 days. Call geocode_city first."""
    try:
        forecast_days = min(days, 16)
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
            # Support both 'weather_code' (new) and 'weathercode' (old) response keys
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
            return {"forecast": forecast}
    except Exception as e:
        return {"error": str(e)}


@tool
def get_air_quality(latitude: float, longitude: float) -> dict:
    """Get live US AQI, PM2.5, PM10, NO2, SO2, CO, and Ozone levels for a location. Call geocode_city first for coordinates."""
    try:
        with httpx.Client(timeout=10) as client:
            res = client.get(
                "https://air-quality-api.open-meteo.com/v1/air-quality",
                params={
                    "latitude": latitude,
                    "longitude": longitude,
                    "current": "us_aqi,pm10,pm2_5,carbon_monoxide,nitrogen_dioxide,sulphur_dioxide,ozone",
                    "timezone": "auto",
                },
            )
            data = res.json()
            curr = data.get("current", {})
            us_aqi = curr.get("us_aqi", 42)

            category = "Good"
            if us_aqi > 300:
                category = "Hazardous"
            elif us_aqi > 200:
                category = "Very Unhealthy"
            elif us_aqi > 150:
                category = "Unhealthy"
            elif us_aqi > 100:
                category = "Unhealthy for Sensitive Groups"
            elif us_aqi > 50:
                category = "Moderate"

            return {
                "us_aqi": us_aqi,
                "category": category,
                "pm2_5": curr.get("pm2_5"),
                "pm10": curr.get("pm10"),
                "nitrogen_dioxide": curr.get("nitrogen_dioxide"),
                "ozone": curr.get("ozone"),
            }
    except Exception as e:
        return {"error": str(e)}


@tool
def get_hourly_forecast(latitude: float, longitude: float) -> dict:
    """Get detailed 24-hour hourly weather breakdown (temperatures, precipitation probability, wind, humidity). Call geocode_city first."""
    try:
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
            codes = hourly.get("weather_code", hourly.get("weathercode", []))[:24]

            hours_data = []
            for i in range(len(times)):
                w_code = codes[i] if i < len(codes) else 0
                hours_data.append({
                    "time": times[i],
                    "temp_celsius": temps[i] if i < len(temps) else None,
                    "feels_like_celsius": feels[i] if i < len(feels) else None,
                    "rain_probability_percent": precip[i] if i < len(precip) else 0,
                    "condition": WEATHER_CODES.get(w_code, "Clear"),
                })
            return {"hourly_forecast": hours_data}
    except Exception as e:
        return {"error": str(e)}


@tool
def get_uv_index_and_sun(latitude: float, longitude: float) -> dict:
    """Get UV Index, daily max UV index, sunrise, sunset, and solar advisories for a location. Call geocode_city first."""
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
            current_uv = data.get("current", {}).get("uv_index", 0)
            daily = data.get("daily", {})
            uv_max = daily.get("uv_index_max", [current_uv])[0]
            sunrise = daily.get("sunrise", ["06:00"])[0]
            sunset = daily.get("sunset", ["18:30"])[0]

            uv_category = "Low"
            uv_advisory = "Minimal sun exposure risk. Enjoy outdoor activities!"
            if uv_max >= 8:
                uv_category = "Very High / Extreme"
                uv_advisory = "Extreme UV risk! Seek shade during midday (10am-4pm), wear SPF 30+ sunscreen, sunglasses, and protective hat."
            elif uv_max >= 6:
                uv_category = "High"
                uv_advisory = "High UV index. Reduce direct sun exposure during peak afternoon hours."
            elif uv_max >= 3:
                uv_category = "Moderate"
                uv_advisory = "Moderate UV index. Wear sunglasses and SPF 30+ if outdoors for extended periods."

            return {
                "current_uv_index": round(current_uv, 1),
                "max_uv_index_today": round(uv_max, 1),
                "uv_category": uv_category,
                "uv_advisory": uv_advisory,
                "sunrise_time": sunrise,
                "sunset_time": sunset,
            }
    except Exception as e:
        return {"error": str(e)}


@tool
def get_surface_pressure_and_wind(latitude: float, longitude: float) -> dict:
    """Get barometric surface pressure (hPa), wind direction degrees, cardinal direction (N, NE, E, SE, S, SW, W, NW), and wind gusts. Call geocode_city first."""
    try:
        with httpx.Client(timeout=10) as client:
            res = client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": latitude,
                    "longitude": longitude,
                    "current": "surface_pressure,wind_speed_10m,wind_direction_10m,wind_gusts_10m",
                    "timezone": "auto",
                },
            )
            data = res.json()
            curr = data.get("current", {})
            pressure = curr.get("surface_pressure", 1013)
            wind_deg = curr.get("wind_direction_10m", 0)
            wind_speed = curr.get("wind_speed_10m", 0)
            gusts = curr.get("wind_gusts_10m", wind_speed * 1.3)

            directions = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
            cardinal = directions[int(round(wind_deg / 45)) % 8]

            return {
                "surface_pressure_hpa": round(pressure, 1),
                "pressure_status": "Standard atmospheric pressure" if 1005 <= pressure <= 1020 else "Low pressure system" if pressure < 1005 else "High pressure system",
                "wind_speed_kmh": round(wind_speed, 1),
                "wind_gusts_kmh": round(gusts, 1),
                "wind_direction_degrees": wind_deg,
                "wind_cardinal_direction": cardinal,
            }
    except Exception as e:
        return {"error": str(e)}


@tool
def get_agricultural_crop_telemetry(latitude: float, longitude: float, crop: str = "Cotton") -> dict:
    """Get agricultural crop telemetry: soil moisture (0-7cm & 7-28cm depth), soil temperature, evapotranspiration (ET0), and crop stress advisory. Call geocode_city first."""
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

            soil_moist_top = curr.get("soil_moisture_0_to_7cm", 0.25)
            soil_moist_sub = curr.get("soil_moisture_7_to_28cm", 0.28)
            soil_temp = curr.get("soil_temperature_0cm", 25)
            et0_today = daily.get("et0_fao_evapotranspiration", [3.5])[0]
            rain_today = daily.get("precipitation_sum", [0])[0]

            crop_name = crop.strip() if crop else "Crops"

            # Irrigation & Crop Risk Evaluation
            irrigation_needed = rain_today < 2.0 and soil_moist_top < 0.20
            spraying_safe = rain_today < 1.0

            return {
                "crop": crop_name,
                "soil_moisture_surface_m3m3": round(soil_moist_top, 3),
                "soil_moisture_rootzone_m3m3": round(soil_moist_sub, 3),
                "soil_temperature_celsius": round(soil_temp, 1),
                "evapotranspiration_et0_mm": round(et0_today, 2),
                "expected_rainfall_mm": round(rain_today, 1),
                "irrigation_advisory": f"Irrigation recommended for {crop_name} today due to low soil moisture and dry weather." if irrigation_needed else f"Sufficient soil moisture for {crop_name}. Delay irrigation to conserve water.",
                "pesticide_spraying_window": "Favorable window for pesticide/fertilizer spraying (low rain risk)." if spraying_safe else "Avoid pesticide spraying today due to impending rainfall wash-off risk.",
            }
    except Exception as e:
        return {"error": str(e)}


@tool
def get_severe_weather_alerts(latitude: float, longitude: float) -> dict:
    """Get severe weather hazard alerts (Heavy Rain, Heatwave, Thunderstorm, Cyclone, Fog) for coordinates. Call geocode_city first."""
    try:
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
            max_temp = daily.get("temperature_2m_max", [30])[0]
            rain_prob = daily.get("precipitation_probability_max", [0])[0]
            max_wind = daily.get("wind_speed_10m_max", [10])[0]
            w_code = daily.get("weather_code", [0])[0]

            level = "GREEN"
            title = "No Severe Weather Hazards Reported"
            advisory = "Normal atmospheric conditions."
            action = "Enjoy your day normally."

            if max_temp >= 42:
                level = "RED"
                title = "RED ALERT: Severe Heatwave Warning"
                advisory = f"Extreme temperatures reaching {max_temp}°C. High risk of heatstroke."
                action = "STAY INDOORS: Avoid outdoor exposure between 11am-4pm. Drink electrolyte fluid."
            elif rain_prob >= 80 or w_code in [65, 82, 95, 96, 99]:
                level = "ORANGE"
                title = "ORANGE ALERT: Heavy Rainfall / Severe Thunderstorm"
                advisory = f"Heavy rainfall expected (rain probability {rain_prob}%). Waterlogging likely."
                action = "BE PREPARED: Avoid low-lying flooded roads and carry umbrellas."
            elif max_wind >= 40:
                level = "YELLOW"
                title = "YELLOW ALERT: High Wind Advisory"
                advisory = f"Strong wind gusts up to {max_wind} km/h."
                action = "WATCHFUL: Secure outdoor furniture and loose objects."

            return {
                "alert_level": level,
                "title": title,
                "advisory": advisory,
                "recommended_action": action,
                "source": "Live Meteorological Telemetry Engine"
            }
    except Exception as e:
        return {"error": str(e)}



