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
            "en": "English",
        }
        return language_map.get(lang_code, "English")
    except Exception:
        return "English"


WEATHER_CODES = {
    0: "Clear sky",
    1: "Partly cloudy",
    2: "Partly cloudy",
    3: "Partly cloudy",
    45: "Foggy",
    48: "Foggy",
    51: "Drizzle",
    53: "Drizzle",
    55: "Drizzle",
    61: "Moderate rain",
    63: "Moderate rain",
    65: "Heavy rain",
    80: "Rain showers",
    81: "Rain showers",
    82: "Rain showers",
    95: "Thunderstorm",
    96: "Thunderstorm",
    99: "Thunderstorm",
}


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


@tool
def get_current_weather(latitude: float, longitude: float) -> dict:
    """Get current weather conditions. Call geocode_city first for coordinates."""
    try:
        with httpx.Client(timeout=10) as client:
            response = client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": latitude,
                    "longitude": longitude,
                    "current": "temperature_2m,apparent_temperature,wind_speed_10m,precipitation,relative_humidity_2m,weathercode",
                    "timezone": "auto",
                },
            )
            data = response.json()
            current = data.get("current", {})
            weather_code = current.get("weathercode", -1)
            condition = WEATHER_CODES.get(weather_code, "Unknown")
            return {
                "temperature_2m": current.get("temperature_2m"),
                "apparent_temperature": current.get("apparent_temperature"),
                "wind_speed_10m": current.get("wind_speed_10m"),
                "precipitation": current.get("precipitation"),
                "relative_humidity_2m": current.get("relative_humidity_2m"),
                "weathercode": weather_code,
                "condition": condition,
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
                    "daily": "temperature_2m_max,temperature_2m_min,rain_sum,precipitation_probability_max,wind_speed_10m_max,weathercode",
                    "forecast_days": forecast_days,
                    "timezone": "auto",
                },
            )
            data = response.json()
            daily = data.get("daily", {})
            dates = daily.get("time", [])
            forecast = []
            for i, date in enumerate(dates):
                weather_code = daily.get("weathercode", [])[i] if i < len(daily.get("weathercode", [])) else -1
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
