"""GET /advisory — farm action windows (spraying / irrigation / field work)."""

from __future__ import annotations

import os
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

from weathergpt.ai import typesafe
from weathergpt.alerts.service import get_alerts
from weathergpt.api.common import resolve_mode, resolve_source
from weathergpt.farm import advisory
from weathergpt.weather.service import service
from weathergpt.weather.supplement import supplement

router = APIRouter(tags=["farm"])


@router.get("/advisory")
@router.get("/advisory/", include_in_schema=False)
async def get_advisory(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    crop: str = Query(""),
    days: int = Query(7, ge=1, le=7),
    growth_stage: str = Query(""),
    soil: str = Query(""),
    irrigation: str = Query(""),
    source: Optional[str] = Query(None),
    requested_source: Optional[str] = Query(None),
    mode: Optional[str] = Query(None),
    place: str = Query("", description="Display name for the summary"),
) -> dict[str, Any]:
    m = resolve_mode(mode, default="farmer")
    src = resolve_source(requested_source, source)

    def work() -> dict:
        sel = service().select(lat, lon, requested_source=src, forecast_days=days)
        if sel.forecast is None:
            raise HTTPException(status_code=502, detail={"status": "unavailable", "requested_source": src,
                                                         "error": sel.error, "fallback_reasons": sel.fallback_reasons})
        fc = sel.forecast
        supplement(fc, lat, lon, days)
        alerts = get_alerts(lat, lon, timeout=6.0)
        windows, _ = advisory.build_windows(fc, days, alerts.get("alerts", []))
        crop_label = crop.strip() or "general crops"
        ai: dict[str, Any] = {"enabled": typesafe.is_enabled(), "applied": False, "model": None}
        if windows and typesafe.is_enabled():
            tz = fc.location.get("timezone") or "Asia/Kolkata"
            result = typesafe.evaluate(
                advisory.build_state(crop_label, lat, lon, windows,
                                     {"growth_stage": growth_stage, "soil": soil, "irrigation": irrigation}, tz),
                advisory.build_questions(windows, tz),
                timeout=float(os.getenv("TYPESAFE_ADVISORY_TIMEOUT_SECONDS", "6")), label="advisory")
            if result:
                ai = advisory.apply_overlay(windows, result["answers"], model=typesafe.model_name(),
                                            min_confidence=float(os.getenv("TYPESAFE_ADVISORY_MIN_CONFIDENCE", "0.55")))
        return {
            "lat": lat, "lon": lon, "crop": crop_label, "mode": m,
            "farm": {"growth_stage": growth_stage or None, "soil": soil or None, "irrigation": irrigation or None},
            "summary": advisory.summary_line(crop_label, windows, place or fc.location.get("name") or f"{lat:.2f}, {lon:.2f}"),
            "windows": windows,
            "advisory_engine": "system-one+thresholds" if ai.get("applied") else "thresholds",
            "ai": ai,
            "official_alerts": {"status": alerts.get("status"), "count": alerts.get("count", 0)},
            "timezone": fc.location.get("timezone"),
            "source": sel.selected_source, "requested_source": src,
            "fallback_reasons": sel.fallback_reasons, "degraded": sel.degraded,
            "field_sources": {k: v for k, v in fc.field_sources.items() if not k.startswith("_")},
            "provenance": fc.provenance.to_dict(),
        }

    return await run_in_threadpool(work)
