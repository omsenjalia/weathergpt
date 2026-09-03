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
                    # Use the current variable name; also accepted as 'weathercode'
                    "current": "temperature_2m,apparent_temperature,wind_speed_10m,precipitation,relative_humidity_2m,weather_code",
                    "timezone": "auto",
                },
            )
            data = response.json()
            current = data.get("current", {})
            weather_code = _extract_weather_code(current)
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
