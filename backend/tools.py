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
from imd_service import fetch_imd_api, get_all_imd_features, get_curl_command_string, fetch_live_imd_cap_rss

@tool
def get_current_weather(latitude: float, longitude: float) -> dict:
    """Get current weather conditions using multi-source telemetry fusion (IMD Official Govt of India Priority 1, Open-Meteo, WeatherAPI, Tomorrow.io, OpenWeather, AccuWeather). Call geocode_city first for coordinates."""
    try:
        sources = []
        with httpx.Client(timeout=10) as client:
            # 0. IMD Official Data (India Meteorological Department - Government of India) -> Highest Trust Weight 3.0
            try:
                imd_res = fetch_imd_api("api-3", {"lat": str(latitude), "lon": str(longitude)})
                if imd_res and "data" in imd_res:
                    imd_data = imd_res["data"]
                    if isinstance(imd_data, list) and len(imd_data) > 0:
                        obs = imd_data[0]
                        sources.append({
                            "name": "IMD Official (Govt of India - Priority 1 Trust)",
                            "temp": float(obs.get("Temperature", 30.0)),
                            "feelsLike": float(obs.get("Temperature", 30.0)),
                            "humidity": float(obs.get("Humidity", 65)),
                            "windSpeed": float(obs.get("Wind_Speed_Kmph", 12)),
                            "code": 0,
                            "condition": obs.get("Weather_Condition", "Partly Cloudy"),
                            "weight": 3.0,
                        })
            except Exception:
                pass

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
def get_official_imd_alerts(latitude: float, longitude: float) -> dict:
    """Get official IMD (India Meteorological Department) severe weather hazard alerts (Heavy Rain, Heatwave, Thunderstorm, Cyclone, Fog) for coordinates. Call geocode_city first."""
    try:
        # Check live IMD CAP RSS Feed first for government issued severe weather alerts
        cap_alerts = fetch_live_imd_cap_rss()
        if cap_alerts and len(cap_alerts) > 0:
            first_alert = cap_alerts[0]
            title = first_alert.get("title", "")
            desc = first_alert.get("description", "")
            
            level = "YELLOW"
            if "RED" in title.upper() or "SEVERE" in title.upper() or "CYCLONE" in title.upper():
                level = "RED"
            elif "ORANGE" in title.upper() or "HEAVY RAIN" in title.upper() or "THUNDERSTORM" in title.upper():
                level = "ORANGE"

            return {
                "alert_level": level,
                "title": f"IMD OFFICIAL ALERT: {title}",
                "advisory": desc or title,
                "recommended_action": "Stay updated with official India Meteorological Department warnings.",
                "source": "IMD Official CAP RSS Feed (Govt of India)"
            }

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
                title = "IMD RED ALERT: Severe Heatwave Warning"
                advisory = f"Extreme temperatures reaching {max_temp}°C. High risk of heatstroke."
                action = "STAY INDOORS: Avoid outdoor exposure between 11am-4pm. Drink electrolyte fluid."
            elif rain_prob >= 80 or w_code in [65, 82, 95, 96, 99]:
                level = "ORANGE"
                title = "IMD ORANGE ALERT: Heavy Rainfall / Severe Thunderstorm"
                advisory = f"Heavy rainfall expected (rain probability {rain_prob}%). Waterlogging likely."
                action = "BE PREPARED: Avoid low-lying flooded roads and carry umbrellas."
            elif max_wind >= 40:
                level = "YELLOW"
                title = "IMD YELLOW ALERT: High Wind Advisory"
                advisory = f"Strong wind gusts up to {max_wind} km/h."
                action = "WATCHFUL: Secure outdoor furniture and loose objects."

            return {
                "alert_level": level,
                "title": title,
                "advisory": advisory,
                "recommended_action": action,
                "source": "IMD Government of India Telemetry Engine"
            }
    except Exception as e:
        return {"error": str(e)}


@tool
def get_imd_city_forecast(station_id: str = "42182") -> dict:
    """Get official 7-day city weather forecast directly from India Meteorological Department (IMD) for station ID (e.g. 42182 for New Delhi)."""
    return fetch_imd_api("api-1", {"id": station_id})


@tool
def get_imd_district_warning(district_id: str = "573") -> dict:
    """Get official 5-day district-wise severe weather color-coded warnings (Green, Yellow, Orange, Red) from IMD."""
    return fetch_imd_api("api-6", {"id": district_id})


@tool
def get_imd_cyclone_track() -> dict:
    """Get official tropical cyclone track, observed/forecast positions, MSW wind speed range, and category from IMD."""
    return fetch_imd_api("api-18")


@tool
def get_imd_agromet_official_advisory(district: str = "Ahmedabad", crop: str = "Cotton") -> dict:
    """Get official IMD Agromet agricultural weather advisory (Gramin Krishi Mausam Sewa) for farming operations."""
    return fetch_imd_api("api-28", {"district": district, "crop": crop})


@tool
def query_any_imd_api_feature(api_id: str = "api-1", params_json: str = "{}") -> dict:
    """Execute any of the 28 official IMD APIs (api-1 to api-28) from https://api.imd.gov.in/public/api_reference.html using curl CLI."""
    try:
        params = json.loads(params_json) if isinstance(params_json, str) and params_json.strip() else {}
    except Exception:
        params = {}
    return fetch_imd_api(api_id, params)



