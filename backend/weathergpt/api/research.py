"""GET /historical and /comparison — yearly climate series (researcher screens)."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

from weathergpt import http
from weathergpt.weather import archive

router = APIRouter(tags=["research"])


@router.get("/historical")
async def historical(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    metric: str = Query("rainfall", description="rainfall | temperature | humidity"),
    start_year: Optional[int] = Query(None, ge=1940, le=2100),
    end_year: Optional[int] = Query(None, ge=1940, le=2100),
) -> dict[str, Any]:
    start, end = archive.default_range(start_year, end_year)
    try:
        return await run_in_threadpool(archive.yearly_series, lat, lon, metric, start, end)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except http.UpstreamError as exc:
        raise HTTPException(status_code=502, detail={"reason": exc.reason, "message": str(exc)}) from exc


@router.get("/comparison")
async def comparison(
    locations: str = Query(..., description="name,lat,lon;name2,lat2,lon2 (names may contain commas)"),
    metric: str = Query("rainfall"),
    start_year: Optional[int] = Query(None, ge=1940, le=2100),
    end_year: Optional[int] = Query(None, ge=1940, le=2100),
) -> dict[str, Any]:
    parsed = archive.parse_locations(locations)
    if not parsed:
        raise HTTPException(status_code=400, detail="Provide locations as name,lat,lon;name2,lat2,lon2")
    if metric.lower().strip() not in archive.METRICS:
        raise HTTPException(status_code=400, detail=f"metric must be one of: {', '.join(archive.METRICS)}")
    start, end = archive.default_range(start_year, end_year, span=10)
    if end < start or end - start > 40:
        raise HTTPException(status_code=400, detail="Invalid year range (max 40 years)")
    return await run_in_threadpool(archive.comparison, parsed, metric, start, end)
