"""Live evidence for a chat/voice turn and everything derived from it.

One fetch (forecast selection + supplement + official alerts) feeds:
- ``card(...)``     the structured card the mobile apps render (real numbers only)
- ``reply(...)``    the deterministic markdown answer (fast path / LLM fallback)
- ``facts(...)``    a compact fact sheet handed to the LLM so it cites real data
"""

from __future__ import annotations

import concurrent.futures
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from weathergpt.alerts.service import get_alerts
from weathergpt.weather.models import Forecast
from weathergpt.weather.service import Selection, service
from weathergpt.weather.supplement import supplement

SOURCE_LABEL = {"imd": "IMD", "weathernext": "Google WeatherNext", "open_meteo": "Open-Meteo"}
_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=8, thread_name_prefix="evidence")


@dataclass
class Evidence:
    place: str
    lat: float
    lon: float
    selection: Selection
    alerts: Optional[dict] = None
    notes: list = field(default_factory=list)

    @property
    def forecast(self) -> Optional[Forecast]:
        return self.selection.forecast


def gather(place: str, lat: float, lon: float, *, requested_source: str = "auto", days: int = 7,
           with_alerts: bool = True, alerts_timeout: float = 6.0) -> Evidence:
    alerts_future = _POOL.submit(get_alerts, lat, lon, timeout=alerts_timeout) if with_alerts else None
    sel = service().select(lat, lon, requested_source=requested_source, forecast_days=days)
    if sel.forecast is not None:
        supplement(sel.forecast, lat, lon, days)
    alerts = None
    if alerts_future is not None:
        try:
            alerts = alerts_future.result(timeout=alerts_timeout + 1)
        except Exception:
            alerts = {"status": "unknown", "alerts": []}
    return Evidence(place, lat, lon, sel, alerts)


# --------------------------------------------------------------------------- helpers


def _fmt(v: Optional[float], unit: str = "", digits: int = 0) -> Optional[str]:
    if v is None:
        return None
    return f"{v:.{digits}f}{unit}"


def _local(fc: Forecast, dt: datetime) -> datetime:
    return dt + timedelta(seconds=fc.utc_offset_seconds or 0)


def _hour(dt: datetime) -> str:
    return f"{dt.hour % 12 or 12} {'AM' if dt.hour < 12 else 'PM'}"


def _day_name(fc: Forecast, date: str, index: int) -> str:
    if index == 0:
        return "Today"
    if index == 1:
        return "Tomorrow"
    try:
        return datetime.fromisoformat(date).strftime("%a")
    except ValueError:
        return date


def _source_line(ev: Evidence) -> str:
    fc = ev.forecast
    if fc is None:
        return ""
    prov = fc.provenance
    parts = [SOURCE_LABEL.get(prov.source, prov.source)]
    if prov.source == "imd" and prov.station:
        parts[0] = f"IMD {prov.station.get('name')} station"
        if fc.current_kind == "observation" and fc.current:
            parts.append(f"observed {_local(fc, fc.current.time_utc):%H:%M} local")
    if prov.run_id:
        parts.append(f"run {prov.run_id}")
    extra = sorted({v for k, v in fc.field_sources.items() if isinstance(v, str) and not k.startswith("_")
                    and v != prov.source})
    if extra:
        parts.append("gaps filled from " + ", ".join(SOURCE_LABEL.get(x, x) for x in extra))
    return "Source: " + " · ".join(parts)


def _next_rain(fc: Forecast, hours: int = 24) -> tuple[Optional[float], Optional[datetime], Optional[float]]:
    """(max chance next N h, first hour >= 50%, total mm next N h)."""
    now = datetime.now(timezone.utc)
    window = [p for p in fc.hourly if p.time_utc + timedelta(hours=1) > now and p.time_utc < now + timedelta(hours=hours)]
    chances = [p.precipitation_probability for p in window if p.precipitation_probability is not None]
    first = next((p.time_utc for p in window if (p.precipitation_probability or 0) >= 50), None)
    amounts = [p.precipitation_mm for p in window if p.precipitation_mm is not None]
    return (max(chances) if chances else None), first, (round(sum(amounts), 1) if amounts else None)


def _tone_rain(chance: Optional[float]) -> str:
    if chance is None:
        return "neutral"
    return "avoid" if chance >= 70 else "caution" if chance >= 40 else "good"


def _tone_aqi(aqi: Optional[float]) -> str:
    if aqi is None:
        return "neutral"
    return "avoid" if aqi > 80 else "caution" if aqi > 40 else "good"


def _tone_heat(t: Optional[float]) -> str:
    if t is None:
        return "neutral"
    return "avoid" if t >= 40 else "caution" if t >= 35 else "good"


# --------------------------------------------------------------------------- card


def card(ev: Evidence, intent: str) -> Optional[dict]:
    """Structured card for the mobile result screen. None when there is no data to show."""
    fc = ev.forecast
    if fc is None:
        return None
    cur = fc.current
    stats: list[dict] = []

    def stat(label: str, value: Optional[str], tone: str = "neutral") -> None:
        if value is not None:
            stats.append({"label": label, "value": value, "tone": tone})

    chance, first_wet, total = _next_rain(fc)
    alerts = (ev.alerts or {}).get("alerts") or []
    top = alerts[0] if alerts else None

    if intent == "rain_probability":
        label = "Rain Forecast"
        stat("Chance of rain (24 h)", _fmt(chance, "%"), _tone_rain(chance))
        stat("Expected rain (24 h)", _fmt(total, " mm", 1))
        if first_wet is not None:
            stat("Likely from", _hour(_local(fc, first_wet)), "caution")
        verdict = ("Rain likely — carry an umbrella" if (chance or 0) >= 60 else
                   "Showers possible" if (chance or 0) >= 30 else "Mostly dry" if chance is not None else None)
    elif intent == "air_quality":
        aqi = (fc.air_quality or {}).get("european_aqi")
        label = "Air Quality"
        stat("European AQI", _fmt(aqi), _tone_aqi(aqi))
        stat("PM2.5", _fmt((fc.air_quality or {}).get("pm2_5"), " µg/m³"))
        verdict = (None if aqi is None else "Air quality is poor — limit outdoor exertion" if aqi > 80 else
                   "Moderate — sensitive groups take care" if aqi > 40 else "Air quality is good")
    elif intent == "weather_alerts":
        label = "Official Warnings"
        verdict = (f"{top['severity'].title()} warning: {top.get('event')}" if top else
                   "No active official warnings" if (ev.alerts or {}).get("status") == "ok" else
                   "Warning status unavailable right now")
        for a in alerts[:3]:
            stat(a.get("date") or "Now", a.get("event") or a.get("headline"),
                 "avoid" if a["severity"] == "red" else "caution")
    else:
        label = "Current Weather"
        stat("Temperature", _fmt(cur.temperature_c if cur else None, "°C"), _tone_heat(cur.temperature_c if cur else None))
        stat("Feels like", _fmt(cur.feels_like_c if cur else None, "°C"))
        stat("Chance of rain", _fmt(chance, "%"), _tone_rain(chance))
        stat("Humidity", _fmt(cur.humidity_percent if cur else None, "%"))
        stat("Wind", _fmt(cur.wind_speed_kmh if cur else None, " km/h"))
        verdict = cur.condition if cur and cur.condition else None

    forecast_rows = [{
        "day": _day_name(fc, d.date, i),
        "date": d.date,
        "temperature": f"{_fmt(d.high_c, '°') or '—'} / {_fmt(d.low_c, '°') or '—'}",
        "rainfall": _fmt(d.precipitation_mm, " mm", 1),
        "rain_chance": _fmt(d.rain_probability, "%"),
        "condition": d.condition,
    } for i, d in enumerate(fc.daily[:5])]

    explanation = _source_line(ev)
    if top and intent != "weather_alerts":
        explanation = f"⚠ {top['severity'].title()} warning: {top.get('event') or top.get('headline')}. " + explanation
    return {
        "label": label,
        "verdict": verdict,
        "explanation": explanation,
        "cta_label": "See full forecast",
        "source": fc.provenance.source,
        "run_id": fc.provenance.run_id,
        "place": ev.place,
        "stats": stats,
        "forecast": forecast_rows,
        "alerts": [{k: a.get(k) for k in ("severity", "event", "headline", "date", "source")} for a in alerts[:3]],
    }


# --------------------------------------------------------------------------- deterministic reply


def reply(ev: Evidence, intent: str) -> str:
    fc = ev.forecast
    if fc is None:
        return unavailable_reply(ev)
    cur = fc.current
    lines: list[str] = [f"## Weather for {ev.place}", ""]
    alerts = (ev.alerts or {}).get("alerts") or []
    for a in alerts[:3]:
        icon = "🔴" if a["severity"] == "red" else "🟠" if a["severity"] == "orange" else "🟡"
        when = f" ({a['date']})" if a.get("date") else ""
        lines.append(f"{icon} **{a['severity'].title()} warning{when}:** {a.get('headline') or a.get('event')}")
    if alerts:
        lines.append("")

    chance, first_wet, total = _next_rain(fc)
    if intent == "rain_probability":
        if chance is None:
            lines.append("Rain chances aren't available for the next 24 hours.")
        else:
            lead = ("**Rain is likely**" if chance >= 60 else "**Showers are possible**" if chance >= 30
                    else "**Mostly dry**")
            detail = f" — up to **{chance:.0f}%** chance in the next 24 hours"
            if first_wet is not None:
                detail += f", most likely from around **{_hour(_local(fc, first_wet))}**"
            if total is not None:
                detail += f", about **{total} mm** in total"
            lines.append(lead + detail + ".")
        lines.append("")

    if cur is not None:
        bits = []
        if cur.temperature_c is not None:
            feels = f" (feels like {cur.feels_like_c:.0f}°C)" if cur.feels_like_c is not None else ""
            bits.append(f"**{cur.temperature_c:.0f}°C**{feels}")
        if cur.condition:
            bits.append(cur.condition.lower())
        head = "Right now" if fc.current_kind == "observation" else "Now"
        if bits:
            lines.append(f"{head}: " + ", ".join(bits) + ".")
        details = [f"- **Humidity:** {cur.humidity_percent:.0f}%" if cur.humidity_percent is not None else None,
                   f"- **Wind:** {cur.wind_speed_kmh:.0f} km/h" if cur.wind_speed_kmh is not None else None,
                   f"- **Chance of rain (24 h):** {chance:.0f}%" if chance is not None and intent != "rain_probability" else None,
                   f"- **Air quality (EAQI):** {fc.air_quality['european_aqi']:.0f}" if (fc.air_quality or {}).get("european_aqi") is not None else None]
        details = [d for d in details if d]
        if details:
            lines.extend(details)
        lines.append("")

    if fc.daily:
        lines.append("**Coming days**")
        for i, d in enumerate(fc.daily[:3]):
            hi, lo = _fmt(d.high_c, "°"), _fmt(d.low_c, "°")
            rain = f", rain {d.rain_probability:.0f}%" if d.rain_probability is not None else ""
            lines.append(f"- {_day_name(fc, d.date, i)}: {d.condition or '—'}, {hi or '—'} / {lo or '—'}{rain}")
        lines.append("")

    lines.append(f"_{_source_line(ev)}_")
    lines.append("")
    lines.append(widgets(ev))
    return "\n".join(lines).strip()


def widgets(ev: Evidence) -> str:
    """Web-app widget blocks (the mobile apps drop these and render ``card``)."""
    fc = ev.forecast
    if fc is None:
        return ""
    cur = fc.current
    weather = {"city": ev.place, "temp": cur.temperature_c if cur else None,
               "feelsLike": cur.feels_like_c if cur else None, "condition": cur.condition if cur else None,
               "humidity": cur.humidity_percent if cur else None, "windSpeed": cur.wind_speed_kmh if cur else None,
               "source": fc.provenance.source}
    forecast = {"city": ev.place, "days": [{"day": _day_name(fc, d.date, i), "temp": d.high_c, "low": d.low_c,
                                            "condition": d.condition, "rainProb": d.rain_probability}
                                           for i, d in enumerate(fc.daily[:5])]}
    return (f"```widget:weather\n{json.dumps(weather, ensure_ascii=False)}\n```\n\n"
            f"```widget:forecast\n{json.dumps(forecast, ensure_ascii=False)}\n```")


def unavailable_reply(ev: Evidence) -> str:
    sel = ev.selection
    reasons = "; ".join(f"{SOURCE_LABEL.get(r['provider'], r['provider'])}: {r.get('reason')}" for r in sel.fallback_reasons)
    if sel.requested_source != "auto":
        return (f"I'm having trouble reaching **{SOURCE_LABEL.get(sel.requested_source, sel.requested_source)}** for "
                f"{ev.place} right now, and you asked for that source specifically, so I won't substitute another one. "
                f"({reasons or 'no details'})")
    return (f"I'm having trouble reaching weather services for **{ev.place}** right now. Please try again in a moment."
            + (f" ({reasons})" if reasons else ""))


# --------------------------------------------------------------------------- LLM fact sheet


def facts(ev: Evidence) -> str:
    """Compact, provenance-labelled facts for the LLM prompt."""
    fc = ev.forecast
    if fc is None:
        return f"Live data for {ev.place}: UNAVAILABLE ({ev.selection.error})."
    cur = fc.current
    out = [f"LIVE DATA for {ev.place} ({ev.lat:.3f}, {ev.lon:.3f}); local timezone {fc.location.get('timezone')}.",
           _source_line(ev) + "."]
    if cur:
        kind = "IMD station observation" if fc.current_kind == "observation" else "model estimate"
        out.append(f"Now ({kind}): temp {_fmt(cur.temperature_c, 'C', 1)}, feels {_fmt(cur.feels_like_c, 'C', 1)}, "
                   f"{cur.condition}, humidity {_fmt(cur.humidity_percent, '%')}, wind {_fmt(cur.wind_speed_kmh, ' km/h')}, "
                   f"UV {_fmt(cur.uv_index, '', 1)}.")
    chance, first_wet, total = _next_rain(fc)
    out.append(f"Next 24 h: max rain chance {_fmt(chance, '%')}, total {_fmt(total, ' mm', 1)}"
               + (f", first likely wet hour {_local(fc, first_wet):%H:00} local" if first_wet else "") + ".")
    for i, d in enumerate(fc.daily[:7]):
        text = f" IMD says: '{d.forecast_text}'." if d.forecast_text else ""
        out.append(f"{d.date} ({_day_name(fc, d.date, i)}): {d.condition}, high {_fmt(d.high_c, 'C')}, "
                   f"low {_fmt(d.low_c, 'C')}, rain chance {_fmt(d.rain_probability, '%')}, "
                   f"rain {_fmt(d.precipitation_mm, ' mm', 1)}, max wind {_fmt(d.wind_kmh_max, ' km/h')}.{text}")
    if fc.air_quality:
        out.append(f"Air quality: European AQI {_fmt(fc.air_quality.get('european_aqi'))}, "
                   f"PM2.5 {_fmt(fc.air_quality.get('pm2_5'), ' ug/m3')}.")
    a = ev.alerts or {}
    if a.get("alerts"):
        out.append("OFFICIAL WARNINGS: " + " | ".join(f"{x['severity'].upper()} {x.get('date') or 'now'}: "
                                                     f"{x.get('headline') or x.get('event')}" for x in a["alerts"][:5]))
    elif a.get("status") == "ok":
        out.append("Official warnings: none active for this location.")
    else:
        out.append("Official warnings: status unknown (do not claim there are none).")
    return "\n".join(o for o in out if o)
