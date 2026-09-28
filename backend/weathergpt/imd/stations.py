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
    row = _match(station, list(iter_dicts(client.fetch("current_weather", {"id": station.code}).rows)))
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
