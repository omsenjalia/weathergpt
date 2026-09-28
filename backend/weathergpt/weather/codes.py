"""Weather codes.

Clients speak the WMO *interpretation* codes Open-Meteo uses (0-3 sky, 45/48 fog,
51-67 drizzle/rain, 71-77 snow, 80-86 showers, 95-99 thunder). IMD station
observations use WMO table 4677 "present weather" (ww 00-99) — a different code
space — and IMD forecasts are free text. Both are translated here.
"""

from __future__ import annotations

import re
from typing import Optional

WMO_CONDITIONS: dict[int, str] = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    56: "Light freezing drizzle", 57: "Dense freezing drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    66: "Light freezing rain", 67: "Heavy freezing rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
}

THUNDER_CODES = frozenset({95, 96, 99})


def wmo_condition(code: Optional[int]) -> Optional[str]:
    if code is None:
        return None
    return WMO_CONDITIONS.get(int(code))


def sky_code_from_okta(okta: Optional[float]) -> Optional[int]:
    """Nebulosity (0-8 oktas) -> WMO sky code."""
    if okta is None or okta < 0 or okta > 9:
        return None
    if okta == 9:  # sky obscured
        return 3
    if okta <= 0:
        return 0
    if okta <= 2:
        return 1
    if okta <= 5:
        return 2
    return 3


# IMD present-weather (ww) -> (WMO interpretation code or None, short label).
# None means the ww code describes sky evolution / distant phenomena; the sky
# class then comes from nebulosity.
_WW: dict[int, tuple[Optional[int], str]] = {}


def _ww(codes, code, label):
    for c in codes:
        _WW[c] = (code, label)


_ww(range(0, 4), None, "")
_ww([4], 45, "Smoke")
_ww([5], 45, "Haze")
_ww([6, 7, 8], 45, "Dust haze")
_ww([9], 45, "Duststorm in sight")
_ww([10], 45, "Mist")
_ww([11, 12], 45, "Shallow fog")
_ww([13], 95, "Lightning")
_ww([14, 15, 16], None, "Rain nearby")
_ww([17], 95, "Thunderstorm")
_ww([18], 95, "Squall")
_ww([19], 95, "Funnel cloud")
_ww([20], 51, "Recent drizzle")
_ww([21], 61, "Recent rain")
_ww([22], 71, "Recent snow")
_ww([23], 66, "Recent sleet")
_ww([24], 56, "Recent freezing rain")
_ww([25], 80, "Recent rain showers")
_ww([26], 85, "Recent snow showers")
_ww([27], 96, "Recent hail")
_ww([28], 45, "Recent fog")
_ww([29], 95, "Recent thunderstorm")
_ww(range(30, 36), 45, "Duststorm")
_ww(range(36, 40), 71, "Blowing snow")
_ww(range(40, 48), 45, "Fog")
_ww([48, 49], 48, "Rime fog")
_ww([50, 51], 51, "Light drizzle")
_ww([52, 53], 53, "Moderate drizzle")
_ww([54, 55], 55, "Dense drizzle")
_ww([56], 56, "Freezing drizzle")
_ww([57], 57, "Freezing drizzle")
_ww([58], 61, "Drizzle and rain")
_ww([59], 63, "Drizzle and rain")
_ww([60, 61], 61, "Slight rain")
_ww([62, 63], 63, "Moderate rain")
_ww([64, 65], 65, "Heavy rain")
_ww([66], 66, "Freezing rain")
_ww([67], 67, "Heavy freezing rain")
_ww([68], 71, "Rain and snow")
_ww([69], 73, "Rain and snow")
_ww([70, 71], 71, "Slight snow")
_ww([72, 73], 73, "Moderate snow")
_ww([74, 75], 75, "Heavy snow")
_ww(range(76, 80), 77, "Ice crystals")
_ww([80], 80, "Slight rain showers")
_ww([81], 81, "Rain showers")
_ww([82], 82, "Violent rain showers")
_ww([83], 85, "Sleet showers")
_ww([84], 86, "Sleet showers")
_ww([85], 85, "Snow showers")
_ww([86], 86, "Heavy snow showers")
_ww([87, 88], 77, "Snow pellets")
_ww([89, 90], 82, "Hail showers")
_ww([91], 61, "Rain after thunderstorm")
_ww([92], 63, "Rain after thunderstorm")
_ww([93, 94], 71, "Snow after thunderstorm")
_ww([95], 95, "Thunderstorm")
_ww([96], 96, "Thunderstorm with hail")
_ww([97], 95, "Heavy thunderstorm")
_ww([98], 95, "Thunderstorm with duststorm")
_ww([99], 99, "Heavy thunderstorm with hail")


def from_imd_present_weather(ww: Optional[int], okta: Optional[float]) -> tuple[Optional[int], Optional[str]]:
    """IMD observation (ww, nebulosity) -> (WMO interpretation code, condition)."""
    sky = sky_code_from_okta(okta)
    if ww is None or ww not in _WW:
        return sky, wmo_condition(sky)
    code, label = _WW[ww]
    if code is None:
        base = wmo_condition(sky)
        if label and base:
            return sky, f"{base}, {label.lower()}"
        return sky, label or base
    return code, label


# Ordered: first match wins, so severe phrases precede milder ones.
_TEXT_RULES: list[tuple[re.Pattern, int, str]] = [(re.compile(p, re.I), c, l) for p, c, l in [
    (r"thunder.*hail|hail.*thunder", 96, "Thunderstorm with hail"),
    (r"thunder|lightning|squall", 95, "Thunderstorm"),
    (r"(very|extremely) heavy rain", 65, "Very heavy rain"),
    (r"heavy rain", 65, "Heavy rain"),
    (r"snow", 71, "Snow"),
    (r"drizzle", 51, "Drizzle"),
    (r"shower", 80, "Rain showers"),
    (r"rain", 61, "Rain"),
    (r"dense fog|fog", 45, "Fog"),
    (r"mist|haze|smog|dust", 45, "Haze"),
    (r"partly cloudy", 2, "Partly cloudy"),
    (r"overcast|generally cloudy|cloudy sky", 3, "Cloudy"),
    (r"mainly clear", 1, "Mainly clear"),
    (r"clear sky|clear", 0, "Clear sky"),
]]

# Phrases that describe a *chance*, not an expected condition: "partly cloudy sky
# with possibility of rain" shows cloud, and the chance is left to rain_probability.
_POSSIBILITY = re.compile(r"(possibility|chance|likely)\s+of\s+(.*)", re.I)


def from_imd_forecast_text(text: Optional[str]) -> tuple[Optional[int], Optional[str]]:
    """IMD free-text daily forecast -> (WMO interpretation code, short condition)."""
    if not text or not str(text).strip() or str(text).strip().upper() in {"NA", "N/A", "--", "NIL"}:
        return None, None
    body = str(text)
    m = _POSSIBILITY.search(body)
    lead = body[: m.start()] if m else body
    for scope in ((lead, body) if lead.strip() else (body,)):
        for pattern, code, label in _TEXT_RULES:
            if pattern.search(scope):
                return code, label
    return None, body.strip()[:60]
