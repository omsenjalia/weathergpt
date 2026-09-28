"""Official warnings for a point, from every channel that can answer.

``status`` is ``ok`` when at least one official channel answered, otherwise
``unknown`` — an unreachable feed never becomes "no alerts".
"""

from __future__ import annotations

import concurrent.futures
from datetime import datetime, timezone

from weathergpt import geo, http
from weathergpt.imd import client as imd_client
from weathergpt.alerts import imd_district, sachet
from weathergpt.config import settings
from weathergpt.weather.providers.imd import in_india

RANK = {"red": 3, "orange": 2, "yellow": 1, "info": 0, "green": 0}
# Shared pool: a request never blocks on a slow channel past its timeout.
_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=8, thread_name_prefix="alerts")


def _imd(lat: float, lon: float) -> dict:
    if not settings().imd.configured:
        return {"status": "not_configured", "alerts": []}
    place = geo.reverse(lat, lon)
    if not place or not place.get("district"):
        return {"status": "unknown", "reason": "district_unresolved", "alerts": []}
    try:
        alerts, district = imd_district.alerts_for_district(place["district"])
    except imd_client.IMDError as exc:
        return {"status": "error", "reason": exc.reason, "message": str(exc), "alerts": []}
    if district is None:
        return {"status": "unknown", "reason": "district_not_in_imd_list", "district_query": place["district"],
                "alerts": []}
    return {"status": "ok", "district": {**district, "state": place.get("state")}, "alerts": alerts}


def _sachet(lat: float, lon: float) -> dict:
    try:
        return {"status": "ok", "alerts": sachet.alerts_for(lat, lon)}
    except http.UpstreamError as exc:
        return {"status": "error", "reason": exc.reason, "alerts": []}
    except Exception as exc:
        return {"status": "error", "reason": f"exception_{type(exc).__name__}", "alerts": []}


def get_alerts(lat: float, lon: float, *, timeout: float = 9.0) -> dict:
    fetched = datetime.now(timezone.utc).isoformat()
    if not settings().alerts_enabled:
        return {"status": "disabled", "alerts": [], "sources": {}, "fetched_at": fetched}
    if not in_india(lat, lon):
        return {"status": "not_covered", "message": "Official warnings are available for locations in India",
                "alerts": [], "sources": {}, "fetched_at": fetched}
    results: dict[str, dict] = {}
    futures = {_POOL.submit(_imd, lat, lon): "imd", _POOL.submit(_sachet, lat, lon): "ndma_sachet"}
    try:
        for fut in concurrent.futures.as_completed(futures, timeout=timeout):
            results[futures[fut]] = fut.result()
    except concurrent.futures.TimeoutError:
        pass  # stragglers finish in the background and warm the caches
    for name in futures.values():
        results.setdefault(name, {"status": "error", "reason": "timeout", "alerts": []})

    alerts = [a for r in results.values() for a in r.get("alerts", [])]
    alerts.sort(key=lambda a: (-RANK.get(a.get("severity"), 0), a.get("date") or "", a.get("id")))
    answered = any(r.get("status") == "ok" for r in results.values())
    return {
        "status": "ok" if answered else "unknown",
        "highest_severity": alerts[0]["severity"] if alerts else None,
        "count": len(alerts),
        "alerts": alerts,
        "district": results.get("imd", {}).get("district"),
        "sources": {k: {kk: vv for kk, vv in v.items() if kk != "alerts"} for k, v in results.items()},
        "fetched_at": fetched,
        "note": None if answered else "Official warning status is unknown (no channel answered); this is not 'no alerts'.",
    }
