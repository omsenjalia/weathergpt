"""Authenticated client for the IMD API gateway.

Auth (verified against https://api.imd.gov.in on 2026-09-28):
    X-API-Key: <IMD_API_KEY>
    Authorization: Bearer <IMD_JWT_TOKEN>
Missing either header is rejected with 401; a bad JWT with
``{"error": "Invalid or expired JWT token"}``. Access is additionally
IP-whitelisted by IMD.

Relay mode (IMD_RELAY_TOKEN set): requests go to IMD_BASE_URL (the relay in
``relay/imd_relay.py``) with only ``X-Relay-Token``. The relay adds the key and JWT.

Responses are either a JSON array of rows or an envelope
``{"status", "message", "totalCount", "data"}``; both are normalised to ``rows``.
"""

from __future__ import annotations

import base64
import json
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from weathergpt import http
from weathergpt.config import settings
from weathergpt.imd import endpoints
from weathergpt.runtime import log_event, make_cache

_cache = make_cache("imd", max_entries=256)
_stats: dict[str, Any] = {"calls": 0, "errors": 0, "last_error": None, "last_success_at": None}


class IMDError(RuntimeError):
    def __init__(self, reason: str, message: str, status: Optional[int] = None, transient: bool = False):
        super().__init__(message)
        self.reason = reason
        self.status = status
        self.transient = transient

    def to_dict(self) -> dict:
        return {"reason": self.reason, "message": str(self), "status": self.status}


@dataclass
class IMDResponse:
    endpoint: str
    path: str
    params: dict
    rows: list
    envelope: Optional[dict] = None
    content_type: str = "application/json"
    raw_bytes: Optional[bytes] = None
    fetched_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    cache_hit: bool = False

    def to_dict(self) -> dict:
        out = {
            "endpoint": self.endpoint,
            "path": self.path,
            "params": self.params,
            "count": len(self.rows),
            "data": self.rows,
            "fetched_at": self.fetched_at,
            "cache_hit": self.cache_hit,
            "source": "imd",
        }
        if self.envelope:
            out["envelope"] = {k: v for k, v in self.envelope.items() if k != "data"}
        return out


def jwt_expiry(token: str | None) -> datetime | None:
    """Expiry from an IMD token (first segment is base64 JSON, e.g. {"uid":..,"exp":..})."""
    if not token:
        return None
    try:
        head = token.split(".")[0]
        payload = json.loads(base64.urlsafe_b64decode(head + "=" * (-len(head) % 4)))
        return datetime.fromtimestamp(float(payload["exp"]), timezone.utc)
    except (ValueError, KeyError, TypeError):
        return None


# --------------------------------------------------------------------------- tokens
# IMD JWTs last 1 h (``expires_in: 3600``). With IMD_EMAIL + IMD_PASSWORD the backend
# mints them at POST /api/oauth/token.php and renews them two minutes before expiry,
# and once more if the gateway rejects one early. A pasted IMD_JWT_TOKEN also works.
_REFRESH_MARGIN_SECONDS = 120
_token_lock = threading.Lock()
_minted: dict[str, Any] = {"token": None, "expires": None, "at": None, "error": None}


def mint_token() -> tuple[str, Optional[datetime]]:
    """Exchange IMD_EMAIL / IMD_PASSWORD for a JWT -> (token, expiry). Raises ``IMDError``."""
    cfg = settings().imd
    if not cfg.can_mint:
        raise IMDError("not_configured", "Set IMD_EMAIL and IMD_PASSWORD so the backend can renew IMD tokens")
    try:
        reply = http.send("POST", cfg.token_url, body={"email": cfg.email, "password": cfg.password},
                          headers={"Content-Type": "application/json", "Accept": "application/json",
                                   "User-Agent": "WeatherGPT/3.0"}, timeout=cfg.timeout_seconds, retries=1)
    except http.UpstreamError as exc:
        raise IMDError(exc.reason, f"IMD token endpoint unreachable: {exc}", exc.status, transient=True) from exc
    try:
        body: Any = reply.json()
    except ValueError:
        body = {}
    if reply.status >= 400:
        text = _error_text(body) or f"HTTP {reply.status}"
        if reply.status in (400, 401):
            raise IMDError("login_rejected", f"IMD rejected IMD_EMAIL/IMD_PASSWORD: {text}", reply.status)
        raise classify(reply.status, text)
    token = body.get("access_token") if isinstance(body, dict) else None
    if not isinstance(token, str) or not token.strip():
        raise IMDError("token_response_unrecognised", "IMD token endpoint answered without access_token", reply.status)
    token = token.strip()
    expires = jwt_expiry(token)
    if expires is None and isinstance(body.get("expires_in"), (int, float)):
        expires = datetime.now(timezone.utc) + timedelta(seconds=float(body["expires_in"]))
    log_event("INFO", "IMD token renewed", {"expires_at": expires.isoformat() if expires else None})
    return token, expires


def current_token(*, force_refresh: bool = False) -> str:
    """A usable JWT: minted and renewed when credentials allow, else IMD_JWT_TOKEN."""
    cfg = settings().imd
    now = datetime.now(timezone.utc)
    with _token_lock:
        token = _minted["token"] or cfg.jwt_token
        expires = _minted["expires"] if _minted["token"] else jwt_expiry(cfg.jwt_token)
        fresh = bool(token) and (expires is None or (expires - now).total_seconds() > _REFRESH_MARGIN_SECONDS)
        if fresh and not force_refresh:
            return token
        if cfg.can_mint:
            try:
                new_token, new_expires = mint_token()
            except IMDError as exc:
                _minted["error"] = exc.to_dict()
                if token and expires is not None and expires > now and not force_refresh:
                    return token  # still valid for a moment; renewal will be retried next call
                raise
            _minted.update(token=new_token, expires=new_expires, at=now.isoformat(), error=None)
            return new_token
    if not token:
        raise IMDError("not_configured", "IMD_JWT_TOKEN missing")
    if expires is not None and expires <= now:
        raise IMDError("token_expired", f"IMD_JWT_TOKEN expired at {expires.isoformat()}; set IMD_EMAIL and "
                                        "IMD_PASSWORD so the backend renews tokens itself")
    return token


def reset_tokens() -> None:
    with _token_lock:
        _minted.update(token=None, expires=None, at=None, error=None)


def _auth_headers(token: Optional[str]) -> dict:
    cfg = settings().imd
    if cfg.relay:
        return {"X-Relay-Token": cfg.relay_token or "", "Accept": "application/json", "User-Agent": "WeatherGPT/3.0"}
    return {
        "X-API-KEY": settings().imd.api_key or "",
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "WeatherGPT/3.0",
    }


def _error_text(body: Any) -> str:
    if isinstance(body, dict):
        for key in ("error", "message", "detail", "msg"):
            if body.get(key):
                return str(body[key])
    return ""


def classify(status: int, text: str) -> IMDError:
    lowered = text.lower()
    if status == 401 or "jwt" in lowered or "api key" in lowered or "authorization" in lowered:
        if "jwt" in lowered or "token" in lowered:
            reason = "token_invalid_or_expired"
        elif "api key" in lowered:
            reason = "api_key_rejected"
        else:
            reason = "unauthorized"
        return IMDError(reason, f"IMD rejected credentials: {text or 'HTTP 401'}", status)
    if status == 403:
        return IMDError("forbidden_ip_not_whitelisted",
                        f"IMD refused access (HTTP 403{': ' + text if text else ''}). "
                        "The server's egress IP must be whitelisted by IMD.", status)
    if status == 404:
        return IMDError("endpoint_not_found", f"IMD endpoint not found (HTTP 404){': ' + text if text else ''}", status)
    if status == 429:
        return IMDError("rate_limited", "IMD rate limit reached", status, transient=True)
    if status >= 500:
        return IMDError("upstream_error", f"IMD returned HTTP {status}", status, transient=True)
    return IMDError("bad_request", f"IMD returned HTTP {status}: {text[:200]}", status)


def _rows(body: Any) -> tuple[list, Optional[dict]]:
    if isinstance(body, list):
        return body, None
    if isinstance(body, dict):
        data = body.get("data")
        if isinstance(data, list):
            return data, body
        if isinstance(data, dict):
            return [data], body
        if data is None and not _error_text(body):
            return [body], None
        return [], body
    return [], None


def fetch(key: str, params: Optional[dict] = None, *, use_cache: bool = True) -> IMDResponse:
    """Call one registered IMD endpoint. Raises ``IMDError``."""
    cfg = settings().imd
    ep = endpoints.get(key)
    if ep is None:
        raise IMDError("unknown_endpoint", f"Unknown IMD endpoint '{key}'")
    if not cfg.enabled:
        raise IMDError("disabled", "IMD is disabled (IMD_ENABLED=0)")
    if not cfg.configured:
        raise IMDError("not_configured", f"IMD credentials missing: {', '.join(cfg.missing())}")

    clean = {k: str(v) for k, v in (params or {}).items() if v is not None and str(v).strip() != ""}
    path = ep.resolved_path()
    cache_key = f"{path}?{json.dumps(clean, sort_keys=True)}"
    if use_cache:
        hit = _cache.get(cache_key)
        if isinstance(hit, IMDError):
            raise hit
        if hit is not None:
            return IMDResponse(**{**hit.__dict__, "cache_hit": True})

    url = f"{cfg.base_url}/{path}"
    started = time.perf_counter()
    try:
        # An already-expired token is caught here, before a gateway call is spent on it.
        reply = _get(url, clean, None if cfg.relay else current_token())
        if reply.status == 401 and cfg.can_mint and "token" in reply.text.lower():
            reply = _get(url, clean, current_token(force_refresh=True))  # rejected early: renew once
    except IMDError as err:
        _record_error(key, err.reason, str(err))
        raise

    body: Any = None
    is_json = "json" in reply.content_type or reply.content.lstrip()[:1] in (b"[", b"{")
    if is_json:
        try:
            body = reply.json()
        except ValueError:
            body = None
            is_json = False

    if reply.status >= 400:
        err = classify(reply.status, _error_text(body) or (reply.text[:200] if not is_json else ""))
        _record_error(key, err.reason, str(err))
        if not err.transient:
            _cache.set(cache_key, err, 60)   # don't hammer the gateway with a known-bad credential
        raise err

    if not is_json:
        # Radar/lightning products may be images; keep bytes for the proxy route.
        resp = IMDResponse(key, f"/api/v1/{path}", clean, [], content_type=reply.content_type or "application/octet-stream",
                           raw_bytes=reply.content)
    else:
        if isinstance(body, dict) and _error_text(body) and body.get("data") is None and body.get("status") is not True:
            err = classify(401 if "token" in _error_text(body).lower() else 400, _error_text(body))
            _record_error(key, err.reason, str(err))
            raise err
        rows, envelope = _rows(body)
        resp = IMDResponse(key, f"/api/v1/{path}", clean, rows, envelope)

    _stats["last_success_at"] = datetime.now(timezone.utc).isoformat()
    log_event("INFO", f"IMD {key} ok", {"rows": len(resp.rows), "ms": round((time.perf_counter() - started) * 1000)})
    _cache.set(cache_key, resp, ep.cache_seconds)
    return resp


def _get(url: str, params: dict, token: Optional[str]) -> "http.Reply":
    _stats["calls"] += 1
    try:
        return http.send("GET", url, params=params, headers=_auth_headers(token),
                         timeout=settings().imd.timeout_seconds, retries=1)
    except http.UpstreamError as exc:
        raise IMDError(exc.reason, f"IMD unreachable: {exc}", exc.status, transient=True) from exc


def _record_error(key: str, reason: str, message: str) -> None:
    _stats["errors"] += 1
    _stats["last_error"] = {"endpoint": key, "reason": reason, "message": message[:200],
                            "at": datetime.now(timezone.utc).isoformat()}
    log_event("WARN", f"IMD {key} failed: {reason}", {"message": message[:200]})


def status() -> dict:
    cfg = settings().imd
    expires = _minted["expires"] if _minted["token"] else jwt_expiry(cfg.jwt_token)
    return {
        "relay": cfg.relay,
        "token_source": "relay" if cfg.relay else ("minted" if _minted["token"] else ("env" if cfg.jwt_token else None)),
        "auto_renew": cfg.can_mint,
        "last_renewal_at": _minted["at"],
        "last_renewal_error": _minted["error"],
        "public_proxy": cfg.public_proxy,
        "jwt_expires_at": expires.isoformat() if expires else None,
        "jwt_expired": bool(expires and expires <= datetime.now(timezone.utc)),
        "configured": cfg.configured,
        "enabled": cfg.enabled,
        "missing": cfg.missing(),
        "base_url": cfg.base_url,
        "auth_scheme": ("X-Relay-Token (the relay adds X-API-KEY and the JWT)" if cfg.relay else
                        "X-API-KEY (bound to server IP) + Authorization: Bearer <JWT from POST /api/oauth/token.php>"),
        "max_station_km": cfg.max_station_km,
        "calls": _stats["calls"],
        "errors": _stats["errors"],
        "last_error": _stats["last_error"],
        "last_success_at": _stats["last_success_at"],
        "cache": _cache.stats(),
    }


def probe() -> list[dict]:
    """Call every registered endpoint once (bypassing cache) and report the outcome."""
    results = []
    for ep in endpoints.ENDPOINTS:
        started = time.perf_counter()
        entry = {"key": ep.key, "path": f"/api/v1/{ep.resolved_path()}", "path_verified": ep.verified}
        try:
            resp = fetch(ep.key, ep.probe_params, use_cache=False)
            entry.update(ok=True, rows=len(resp.rows), content_type=resp.content_type,
                         sample_keys=sorted(resp.rows[0].keys())[:40] if resp.rows and isinstance(resp.rows[0], dict) else None)
        except IMDError as exc:
            entry.update(ok=False, **exc.to_dict())
        entry["ms"] = round((time.perf_counter() - started) * 1000)
        results.append(entry)
    return results
