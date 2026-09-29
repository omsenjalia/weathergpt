"""Nearest IMD station lookup.

``cityforecastloc`` without an id returns every city-forecast station with its
coordinates; that list (cached 30 min by the client) is the station index.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from weathergpt.imd import client
from weathergpt.imd.parse import haversine_km, iter_dicts, number, station_code, text


@dataclass
class Station:
    code: str
    name: str
    lat: float
    lon: float
    distance_km: float
    row: dict

    def to_dict(self) -> dict:
        return {"code": self.code, "name": self.name, "lat": self.lat, "lon": self.lon,
                "distance_km": round(self.distance_km, 2)}


def city_stations() -> list[dict]:
    return list(iter_dicts(client.fetch("city_forecast_loc").rows))


def nearest_city_station(lat: float, lon: float, rows: Optional[list[dict]] = None) -> Optional[Station]:
    best: Optional[Station] = None
    for row in rows if rows is not None else city_stations():
        s_lat = number(row, "Latitude", "Lat", "lat", low=-90, high=90)
        s_lon = number(row, "Longitude", "Lon", "Long", "lon", low=-180, high=180)
        code = station_code(text(row, "Station_Code", "Station Code", "Station Id", "id"))
        if s_lat is None or s_lon is None or not code:
            continue
        d = haversine_km(lat, lon, s_lat, s_lon)
        if best is None or d < best.distance_km:
            best = Station(code, text(row, "Station_Name", "Station Name", "Station") or code, s_lat, s_lon, d, row)
    return best


def observation_for(station: Station, rows: Optional[list[dict]] = None) -> Optional[dict]:
    """current_wx row for this station: by id (preferred) or by name.

    Asks for the station's own row first; when the id spaces of the forecast and
    observation APIs disagree, falls back to scanning the all-stations list.
    """
    if rows is not None:
        return _match(station, rows)
    try:
        row = _match(station, list(iter_dicts(client.fetch("current_weather", {"id": station.code}).rows)))
    except client.IMDError as exc:
        if exc.reason != "bad_request":  # IMD answers 400 "Invalid ID or No Data" for non-reporting stations
            raise
        row = None
    if row is not None:
        return row
    return _match(station, list(iter_dicts(client.fetch("current_weather").rows)))


def _match(station: Station, rows: list[dict]) -> Optional[dict]:
    name = station.name.strip().lower()
    for row in rows:
        if station_code(text(row, "Station Id", "Station_Id", "StationId", "Station_Code", "id")) == station.code:
            return row
    for row in rows:
        if (text(row, "Station", "Station Name", "Station_Name") or "").strip().lower() == name:
            return row
    return None


def _station_coords() -> dict[str, tuple[float, float, str]]:
    """code -> (lat, lon, name) from the station lists IMD publishes with coordinates."""
    coords: dict[str, tuple[float, float, str]] = {}
    for key in ("city_forecast_mapping", "city_forecast_loc"):
        try:
            rows = client.fetch(key).rows
        except client.IMDError:
            continue
        for row in iter_dicts(rows):
            code = station_code(text(row, "Station_Code", "Station Id"))
            s_lat = number(row, "Latitude", low=-90, high=90)
            s_lon = number(row, "Longitude", low=-180, high=180)
            if code and s_lat is not None and s_lon is not None:
                coords.setdefault(code, (s_lat, s_lon, text(row, "Station_Name") or code))
    return coords


def nearest_observation(lat: float, lon: float, max_km: float) -> Optional[tuple[dict, Station]]:
    """Nearest station that actually reports current_wx, within ``max_km``.

    Only ~440 of IMD's ~1,300 city-forecast stations send synoptic observations, so the
    forecast station and the observing station are often different places.
    """
    coords = _station_coords()
    best: Optional[tuple[dict, Station]] = None
    for row in iter_dicts(client.fetch("current_weather").rows):
        code = station_code(text(row, "Station Id", "Station_Id", "StationId"))
        if not code or code not in coords:
            continue
        s_lat, s_lon, name = coords[code]
        d = haversine_km(lat, lon, s_lat, s_lon)
        if d <= max_km and (best is None or d < best[1].distance_km):
            best = (row, Station(code, text(row, "Station") or name, s_lat, s_lon, d, row))
    return best


def nearest_aws(lat: float, lon: float, max_km: float) -> Optional[tuple[dict, Station]]:
    """Nearest reporting AWS / ARG station (``aws_data``, ~1,100 stations with coordinates).

    Denser than the synoptic network, so it covers many places whose nearest city
    station does not observe.
    """
    best: Optional[tuple[dict, Station]] = None
    for row in iter_dicts(client.fetch("aws_data").rows):
        s_lat = number(row, "Latitude", low=-90, high=90)
        s_lon = number(row, "Longitude", low=-180, high=180)
        if s_lat is None or s_lon is None or number(row, "CURR_TEMP", low=-60, high=60) is None:
            continue
        d = haversine_km(lat, lon, s_lat, s_lon)
        if d <= max_km and (best is None or d < best[1].distance_km):
            name = (text(row, "STATION") or text(row, "ID") or "AWS").replace("_", " ").title()
            best = (row, Station(text(row, "ID") or name, f"{name} (AWS)", s_lat, s_lon, d, row))
    return best
