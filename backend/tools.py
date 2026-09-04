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


# Open-Meteo renamed the variable from `weathercode` to `weather_code`.
# Both names are accepted in API requests; the response uses the name you sent.
# Added missing snow / freezing-rain codes (71-77, 85-86).
WEATHER_CODES = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Foggy",
    48: "Icy fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


def _extract_weather_code(data: dict) -> int:
    """Return the weather code from a response dict, handling both naming conventions."""
    return data.get("weather_code", data.get("weathercode", -1))


@tool
def geocode_city(city_name: str) -> dict:
    """Convert a city name to latitude/longitude. Always call this first before weather tools."""
    try:
        with httpx.Client(timeout=10) as client:
            response = client.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": city_name, "count": 1, "language": "en"},
            )
            data = response.json()
            if "results" in data and data["results"]:
                result = data["results"][0]
                return {
                    "latitude": result["latitude"],
                    "longitude": result["longitude"],
                    "city": result.get("name", city_name),
                    "country": result.get("country", ""),
                    "state": result.get("admin1", ""),
                }
            return {"error": f"City '{city_name}' not found"}
    except Exception as e:
        return {"error": str(e)}


import os

@tool
def get_current_weather(latitude: float, longitude: float) -> dict:
    """Get current weather conditions using multi-source telemetry fusion (Open-Meteo, WeatherAPI, Tomorrow.io, OpenWeather, AccuWeather). Call geocode_city first for coordinates."""
    try:
        sources = []
        with httpx.Client(timeout=10) as client:
            # 1. Base Open-Meteo
            try:
                res = client.get(
                    "https://api.open-meteo.com/v1/forecast",
                    params={
                        "latitude": latitude,
                        "longitude": longitude,
                        "current": "temperature_2m,apparent_temperature,wind_speed_10m,precipitation,relative_humidity_2m,weather_code",
                        "timezone": "auto",
                    },
                )
                data = res.json()
                current = data.get("current", {})
                w_code = _extract_weather_code(current)
                sources.append({
                    "name": "Open-Meteo (ECMWF)",
                    "temp": current.get("temperature_2m"),
                    "feelsLike": current.get("apparent_temperature"),
                    "humidity": current.get("relative_humidity_2m"),
                    "windSpeed": current.get("wind_speed_10m"),
                    "code": w_code,
                    "condition": WEATHER_CODES.get(w_code, "Unknown"),
                    "weight": 1.0,
                })
            except Exception:
                pass

            # 2. WeatherAPI.com
            wapi_key = os.getenv("WEATHERAPI_KEY") or os.getenv("VITE_WEATHERAPI_KEY")
            if wapi_key:
                try:
                    res = client.get(
                        "https://api.weatherapi.com/v1/current.json",
                        params={"key": wapi_key, "q": f"{latitude},{longitude}"},
                    )
                    curr = res.json().get("current", {})
                    if "temp_c" in curr:
                        sources.append({
                            "name": "WeatherAPI.com",
                            "temp": curr.get("temp_c"),
                            "feelsLike": curr.get("feelslike_c"),
                            "humidity": curr.get("humidity"),
                            "windSpeed": curr.get("wind_kph"),
                            "condition": curr.get("condition", {}).get("text"),
                            "weight": 1.2,
                        })
                except Exception:
                    pass

            # 3. OpenWeatherMap
            owm_key = os.getenv("OPENWEATHER_KEY") or os.getenv("VITE_OPENWEATHER_KEY")
            if owm_key:
                try:
                    res = client.get(
                        "https://api.openweathermap.org/data/2.5/weather",
                        params={"lat": latitude, "lon": longitude, "appid": owm_key, "units": "metric"},
                    )
                    main = res.json().get("main", {})
                    if "temp" in main:
                        sources.append({
                            "name": "OpenWeatherMap",
                            "temp": main.get("temp"),
                            "feelsLike": main.get("feels_like"),
                            "humidity": main.get("humidity"),
                            "windSpeed": res.json().get("wind", {}).get("speed", 0) * 3.6,
                            "condition": res.json().get("weather", [{}])[0].get("description"),
                            "weight": 1.1,
                        })
                except Exception:
                    pass

        if not sources:
            return {"error": "Failed to retrieve weather data from providers"}

        # Compute weighted averages
        total_w = sum(s["weight"] for s in sources if s.get("temp") is not None)
        weighted_temp = sum(s["temp"] * s["weight"] for s in sources if s.get("temp") is not None) / total_w if total_w > 0 else sources[0]["temp"]
        weighted_feels = sum((s.get("feelsLike") or s["temp"]) * s["weight"] for s in sources if s.get("temp") is not None) / total_w if total_w > 0 else weighted_temp
        weighted_humidity = sum((s.get("humidity") or 50) * s["weight"] for s in sources if s.get("temp") is not None) / total_w if total_w > 0 else 50
        weighted_wind = sum((s.get("windSpeed") or 0) * s["weight"] for s in sources if s.get("temp") is not None) / total_w if total_w > 0 else 0

        base = sources[0]
        return {
            "temperature_2m": round(weighted_temp, 1),
            "apparent_temperature": round(weighted_feels, 1),
            "relative_humidity_2m": round(weighted_humidity),
            "wind_speed_10m": round(weighted_wind, 1),
            "weathercode": base.get("code", 0),
            "condition": base.get("condition", "Normal"),
            "providers_used": [s["name"] for s in sources],
        }
    except Exception as e:
        return {"error": str(e)}


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

