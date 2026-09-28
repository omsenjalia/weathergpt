"""Outbound HTTP for every upstream (Open-Meteo, IMD, SACHET, Nominatim, Bhashini, TypeSafe).

All calls go through ``send()`` so tests can install one fake transport
(``set_transport``) and exercise real parsing/selection code with no network.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

import httpx


@dataclass
class Reply:
    status: int
    headers: dict[str, str]
    content: bytes

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.content)

    @property
    def content_type(self) -> str:
        return (self.headers.get("content-type") or "").split(";")[0].strip().lower()


class UpstreamError(RuntimeError):
    """An upstream call failed. ``reason`` is a stable machine-readable code."""

    def __init__(self, reason: str, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.reason = reason
        self.status = status


Transport = Callable[[str, str, dict, dict, Any, float], Reply]


def _httpx_transport(method: str, url: str, params: dict, headers: dict, body: Any, timeout: float) -> Reply:
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        resp = client.request(method, url, params=params or None, headers=headers or None,
                              json=body if body is not None else None)
        return Reply(resp.status_code, {k.lower(): v for k, v in resp.headers.items()}, resp.content)


_transport: Transport = _httpx_transport


def set_transport(transport: Optional[Transport]) -> None:
    """Install a fake transport (tests) or restore the real one with ``None``."""
    global _transport
    _transport = transport or _httpx_transport


def send(method: str, url: str, *, params: Optional[dict] = None, headers: Optional[dict] = None,
         body: Any = None, timeout: float = 10.0, retries: int = 1) -> Reply:
    """Send a request; network errors and 5xx/429 are retried ``retries`` times.

    Returns the final ``Reply`` for any HTTP status (callers classify 4xx).
    Raises ``UpstreamError`` only when no HTTP response was obtained.
    """
    last: Optional[Exception] = None
    reply: Optional[Reply] = None
    for attempt in range(retries + 1):
        try:
            reply = _transport(method, url, params or {}, headers or {}, body, timeout)
        except httpx.TimeoutException as exc:
            last = exc
            reply = None
        except (httpx.HTTPError, OSError) as exc:
            last = exc
            reply = None
        if reply is not None and reply.status < 500 and reply.status != 429:
            return reply
        if attempt < retries:
            time.sleep(0.2 * (attempt + 1))
    if reply is not None:
        return reply
    if isinstance(last, httpx.TimeoutException):
        raise UpstreamError("timeout", f"{_host(url)} timed out", 504)
    raise UpstreamError("network_error", f"{_host(url)} unreachable: {type(last).__name__}", 502)


def get_json(url: str, params: Optional[dict] = None, *, headers: Optional[dict] = None,
             timeout: float = 10.0, retries: int = 1) -> Any:
    """GET and decode JSON; any non-2xx or bad body raises ``UpstreamError``."""
    reply = send("GET", url, params=params, headers=headers, timeout=timeout, retries=retries)
    if reply.status >= 400:
        raise UpstreamError(f"http_{reply.status}", f"{_host(url)} returned HTTP {reply.status}", reply.status)
    try:
        return reply.json()
    except ValueError as exc:
        raise UpstreamError("invalid_json", f"{_host(url)} returned invalid JSON", 502) from exc


def _host(url: str) -> str:
    try:
        return httpx.URL(url).host or url
    except Exception:
        return url
