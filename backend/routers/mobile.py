"""Mobile app REST endpoints (Flutter `weathergpt-app`).

Routes match `docs/web_app_api_contract.md` in weathergpt-app. Forecast structure, UV,
AQI and sun times come from shared forecast service with IMD -> WeatherNext ->
AccuWeather -> Open-Meteo priority. Legacy Open-Meteo direct path retained for
backward compatibility but now goes through forecast service.

Fixes:
- Heat handling uses worst-band merging, not unconditional caution override
- Hourly bands use data-sufficiency gate
- Advisory uses fixed deterministic baseline before Jev overlay
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

from services import advisory as advisory_ai
from services import typesafe
from services.fusion import fuse_current_weather
from services.open_meteo import (
    AIR_QUALITY_URL,
    ARCHIVE_URL,
    FORECAST_URL,
    UpstreamError,
    code_to_condition as _code_to_condition,
    extract_weather_code,
    get_json,
)
from services.forecast import get_forecast_service
from services.config import get_config

router = APIRouter(tags=["mobile"])


def _bounded(value: Any, low: float | None = None, high: float | None = None) -> float | None:
    """Return finite numeric upstream data, optionally constrained to a physical range."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    if low is not None and number < low or high is not None and number > high:
        return None
    return number


def _get_json(url: str, params: dict[str, Any], timeout: float = 12.0) -> dict[str, Any]:
    try:
        return get_json(url, params, timeout=timeout)
    except UpstreamError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/weather")
async def get_weather(
    lat: float = Query(..., ge=-90, le=90, description="Latitude (-90 to 90)"),
    lon: float = Query(..., ge=-180, le=180, description="Longitude (-180 to 180)"),
    language: str = Query("en", description="Preferred language code"),
    source: str = Query("auto", description="auto|imd|weathernext|accuweather|open_meteo (researcher mode)"),
    mode: str = Query("everyone", description="everyone|farmer|researcher"),
) -> dict[str, Any]:
    """Current conditions + today high/low + 3-day outlook for the Flutter home screens.

    Uses shared forecast service with IMD -> WeatherNext -> AccuWeather -> Open-Meteo.
    Explicit source pins bypass automatic substitution for researcher mode.
    """
    return await run_in_threadpool(_build_weather_snapshot, lat, lon, language, source, mode)


def _build_weather_snapshot(lat: float, lon: float, language: str, source: str = "auto", mode: str = "everyone") -> dict[str, Any]:
    # Try new forecast service first
    forecast_service = get_forecast_service()
    selection = forecast_service.select_forecast(
        lat=lat,
        lon=lon,
        product="forecast",
        requested_source=source,
        mode=mode,
        forecast_days=7,
    )

    # If new service succeeds, use it
    if selection.forecast:
        fc = selection.forecast
        # Build response from normalized forecast
        current = fc.current
        daily_list = fc.daily
        hourly_list = fc.hourly

        # Legacy compatibility: map to old structure but with provenance
        temp_c = current.temperature_c if current else None
        feels_c = current.feels_like_c if current else None
        humidity = current.humidity_percent if current else None
        wind_kmh = current.wind_speed_kmh if current else None
        pressure = current.pressure_hpa if current else None
        condition = current.condition if current else "Unknown"
        weather_code = current.weather_code if current else 0

        # Air quality from forecast or best-effort
        aqi = None
        pm25 = None
        if fc.air_quality:
            aqi = fc.air_quality.get("european_aqi")
            pm25 = fc.air_quality.get("pm2_5")
        else:
            try:
                aq = _get_json(
                    AIR_QUALITY_URL,
                    {"latitude": lat, "longitude": lon, "current": "european_aqi,pm2_5", "timezone": "auto"},
                    timeout=8.0,
                )
                cur_aq = aq.get("current") or {}
                aqi = cur_aq.get("european_aqi")
                pm25 = cur_aq.get("pm2_5")
            except Exception:
                pass

        # Build hourly_out for legacy
        hourly_out = []
        for p in hourly_list[:24]:
            hourly_out.append({
                "time": p.time_utc.isoformat(),
                "temperature_c": p.temperature_c,
                "rain_probability": p.precipitation_probability,
            })

        # Forecast 3-day
        forecast = []
        for d in daily_list[:3]:
            forecast.append({
                "date": d.get("date"),
                "high_c": d.get("high_c"),
                "low_c": d.get("low_c"),
                "rain_probability": d.get("rain_probability"),
                "rain_mm": d.get("rain_mm"),
                "condition": d.get("condition"),
            })

        # UV, sunrise/sunset from daily
        uv_index = None
        sunrise = None
        sunset = None
        if daily_list:
            uv_index = daily_list[0].get("uv_index") or daily_list[0].get("uv_index_max")
            sunrise = daily_list[0].get("sunrise")
            sunset = daily_list[0].get("sunset")

        temp_c = _bounded(temp_c, -100, 70)
        feels_c = _bounded(feels_c, -100, 80)
        humidity = _bounded(humidity, 0, 100)
        wind_kmh = _bounded(wind_kmh, 0, 500)
        pressure = _bounded(pressure, 800, 1200)

        return {
            "lat": lat,
            "lon": lon,
            "language": language,
            "temperature_c": temp_c,
            "feels_like_c": feels_c,
            "condition": condition,
            "weather_code": weather_code,
            "high_c": daily_list[0].get("high_c") if daily_list else temp_c,
            "low_c": daily_list[0].get("low_c") if daily_list else temp_c,
            "rain_probability": _bounded(daily_list[0].get("rain_probability") if daily_list else None, 0, 100) or 0,
            "wind_kmh": wind_kmh,
            "wind_direction": current.wind_direction_deg if current else None,
            "humidity": humidity,
            "pressure_hpa": pressure,
            "precipitation_mm": current.precipitation_mm if current else None,
            "uv_index": uv_index,
            "sunrise": sunrise,
            "sunset": sunset,
            "aqi": aqi,
            "pm2_5": pm25,
            "hourly": hourly_out,
            "timezone": fc.location.get("timezone", "auto"),
            "forecast": forecast,
            "source": selection.selected_source.value,
            "requested_source": selection.requested_source,
            "selection_policy_version": fc.provenance.selection_policy_version,
            "providers_used": fc.provenance.sources,
            "fallback_reasons": selection.fallback_reasons,
            "provenance": fc.provenance.to_dict(),
            "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "mode": mode,
        }

    # Fallback to legacy Open-Meteo direct path if new service unavailable
    # This preserves existing behavior when WeatherNext/IMD not configured
    data = _get_json(
        FORECAST_URL,
        {
            "latitude": lat,
            "longitude": lon,
            "current": (
                "temperature_2m,apparent_temperature,relative_humidity_2m,"
                "weather_code,wind_speed_10m,wind_direction_10m,"
                "surface_pressure,precipitation"
            ),
            "hourly": "temperature_2m,precipitation_probability,weather_code",
            "daily": (
                "temperature_2m_max,temperature_2m_min,"
                "precipitation_probability_max,weather_code,rain_sum,"
                "sunrise,sunset,uv_index_max,wind_direction_10m_dominant"
            ),
            "forecast_days": 7,
            "timezone": "auto",
        },
    )
    current = data.get("current") or {}
    daily = data.get("daily") or {}

    code = extract_weather_code(current, default=0)
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

    hourly = data.get("hourly") or {}
    h_times = hourly.get("time") or []
    h_temps = hourly.get("temperature_2m") or []
    h_pop = hourly.get("precipitation_probability") or []
    hourly_out = []
    for i in range(min(24, len(h_times))):
        hourly_out.append({
            "time": h_times[i],
            "temperature_c": h_temps[i] if i < len(h_temps) else None,
            "rain_probability": h_pop[i] if i < len(h_pop) else None,
        })

    sunrises = daily.get("sunrise") or []
    sunsets = daily.get("sunset") or []
    uv_max = daily.get("uv_index_max") or []
    wind_dir = current.get("wind_direction_10m")

    aqi = None
    pm25 = None
    try:
        aq = _get_json(
            AIR_QUALITY_URL,
            {"latitude": lat, "longitude": lon, "current": "european_aqi,pm2_5", "timezone": "auto"},
            timeout=8.0,
        )
        cur_aq = aq.get("current") or {}
        aqi = cur_aq.get("european_aqi")
        pm25 = cur_aq.get("pm2_5")
    except Exception:
        pass

    providers_used = ["Open-Meteo (ECMWF)"]
    source_label = "open-meteo"
    fusion_meta: dict[str, Any] = {}
    temp_c = current.get("temperature_2m")
    feels_c = current.get("apparent_temperature")
    humidity = current.get("relative_humidity_2m")
    wind_kmh = current.get("wind_speed_10m")
    pressure = current.get("surface_pressure")
    condition = _code_to_condition(code)
    weather_code = code
    try:
        fused = fuse_current_weather(lat, lon, open_meteo_current=current)
        if isinstance(fused, dict) and not fused.get("error"):
            temp_c = fused.get("temperature_2m", temp_c)
            feels_c = fused.get("apparent_temperature", feels_c)
            humidity = fused.get("relative_humidity_2m") or humidity
            wind_kmh = fused.get("wind_speed_10m") or wind_kmh
            pressure = fused.get("surface_pressure") or pressure
            if fused.get("condition"):
                condition = fused["condition"]
            if fused.get("weathercode") is not None:
                weather_code = fused["weathercode"]
            providers_used = fused.get("providers_used") or providers_used
            if len(providers_used) > 1:
                source_label = "multi-provider-fusion"
            fusion_meta = {
                "confidence": fused.get("confidence"),
                "temp_spread_c": fused.get("temp_spread_c"),
                "weights": fused.get("weights"),
            }
    except Exception as fuse_err:
        print(f"[mobile /weather] fusion skipped: {fuse_err}")

    temp_c = _bounded(temp_c, -100, 70)
    feels_c = _bounded(feels_c, -100, 80)
    humidity = _bounded(humidity, 0, 100)
    wind_kmh = _bounded(wind_kmh, 0, 500)
    pressure = _bounded(pressure, 800, 1200)
    rain_probability = _bounded(rain_probs[0] if rain_probs else None, 0, 100)
    return {
        "lat": lat,
        "lon": lon,
        "language": language,
        "temperature_c": temp_c,
        "feels_like_c": feels_c,
        "condition": condition,
        "weather_code": weather_code,
        "high_c": highs[0] if highs else temp_c,
        "low_c": lows[0] if lows else temp_c,
        "rain_probability": rain_probability if rain_probability is not None else 0,
        "wind_kmh": wind_kmh,
        "wind_direction": wind_dir,
        "humidity": humidity,
        "pressure_hpa": pressure,
        "precipitation_mm": current.get("precipitation"),
        "uv_index": uv_max[0] if uv_max else None,
        "sunrise": sunrises[0] if sunrises else None,
        "sunset": sunsets[0] if sunsets else None,
        "aqi": aqi,
        "pm2_5": pm25,
        "hourly": hourly_out,
        "timezone": data.get("timezone"),
        "forecast": forecast,
        "source": source_label,
        "providers_used": providers_used,
        "fusion": fusion_meta,
        "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "requested_source": source,
        "selection_policy_version": "1.0.0",
        "fallback_reasons": selection.fallback_reasons if 'selection' in locals() else [],
        "mode": mode,
    }


@router.get("/advisory")
async def get_advisory(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    crop: str = Query("", description="Optional crop name"),
    days: int = Query(3, ge=1, le=7),
    growth_stage: str = Query("", description="Optional crop growth stage (e.g. Flowering)"),
    soil: str = Query("", description="Optional soil type"),
    irrigation: str = Query("", description="Optional irrigation type"),
    source: str = Query("auto", description="Forecast source"),
    mode: str = Query("farmer", description="Mode for advisory"),
) -> dict[str, Any]:
    """Simple farm action-window style advisory for mobile farmer mode.

    Threshold-based by default. When ``TYPESAFE_API_KEY`` is configured, one
    batched System One call scores every day per activity (composite scoring)
    and may make days/hours *more* conservative with high-confidence answers.
    The response carries additive ``ai``/``hourly`` fields plus an
    ``advisory_engine`` label; older clients ignore them.

    Fixed: heat handling uses worst-band merging, not unconditional caution.
    """
    # Use forecast service for data
    def _fetch_forecast():
        service = get_forecast_service()
        result = service.select_forecast(
            lat=lat,
            lon=lon,
            product="forecast",
            requested_source=source,
            mode=mode,
            forecast_days=days,
        )
        return result

    forecast_result = await run_in_threadpool(_fetch_forecast)

    # If forecast service failed, fallback to direct Open-Meteo
    if not forecast_result.forecast:
        data = await run_in_threadpool(
            _get_json,
            FORECAST_URL,
            {
                "latitude": lat,
                "longitude": lon,
                "daily": (
                    "temperature_2m_max,temperature_2m_min,precipitation_probability_max,"
                    "rain_sum,wind_speed_10m_max,weather_code"
                ),
                "hourly": (
                    "temperature_2m,precipitation_probability,precipitation,"
                    "wind_speed_10m,weather_code"
                ),
                "forecast_days": days,
                "timezone": "auto",
            },
        )
    else:
        # Build data structure compatible with existing advisory code from normalized forecast
        fc = forecast_result.forecast
        # Map to old structure
        daily_time = [d.get("date") for d in fc.daily]
        daily_data = {
            "time": daily_time,
            "temperature_2m_max": [d.get("high_c") for d in fc.daily],
            "temperature_2m_min": [d.get("low_c") for d in fc.daily],
            "precipitation_probability_max": [d.get("rain_probability") for d in fc.daily],
            "rain_sum": [d.get("rain_mm") for d in fc.daily],
            "wind_speed_10m_max": [d.get("wind_kmh_max") or d.get("wind_max") or 0 for d in fc.daily],
            "weather_code": [d.get("weather_code") or 0 for d in fc.daily],
        }
        # Hourly
        hourly_time = [p.time_utc.isoformat() for p in fc.hourly]
        hourly_data = {
            "time": hourly_time,
            "temperature_2m": [p.temperature_c for p in fc.hourly],
            "precipitation_probability": [p.precipitation_probability for p in fc.hourly],
            "precipitation": [p.precipitation_mm for p in fc.hourly],
            "wind_speed_10m": [p.wind_speed_kmh for p in fc.hourly],
            "weather_code": [p.weather_code or 0 for p in fc.hourly],
        }
        data = {"daily": daily_data, "hourly": hourly_data}

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

        # Fixed: use worst-band merging, not unconditional override
        # Start with good, then apply worst of rain, wind, heat
        suitability = "good"
        notes = []
        best = "Best: 6–10 AM"

        # Rain check
        if rp >= 70 or (isinstance(rs, (int, float)) and rs >= 10):
            suitability = advisory_ai.worse(suitability, "poor")
            notes.append("Heavy rain likely")
        elif rp >= 40 or (isinstance(wind, (int, float)) and wind >= 25):
            suitability = advisory_ai.worse(suitability, "caution")
            notes.append("Watch wind and showers")

        # Heat check - use worse merging, not unconditional
        if high is not None and high >= 40:
            suitability = advisory_ai.worse(suitability, "caution")
            notes.append("Heat stress risk")

        # Determine summary based on final suitability (worst)
        if suitability == "poor":
            note = "Heavy rain likely — avoid spraying and limit field work." if "Heavy rain" in " ".join(notes) else "Conditions unsafe — avoid spraying and limit field work."
            best = "Indoor / planning tasks"
        elif suitability == "caution":
            if "Heat stress" in " ".join(notes):
                note = "Heat stress risk — irrigate early morning or evening."
                best = "Avoid midday field work"
            else:
                note = "Workable with caution — watch wind and showers."
                best = "Plan for afternoon gaps"
        else:
            note = "Good day for field work."
            best = "Best: 6–10 AM"

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
                "reasons": notes,
            }
        )

    crop_label = crop.strip() or "general crops"

    # Hourly activity bands for first two days
    hourly_by_date = advisory_ai.build_hourly_by_date((data.get("hourly") or {}), dates)
    for window in windows[:2]:
        window["hourly"] = hourly_by_date.get(str(window.get("date"))) or {}

    # TypeSafe overlay
    ai_meta: dict[str, Any] = {"enabled": False, "applied": False, "model": None}
    if windows and typesafe.is_enabled():
        stats = [advisory_ai.daily_stats(data.get("hourly") or {}, str(d)) for d in dates]
        # Generate evidence IDs
        evidence_ids = [f"ev_{d}_{lat:.2f}_{lon:.2f}" for d in dates]
        state_text = advisory_ai.build_state(
            crop_label, lat, lon, dates, stats,
            farm={"growth_stage": growth_stage, "soil": soil, "irrigation": irrigation},
            evidence_ids=evidence_ids,
        )
        result = typesafe.evaluate(
            state_text,
            advisory_ai.build_questions(dates, evidence_ids=evidence_ids),
            timeout=float(os.getenv("TYPESAFE_ADVISORY_TIMEOUT_SECONDS", "6")),
            label="advisory",
        )
        if result:
            ai_meta = advisory_ai.apply_typesafe_overlay(
                windows,
                hourly_by_date,
                result["answers"],
                min_confidence=float(os.getenv("TYPESAFE_ADVISORY_MIN_CONFIDENCE", "0.55")),
                model=typesafe.model_name(),
            )

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
        "advisory_engine": "system-one+thresholds" if ai_meta.get("applied") else "thresholds",
        "ai": ai_meta,
        "source": forecast_result.selected_source.value if 'forecast_result' in locals() and forecast_result.forecast else "open-meteo",
        "requested_source": source,
        "fallback_reasons": forecast_result.fallback_reasons if 'forecast_result' in locals() else [],
        "provenance": forecast_result.forecast.provenance.to_dict() if 'forecast_result' in locals() and forecast_result.forecast else None,
        "mode": mode,
    }


@router.get("/historical")
async def get_historical(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
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

    data = await run_in_threadpool(
        _get_json,
        ARCHIVE_URL,
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
        except (TypeError, ValueError):
            continue
        if not (-90 <= lat_f <= 90 and -180 <= lon_f <= 180):
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
