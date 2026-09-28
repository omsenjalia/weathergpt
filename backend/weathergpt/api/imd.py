"""IMD gateway endpoints — every published IMD API, proxied with server-side credentials.

GET /v2/imd                 catalog of all endpoints + configuration status (no secrets)
GET /v2/imd/nearest         nearest IMD city station, its observation and the point's district
GET /v2/imd/{endpoint}      proxy one endpoint (id / sid / lat / lon query params pass through)

IMD's terms prohibit unauthorized redistribution, so raw data from /nearest and
/{endpoint} needs ``X-Admin-Token`` unless IMD_PUBLIC_PROXY=1. The apps get IMD data
through /v2/weather, /v2/alerts and /chat, which are unaffected.

Errors: 503 {code: imd_not_configured}, 502 {code: imd_error, reason} (e.g. token_invalid_or_expired,
forbidden_ip_not_whitelisted), 404 unknown endpoint.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response

from weathergpt import geo
from weathergpt.api.dev import require_admin
from weathergpt.config import settings
from weathergpt.imd import client, endpoints, stations

router = APIRouter(prefix="/v2/imd", tags=["imd"])


def _raise(exc: client.IMDError) -> None:
    if exc.reason in ("not_configured", "disabled"):
        raise HTTPException(status_code=503, detail={"code": "imd_not_configured", "reason": exc.reason, "message": str(exc)})
    raise HTTPException(status_code=502, detail={"code": "imd_error", "reason": exc.reason, "message": str(exc),
                                                 "upstream_status": exc.status})


def _gate(token: Optional[str]) -> None:
    if not settings().imd.public_proxy:
        require_admin(token)


@router.get("")
@router.get("/", include_in_schema=False)
async def imd_catalog() -> dict[str, Any]:
    return {"status": client.status(), "count": len(endpoints.ENDPOINTS), "endpoints": endpoints.catalog(),
            "documentation": "https://api.imd.gov.in/public/api_reference.html"}


@router.get("/nearest")
async def imd_nearest(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180),
                      x_admin_token: Optional[str] = Header(None)) -> dict:
    _gate(x_admin_token)
    def work() -> dict:
        try:
            station = stations.nearest_city_station(lat, lon)
            observation = stations.observation_for(station) if station else None
        except client.IMDError as exc:
            _raise(exc)
        return {"station": station.to_dict() if station else None, "forecast_row": station.row if station else None,
                "observation": observation, "district": geo.reverse(lat, lon)}

    return await run_in_threadpool(work)


@router.get("/{key}")
async def imd_proxy(
    key: str,
    id: Optional[str] = Query(None, description="Station / district / basin / area id (see catalog)"),
    sid: Optional[str] = Query(None, description="State id (aws_data)"),
    lat: Optional[float] = Query(None, ge=-90, le=90),
    lon: Optional[float] = Query(None, ge=-180, le=180),
    limit: int = Query(0, ge=0, le=5000, description="Truncate rows (0 = all)"),
    x_admin_token: Optional[str] = Header(None),
):
    _gate(x_admin_token)
    ep = endpoints.get(key)
    if ep is None:
        raise HTTPException(status_code=404, detail={"code": "unknown_endpoint", "endpoints": list(endpoints.BY_KEY)})
    missing = [p.name for p in ep.params if p.required and {"id": id, "sid": sid, "lat": lat, "lon": lon}.get(p.name) is None]
    if missing:
        raise HTTPException(status_code=422, detail=f"missing required parameter(s): {', '.join(missing)}")

    def work():
        try:
            return client.fetch(key, {"id": id, "sid": sid, "lat": lat, "lon": lon})
        except client.IMDError as exc:
            _raise(exc)

    resp = await run_in_threadpool(work)
    if resp.raw_bytes is not None:  # images (radar) pass through unchanged
        return Response(content=resp.raw_bytes, media_type=resp.content_type,
                        headers={"Cache-Control": f"public, max-age={ep.cache_seconds}"})
    body = resp.to_dict()
    body["title"] = ep.title
    body["path_verified"] = ep.to_dict()["path_verified"]
    if limit:
        body["data"] = body["data"][:limit]
        body["truncated"] = resp.rows[limit:] != []
    return body
