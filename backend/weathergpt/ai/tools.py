"""LangGraph tools. Each one calls the same service the REST API uses."""

from __future__ import annotations

from typing import Optional

from langchain_core.tools import tool

from weathergpt import geo
from weathergpt.alerts.service import get_alerts
from weathergpt.imd import client as imd_client
from weathergpt.imd import endpoints as imd_endpoints
from weathergpt.weather import archive
from weathergpt.weather.payloads import hour_row, upcoming_hours
from weathergpt.weather.service import InvalidSource, service
from weathergpt.weather.summaries import precip_next_24h, temperature_spread
from weathergpt.weather.supplement import supplement


def _select(lat: float, lon: float, days: int, source: str):
    sel = service().select(lat, lon, requested_source=source, forecast_days=days)
    if sel.forecast is not None:
        supplement(sel.forecast, lat, lon, days)
    return sel


@tool
def geocode_place(name: str) -> dict:
    """Find latitude/longitude for a city, town or district name (India preferred). Call before other tools
    when the user names a place you don't have coordinates for."""
    hit = geo.geocode(name)
    return hit or {"error": f"Place '{name}' not found"}


@tool
def get_weather(latitude: float, longitude: float, days: int = 7, source: str = "auto") -> dict:
    """Current conditions and a daily forecast (up to 15 days). source: auto (IMD -> WeatherNext -> Open-Meteo),
    or pin imd / weathernext / open_meteo. A pinned source is never substituted."""
    try:
        sel = _select(latitude, longitude, max(1, min(int(days), 15)), source)
    except InvalidSource as exc:
        return {"error": str(exc)}
    fc = sel.forecast
    if fc is None:
        return {"status": "unavailable", "requested_source": sel.requested_source, "reasons": sel.fallback_reasons}
    return {
        "source": sel.selected_source, "model": fc.provenance.model, "run_id": fc.provenance.run_id,
        "current_kind": fc.current_kind, "current": fc.current.to_dict() if fc.current else None,
        "daily": [d.to_dict() for d in fc.daily], "air_quality": fc.air_quality,
        "field_sources": {k: v for k, v in fc.field_sources.items() if not k.startswith("_")},
        "timezone": fc.location.get("timezone"), "station": fc.provenance.station,
        "temperature_spread": temperature_spread(fc), "precip_next_24h": precip_next_24h(fc),
        "fallback_reasons": sel.fallback_reasons,
    }


@tool
def get_hourly_forecast(latitude: float, longitude: float, hours: int = 24) -> dict:
    """Hour-by-hour forecast (temperature, rain chance/amount, wind, humidity) for the next N hours (max 72)."""
    sel = _select(latitude, longitude, 4, "auto")
    fc = sel.forecast
    if fc is None:
        return {"status": "unavailable", "reasons": sel.fallback_reasons}
    keep = ("time_utc", "temperature_c", "precipitation_probability", "precipitation_mm", "wind_speed_kmh",
            "humidity_percent", "condition")
    return {"timezone": fc.location.get("timezone"), "utc_offset_seconds": fc.location.get("utc_offset_seconds"),
            "source": fc.field_sources.get("hourly") or sel.selected_source,
            "hours": [{k: hour_row(p)[k] for k in keep} for p in upcoming_hours(fc, max(1, min(int(hours), 72)))]}


@tool
def get_official_alerts(latitude: float, longitude: float) -> dict:
    """Official weather warnings in force for a point in India (IMD district warnings/nowcast + NDMA SACHET).
    status 'unknown' means no channel answered — never report that as 'no alerts'."""
    return get_alerts(latitude, longitude)


@tool
def get_farm_advisory(latitude: float, longitude: float, crop: str = "", days: int = 3) -> dict:
    """Spray / irrigation / field-work suitability by day and hour for a farm location."""
    from weathergpt.farm.advisory import build_windows
    sel = _select(latitude, longitude, max(1, min(int(days), 7)), "auto")
    if sel.forecast is None:
        return {"status": "unavailable", "reasons": sel.fallback_reasons}
    alerts = get_alerts(latitude, longitude).get("alerts", [])
    windows, _ = build_windows(sel.forecast, days, alerts)
    return {"crop": crop or "general crops", "windows": windows, "source": sel.selected_source}


@tool
def get_climate_history(latitude: float, longitude: float, metric: str = "rainfall",
                        start_year: Optional[int] = None, end_year: Optional[int] = None) -> dict:
    """Yearly climate series (ERA5 reanalysis): metric rainfall (annual total mm), temperature or humidity (annual mean)."""
    start, end = archive.default_range(start_year, end_year)
    try:
        return archive.yearly_series(latitude, longitude, metric, start, end)
    except Exception as exc:
        return {"error": str(exc)}


@tool
def get_imd_product(endpoint: str, id: Optional[str] = None, latitude: Optional[float] = None,
                    longitude: Optional[float] = None) -> dict:
    """Raw official IMD product. endpoint is one of: city_forecast, current_weather, district_warning,
    district_nowcast, station_nowcast, district_rainfall, state_rainfall, basin_qpf, subdivision_warning,
    subdivision_rainfall_forecast, state_district_rainfall_forecast, port_warning, sea_bulletin,
    coastal_bulletin, fishermen_warning, cyclone_track, cyclone_wind, cyclone_cone, sun_moon, aws_data,
    agromet, highway_nowcast, highway_warning, radar, lightning, mausamgram, all_india_bulletin."""
    if imd_endpoints.get(endpoint) is None:
        return {"error": f"unknown endpoint; choose from {[e.key for e in imd_endpoints.ENDPOINTS]}"}
    params = {"id": id}
    if latitude is not None and longitude is not None:
        params.update(lat=latitude, lon=longitude)
    try:
        resp = imd_client.fetch(endpoint, params)
    except imd_client.IMDError as exc:
        return {"error": exc.reason, "message": str(exc)}
    out = resp.to_dict()
    out["data"] = out["data"][:25]
    out["truncated"] = resp.rows[25:] != []
    return out


TOOLS = [geocode_place, get_weather, get_hourly_forecast, get_official_alerts, get_farm_advisory,
         get_climate_history, get_imd_product]
