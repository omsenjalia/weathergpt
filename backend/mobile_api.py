"""Mobile app REST endpoints (Flutter WeatherGPT).

These routes match docs/web_app_api_contract.md used by weathergpt-app.
Weather data is proxied from Open-Meteo (no API key required).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(tags=["mobile"])

# WMO weather interpretation codes (Open-Meteo)
_WEATHER_CODES: dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


def _code_to_condition(code: Any) -> str:
    try:
        return _WEATHER_CODES.get(int(code), "Unknown")
    except (TypeError, ValueError):
        return "Unknown"


def _get_json(url: str, params: dict[str, Any], timeout: float = 12.0) -> dict[str, Any]:
    try:
        with httpx.Client(timeout=timeout) as client:
            res = client.get(url, params=params)
            res.raise_for_status()
            data = res.json()
            if not isinstance(data, dict):
                raise HTTPException(status_code=502, detail="Unexpected weather upstream response")
            return data
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="Weather upstream timed out") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Weather upstream error: {exc}") from exc


@router.get("/weather")
async def get_weather(
    lat: float = Query(..., description="Latitude"),
    lon: float = Query(..., description="Longitude"),
    language: str = Query("en", description="Preferred language code"),
) -> dict[str, Any]:
    """Current conditions + today high/low for the Flutter home screens."""
    data = _get_json(
        "https://api.open-meteo.com/v1/forecast",
        {
            "latitude": lat,
            "longitude": lon,
            "current": (
                "temperature_2m,apparent_temperature,relative_humidity_2m,"
                "weather_code,wind_speed_10m,surface_pressure,precipitation"
            ),
            "daily": (
                "temperature_2m_max,temperature_2m_min,"
                "precipitation_probability_max,weather_code,rain_sum"
            ),
            "forecast_days": 4,
            "timezone": "auto",
        },
    )
    current = data.get("current") or {}
    daily = data.get("daily") or {}

    code = current.get("weather_code", current.get("weathercode", 0))
    highs = daily.get("temperature_2m_max") or []
    lows = daily.get("temperature_2m_min") or []
    rain_probs = daily.get("precipitation_probability_max") or []
    daily_codes = daily.get("weather_code") or daily.get("weathercode") or []
    rain_sums = daily.get("rain_sum") or []
    dates = daily.get("time") or []

    forecast = []
    for i in range(min(3, len(dates))):
        forecast.append(
            {
                "date": dates[i],
                "high_c": highs[i] if i < len(highs) else None,
                "low_c": lows[i] if i < len(lows) else None,
                "rain_probability": rain_probs[i] if i < len(rain_probs) else None,
                "rain_mm": rain_sums[i] if i < len(rain_sums) else None,
                "condition": _code_to_condition(
                    daily_codes[i] if i < len(daily_codes) else code
                ),
            }
        )

    return {
        "lat": lat,
        "lon": lon,
        "language": language,
        "temperature_c": current.get("temperature_2m"),
        "feels_like_c": current.get("apparent_temperature"),
        "condition": _code_to_condition(code),
        "weather_code": code,
        "high_c": highs[0] if highs else current.get("temperature_2m"),
        "low_c": lows[0] if lows else current.get("temperature_2m"),
        "rain_probability": rain_probs[0] if rain_probs else 0,
        "wind_kmh": current.get("wind_speed_10m"),
        "humidity": current.get("relative_humidity_2m"),
        "pressure_hpa": current.get("surface_pressure"),
        "precipitation_mm": current.get("precipitation"),
        "timezone": data.get("timezone"),
        "forecast": forecast,
        "source": "open-meteo",
        "fetched_at": datetime.utcnow().isoformat() + "Z",
    }


@router.get("/advisory")
async def get_advisory(
    lat: float = Query(...),
    lon: float = Query(...),
    crop: str = Query("", description="Optional crop name"),
    days: int = Query(3, ge=1, le=7),
) -> dict[str, Any]:
    """Simple farm action-window style advisory for mobile farmer mode."""
    data = _get_json(
        "https://api.open-meteo.com/v1/forecast",
        {
            "latitude": lat,
            "longitude": lon,
            "daily": (
                "temperature_2m_max,temperature_2m_min,precipitation_probability_max,"
                "rain_sum,wind_speed_10m_max,weather_code"
            ),
            "forecast_days": days,
            "timezone": "auto",
        },
    )
    daily = data.get("daily") or {}
    dates = daily.get("time") or []
    rain_probs = daily.get("precipitation_probability_max") or []
    rain_sums = daily.get("rain_sum") or []
    wind_max = daily.get("wind_speed_10m_max") or []
    highs = daily.get("temperature_2m_max") or []

    windows = []
    for i, date in enumerate(dates):
        rp = rain_probs[i] if i < len(rain_probs) else 0
        rs = rain_sums[i] if i < len(rain_sums) else 0
        wind = wind_max[i] if i < len(wind_max) else 0
        high = highs[i] if i < len(highs) else None

        if rp >= 70 or (isinstance(rs, (int, float)) and rs >= 10):
            suitability = "poor"
            note = "Heavy rain likely — avoid spraying and limit field work."
            best = "Indoor / planning tasks"
        elif rp >= 40 or (isinstance(wind, (int, float)) and wind >= 25):
            suitability = "caution"
            note = "Workable with caution — watch wind and showers."
            best = "Plan for afternoon gaps"
        else:
            suitability = "good"
            note = "Good day for field work."
            best = "Best: 6–10 AM"
        if high is not None and high >= 40:
            suitability = "caution"
            note = "Heat stress risk — irrigate early morning or evening."
            best = "Avoid midday field work"

        windows.append(
            {
                "date": date,
                "suitability": suitability,
                "summary": note,
                "best_window": best,
                "rain_probability": rp,
                "rain_mm": rs,
                "wind_kmh_max": wind,
                "high_c": high,
            }
        )

    crop_label = crop.strip() or "general crops"
    good_days = sum(1 for w in windows if w["suitability"] == "good")
    summary = (
        f"Advisory for {crop_label}: {good_days}/{len(windows)} day(s) look favourable "
        f"near ({lat:.2f}, {lon:.2f})."
    )
    return {
        "lat": lat,
        "lon": lon,
        "crop": crop_label,
        "summary": summary,
        "windows": windows,
        "source": "open-meteo",
    }


@router.get("/historical")
async def get_historical(
    lat: float = Query(...),
    lon: float = Query(...),
    metric: str = Query("rainfall", description="rainfall | temperature | humidity"),
    start_year: int = Query(2000, ge=1940, le=2100),
    end_year: int = Query(2024, ge=1940, le=2100),
) -> dict[str, Any]:
    """Yearly historical series via Open-Meteo archive (mobile researcher screens)."""
    if end_year < start_year:
        raise HTTPException(status_code=400, detail="end_year must be >= start_year")
    if end_year - start_year > 40:
        raise HTTPException(status_code=400, detail="Maximum range is 40 years")

    metric_key = metric.lower().strip()
    daily_var = {
        "rainfall": "precipitation_sum",
        "temperature": "temperature_2m_mean",
        "humidity": "relative_humidity_2m_mean",
    }.get(metric_key)
    if not daily_var:
        raise HTTPException(
            status_code=400,
            detail="metric must be one of: rainfall, temperature, humidity",
        )

    # Open-Meteo archive — request full range then aggregate by year client-side
    data = _get_json(
        "https://archive-api.open-meteo.com/v1/archive",
        {
            "latitude": lat,
            "longitude": lon,
            "start_date": f"{start_year}-01-01",
            "end_date": f"{end_year}-12-31",
            "daily": daily_var,
            "timezone": "auto",
        },
        timeout=30.0,
    )
    daily = data.get("daily") or {}
    times = daily.get("time") or []
    values = daily.get(daily_var) or []

    buckets: dict[int, list[float]] = {}
    for t, v in zip(times, values):
        if v is None:
            continue
        try:
            year = int(str(t)[:4])
            buckets.setdefault(year, []).append(float(v))
        except (TypeError, ValueError):
            continue

    points = []
    for year in range(start_year, end_year + 1):
        vals = buckets.get(year)
        if not vals:
            continue
        if metric_key == "rainfall":
            value = round(sum(vals), 1)
        else:
            value = round(sum(vals) / len(vals), 2)
        points.append({"year": year, "value": value})

    return {
        "lat": lat,
        "lon": lon,
        "metric": metric_key,
        "start_year": start_year,
        "end_year": end_year,
        "points": points,
        "source": "open-meteo-archive",
    }


@router.get("/comparison")
async def get_comparison(
    locations: str = Query(
        ...,
        description="Semicolon-separated list: name,lat,lon;name2,lat2,lon2",
    ),
    metric: str = Query("rainfall"),
    start_year: int = Query(2015),
    end_year: int = Query(2024),
) -> dict[str, Any]:
    """Compare yearly metric across multiple named locations."""
    series = []
    for chunk in locations.split(";"):
        parts = [p.strip() for p in chunk.split(",")]
        if len(parts) != 3:
            continue
        name, lat_s, lon_s = parts
        try:
            lat_f, lon_f = float(lat_s), float(lon_s)
        except ValueError:
            continue
        hist = await get_historical(
            lat=lat_f,
            lon=lon_f,
            metric=metric,
            start_year=start_year,
            end_year=end_year,
        )
        series.append({"name": name, "lat": lat_f, "lon": lon_f, "points": hist["points"]})

    if not series:
        raise HTTPException(
            status_code=400,
            detail="Provide locations as name,lat,lon;name2,lat2,lon2",
        )

    return {
        "metric": metric.lower().strip(),
        "start_year": start_year,
        "end_year": end_year,
        "locations": series,
        "source": "open-meteo-archive",
    }
