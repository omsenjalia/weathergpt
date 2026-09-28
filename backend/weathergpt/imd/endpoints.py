"""Registry of every API published by the IMD gateway (https://api.imd.gov.in).

Source: the public reference https://api.imd.gov.in/public/api_reference.html
(28 APIs). Twenty have documented paths under ``/api/v1``. Eight appear only in
the index (the detailed docs sit behind the portal login), so their paths here
are provisional: ``verified=False``, and each can be corrected without a code
change via ``IMD_ENDPOINT_<KEY>`` (e.g. ``IMD_ENDPOINT_AGROMET=agromet_advisory``).
``GET /dev/imd/probe`` calls every endpoint and reports which paths answer.

The gateway authenticates *before* routing (any unknown path also returns
401 "API key missing"), so provisional paths cannot be discovered without keys.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Param:
    name: str
    description: str
    example: Optional[str] = None
    required: bool = False


@dataclass(frozen=True)
class Endpoint:
    key: str
    title: str
    group: str
    path: str
    description: str
    params: tuple[Param, ...] = ()
    verified: bool = True
    cache_seconds: int = 600
    # A cheap parameter set used by the probe (keeps responses small).
    probe_params: dict = field(default_factory=dict)
    fields: tuple[str, ...] = ()

    def resolved_path(self) -> str:
        override = (os.getenv(f"IMD_ENDPOINT_{self.key.upper()}") or "").strip().strip("/")
        return override or self.path

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "title": self.title,
            "group": self.group,
            "path": f"/api/v1/{self.resolved_path()}",
            "path_verified": self.verified or bool(os.getenv(f"IMD_ENDPOINT_{self.key.upper()}")),
            "override_env": f"IMD_ENDPOINT_{self.key.upper()}",
            "description": self.description,
            "params": [{"name": p.name, "description": p.description, "example": p.example, "required": p.required}
                       for p in self.params],
            "fields": list(self.fields),
            "proxy": f"/v2/imd/{self.key}",
        }


_ID = lambda desc, ex: (Param("id", desc, ex),)  # noqa: E731

ENDPOINTS: tuple[Endpoint, ...] = (
    # --- Weather forecast -------------------------------------------------
    Endpoint("city_forecast", "City Weather Forecast (7 days)", "forecast", "cityforecast",
             "Observed max/min, rainfall, humidity, sun/moon times and a 7-day max/min/text forecast per city station.",
             _ID("City station code (omit for all stations)", "42182"), cache_seconds=1800,
             probe_params={"id": "42182"},
             fields=("Date", "Station_Code", "Station_Name", "Today_Max_temp", "Today_Min_temp", "Past_24_hrs_Rainfall",
                     "Relative_Humidity_at_0830", "Relative_Humidity_at_1730", "Sunrise_time", "Sunset_time",
                     "Todays_Forecast_Max_Temp", "Todays_Forecast_Min_temp", "Todays_Forecast", "Day_2..7_*")),
    Endpoint("city_forecast_loc", "City Weather Forecast with Latitude & Longitude", "forecast", "cityforecastloc",
             "Same as city_forecast plus station Latitude/Longitude; used to find the nearest IMD station.",
             _ID("City station code (omit for all stations)", "42182"), cache_seconds=1800,
             probe_params={"id": "42182"}, fields=("...city_forecast fields", "Latitude", "Longitude")),
    Endpoint("city_forecast_mapping", "City Forecast Mapping", "forecast", "cityforecast_mapping",
             "Station code/name mapping for the city forecast APIs.", cache_seconds=86400),
    Endpoint("subdivision_rainfall_forecast", "Subdivision Rainfall Forecast (7 days)", "forecast",
             "subdivision_rainfall_forecast",
             "Rainfall distribution (e.g. Widespread, 76-100% stations) per meteorological subdivision for 7 days.",
             cache_seconds=3600,
             fields=("date_obs", "SUBDIV", "dayN_color", "dayN_distribution", "dayN_distribution_percentage")),
    Endpoint("state_district_rainfall_forecast", "State/District Rainfall Forecast (5 days)", "forecast",
             "state_district_rainfall_forecast", "Rainfall distribution per district for 5 days.", cache_seconds=3600,
             fields=("date_obs", "Obj_id", "District", "State", "dayN_color", "dayN_distribution",
                     "dayN_distribution_percentage")),
    Endpoint("all_india_bulletin", "All India Weather Forecast Bulletin", "forecast", "allindia_bulletin",
             "National forecast bulletin text.", verified=False, cache_seconds=3600),
    Endpoint("mausamgram", "Weather at your location (Mausamgram)", "forecast", "mausamgram",
             "Point (lat/lon) forecast from IMD's Mausamgram service.",
             (Param("lat", "Latitude", "28.61", True), Param("lon", "Longitude", "77.21", True)),
             verified=False, probe_params={"lat": "28.61", "lon": "77.21"}),
    # --- Current weather & nowcast -----------------------------------------
    Endpoint("current_weather", "Current Weather", "current", "current_wx",
             "Latest surface observation per station: temperature, MSLP, wind, humidity, present-weather code, nebulosity.",
             _ID("Station ID (omit for all stations)", "42182"), cache_seconds=600, probe_params={"id": "42182"},
             fields=("Station Id", "Station", "Date of Observation", "Time of Observation", "M.S.L.P", "Wind Direction",
                     "Wind Speed", "Temperature", "Weather Code", "Nebulosity", "Humidity", "Last 24 hrs Rainfall")),
    Endpoint("district_nowcast", "District-wise Nowcast", "current", "districtnowcast",
             "Next-3-hour nowcast categories (thunderstorm, rain, dust storm, lightning) with colour 1 green .. 4 red.",
             _ID("District object ID", "1"), cache_seconds=300, probe_params={"id": "1"},
             fields=("Station", "Date", "Cat1..Cat19", "message", "toi", "Vupto", "color")),
    Endpoint("station_nowcast", "Station-wise Nowcast", "current", "stationnowcast",
             "Nowcast categories per station name.", _ID("Station name", "Adilabad"), cache_seconds=300,
             probe_params={"id": "Adilabad"}),
    Endpoint("aws_data", "AWS/ARG Data", "current", "aws_data",
             "Automatic Weather Station / Rain Gauge readings with coordinates.",
             (Param("id", "Station call sign", "NDL"), Param("sid", "State ID 1-36", "7")),
             cache_seconds=600, probe_params={"id": "NDL"},
             fields=("CALL_SIGN", "DISTRICT", "STATE", "STATION", "DATE", "TIME", "CURR_TEMP", "DEW_POINT_TEMP", "RH",
                     "WIND_DIRECTION", "WIND_SPEED", "MSLP", "MIN_TEMP", "MAX_TEMP", "Latitude", "Longitude")),
    Endpoint("aws_data_mapping", "AWS Mapping", "current", "aws_data_mapping",
             "AWS/ARG station metadata mapping.", cache_seconds=86400),
    # --- Warnings -------------------------------------------------------------
    Endpoint("district_warning", "District-wise Warnings (5 days)", "warnings", "districtwarning",
             "Official warning codes per district for 5 days. NOTE: colour 1 = red .. 4 = green (reverse of nowcast).",
             _ID("District object ID", "573"), cache_seconds=900, probe_params={"id": "573"},
             fields=("Obj_id", "Date", "UTC", "District", "Day_1..Day_5", "Day1_Color..Day5_Color")),
    Endpoint("subdivision_warning", "Subdivision-wise Warnings (5 days)", "warnings", "subdivisionwarning",
             "Warning text and hex colour per meteorological subdivision for 5 days.", cache_seconds=900,
             fields=("date_obs", "SUBDIV", "dayN_color", "dayN_warning")),
    # --- Rainfall -----------------------------------------------------------------
    Endpoint("district_rainfall", "District-wise Rainfall", "rainfall", "districtrainfall",
             "Daily/weekly/monthly/cumulative actual vs normal rainfall per district.",
             _ID("District object ID", "164"), cache_seconds=3600, probe_params={"id": "164"}),
    Endpoint("state_rainfall", "State-wise Rainfall", "rainfall", "staterainfall",
             "Daily/weekly/monthly/cumulative actual vs normal rainfall per state.",
             _ID("State name", "jammu"), cache_seconds=3600, probe_params={"id": "jammu"}),
    Endpoint("basin_qpf", "River Basin QPF", "rainfall", "basinqpf",
             "Quantitative precipitation forecast per river sub-basin for 5 days.",
             _ID("Basin ID", "100"), cache_seconds=3600, probe_params={"id": "100"}),
    # --- Marine ---------------------------------------------------------------------
    Endpoint("port_warning", "Port Warning", "marine", "portwarning", "Port signals issued by CWC/ACWC.",
             _ID("Port ID", None), cache_seconds=900),
    Endpoint("sea_bulletin", "Sea Area Bulletin", "marine", "seabulletin", "Sea area forecast bulletin.",
             _ID("Area ID", "108"), cache_seconds=1800, probe_params={"id": "108"}),
    Endpoint("coastal_bulletin", "Coastal Bulletin", "marine", "coastalbulletin", "Coastal area forecast bulletin.",
             cache_seconds=1800),
    Endpoint("fishermen_warning", "Fishermen Warning", "marine", "fishermen_warning",
             "Warnings for fishermen.", verified=False, cache_seconds=900),
    # --- Cyclone ------------------------------------------------------------------------
    Endpoint("cyclone_track", "Cyclone Track", "cyclone", "cyclone_track",
             "Observed and forecast track of the active cyclone.", cache_seconds=600),
    Endpoint("cyclone_wind", "Cyclone Wind Warning", "cyclone", "cyclone_wind",
             "27/34/50/64 kt wind radii as GeoJSON MultiPolygons.", cache_seconds=600),
    Endpoint("cyclone_cone", "Cyclone Cone of Uncertainty", "cyclone", "cyclone_cou",
             "Track cone of uncertainty as a GeoJSON MultiPolygon.", cache_seconds=600),
    # --- Astronomy --------------------------------------------------------------------------
    Endpoint("sun_moon", "Sun & Moon Rise/Set", "astronomy", "sunmoon",
             "Sunrise, sunset, moonrise and moonset (IST) for a point.",
             (Param("lat", "Latitude", "26.9124", True), Param("lon", "Longitude", "75.7873", True)),
             cache_seconds=21600, probe_params={"lat": "26.9124", "lon": "75.7873"}),
    # --- NHAI ---------------------------------------------------------------------------------
    Endpoint("highway_nowcast", "Highway Nowcast Warning", "highway", "highway_nowcast",
             "Nowcast warnings along national highways.", verified=False, cache_seconds=300),
    Endpoint("highway_warning", "Highway Warning (5 days)", "highway", "highway_warning",
             "5-day warnings along national highways.", verified=False, cache_seconds=900),
    # --- Radar & lightning ------------------------------------------------------------------
    Endpoint("radar", "Radar Image", "radar", "radar", "Doppler weather radar products.", verified=False,
             cache_seconds=300),
    Endpoint("lightning", "Lightning Data", "radar", "lightning", "Lightning strike data.", verified=False,
             cache_seconds=300),
    # --- Agromet ---------------------------------------------------------------------------------
    Endpoint("agromet", "Agromet Advisory", "agromet", "agromet",
             "District agro-meteorological advisory for farmers.", verified=False, cache_seconds=3600),
)

BY_KEY: dict[str, Endpoint] = {e.key: e for e in ENDPOINTS}


def get(key: str) -> Optional[Endpoint]:
    return BY_KEY.get(key)


def catalog() -> list[dict]:
    return [e.to_dict() for e in ENDPOINTS]
