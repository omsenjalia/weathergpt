"""Google credentials for BigQuery, tried in order (first usable wins):

1. ``GOOGLE_APPLICATION_CREDENTIALS_JSON`` — service-account JSON in one env value (Vercel)
2. ``GOOGLE_APPLICATION_CREDENTIALS`` file, or ambient ADC (skipped on serverless)
3. ``GOOGLE_OAUTH_CLIENT_ID/SECRET/REFRESH_TOKEN`` — owner-authorised OAuth (dev)

No secret material is ever logged or returned.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from weathergpt.config import WeatherNextSettings, settings
from weathergpt.runtime import log_event

SCOPES = ("https://www.googleapis.com/auth/bigquery",)


class CredentialsUnavailable(RuntimeError):
    code = "live_credentials_required"

    def __init__(self, message: str, attempts: Optional[list[dict]] = None):
        super().__init__(message)
        self.attempts = attempts or []


@dataclass
class CredentialBundle:
    credentials: Any
    source: str
    project: Optional[str]


_bundle: Optional[CredentialBundle] = None
_last_failure: Optional[dict] = None
_lock = threading.Lock()


def _redact(exc: BaseException) -> str:
    text = str(exc).replace("\n", " ")
    for marker in ("-----BEGIN", "private_key", "refresh_token", "client_secret"):
        if marker in text:
            return f"{type(exc).__name__}: [redacted]"
    return f"{type(exc).__name__}: {text[:160]}"


def _serverless() -> bool:
    return bool(os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME") or os.getenv("WEATHERNEXT_SKIP_ADC_PROBE"))


def _from_json(cfg: WeatherNextSettings) -> Optional[CredentialBundle]:
    raw = (os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON") or "").strip()
    if not raw.startswith("{"):
        return None
    from google.oauth2 import service_account  # type: ignore

    info = json.loads(raw)
    if info.get("type") != "service_account":
        raise ValueError("GOOGLE_APPLICATION_CREDENTIALS_JSON is not a service_account key")
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    return CredentialBundle(creds, "service_account_json", cfg.project or info.get("project_id"))


def _from_file_or_adc(cfg: WeatherNextSettings) -> Optional[CredentialBundle]:
    import google.auth  # type: ignore

    if cfg.credentials_path:
        if not Path(cfg.credentials_path).exists():
            raise FileNotFoundError("GOOGLE_APPLICATION_CREDENTIALS file not found")
        creds, project = google.auth.load_credentials_from_file(cfg.credentials_path, scopes=SCOPES)
        source = "credentials_file"
    else:
        if _serverless():
            return None
        creds, project = google.auth.default(scopes=SCOPES)
        source = "adc"
    quota = cfg.quota_project or cfg.project or project
    if quota and hasattr(creds, "with_quota_project") and getattr(creds, "quota_project_id", None) is None:
        try:
            creds = creds.with_quota_project(quota)
        except Exception:
            pass
    return CredentialBundle(creds, source, cfg.project or project)


def _from_oauth(cfg: WeatherNextSettings) -> Optional[CredentialBundle]:
    if not cfg.has_oauth:
        return None
    from google.auth.transport.requests import Request  # type: ignore
    from google.oauth2.credentials import Credentials  # type: ignore

    creds = Credentials(token=None, refresh_token=cfg.oauth_refresh_token, token_uri="https://oauth2.googleapis.com/token",
                        client_id=cfg.oauth_client_id, client_secret=cfg.oauth_client_secret, scopes=list(SCOPES),
                        quota_project_id=cfg.quota_project or cfg.project)
    creds.refresh(Request())  # surface a revoked token here, not as an opaque BigQuery 401
    return CredentialBundle(creds, "oauth_refresh_token", cfg.project)


_CHAIN = (("service_account_json", _from_json), ("credentials_file_or_adc", _from_file_or_adc),
          ("oauth_refresh_token", _from_oauth))


def get_credentials(force_refresh: bool = False) -> CredentialBundle:
    global _bundle, _last_failure
    cfg = settings().weathernext
    if not cfg.enabled:
        raise CredentialsUnavailable("WeatherNext disabled")
    with _lock:
        if _bundle is not None and not force_refresh:
            return _bundle
        attempts: list[dict] = []
        for name, factory in _CHAIN:
            try:
                bundle = factory(cfg)
            except ImportError as exc:
                attempts.append({"source": name, "error": f"missing_dependency: {type(exc).__name__}"})
                continue
            except Exception as exc:
                attempts.append({"source": name, "error": _redact(exc)})
                continue
            if bundle is None:
                attempts.append({"source": name, "error": "not_configured"})
                continue
            if not bundle.project:
                attempts.append({"source": name, "error": "no billing project (set GOOGLE_CLOUD_PROJECT)"})
                continue
            _bundle, _last_failure = bundle, None
            log_event("INFO", "WeatherNext credentials resolved", {"source": bundle.source})
            return bundle
        _last_failure = {"attempts": attempts, "at": time.time()}
        raise CredentialsUnavailable("No usable Google credentials", attempts)


def reset() -> None:
    global _bundle, _last_failure
    with _lock:
        _bundle, _last_failure = None, None


def status() -> dict:
    cfg = settings().weathernext
    return {
        "enabled": cfg.enabled,
        "mock_data": cfg.mock_data,
        "project": cfg.project,
        "configured_sources": cfg.credential_sources(),
        "problems": cfg.problems(),
        "active_source": _bundle.source if _bundle else None,
        "last_failure": _last_failure,
    }
