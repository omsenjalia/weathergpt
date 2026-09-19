"""Credentials factory for WeatherNext Google access.

Credential chain (first source that yields usable credentials wins):

    1. GOOGLE_APPLICATION_CREDENTIALS_JSON  - service account JSON contents in an
       env var. Best fit for Vercel / serverless where no file system secret
       mounts exist. (Primary in production.)
    2. GOOGLE_APPLICATION_CREDENTIALS       - path to a service account /
       workload-identity / authorized-user file, or ambient ADC (gcloud, attached
       service account on Cloud Run / GCE).
    3. GOOGLE_OAUTH_CLIENT_ID + GOOGLE_OAUTH_CLIENT_SECRET +
       GOOGLE_OAUTH_REFRESH_TOKEN         - owner-authorised OAuth user
       credentials refreshed at runtime. (Kept as the fallback.)

If every source fails the adapter reports ``live_credentials_required`` and the
provider chain falls back to the next forecast source - the app never crashes
and always shows the honest source.

Security properties:
- Disabled mode performs no Google auth or reads.
- GOOGLE_APPLICATION_CREDENTIALS is a file path, not JSON; JSON goes in *_JSON.
- OAuth client_id+secret alone is incomplete; refresh_token required.
- No secrets in logs, errors, or health endpoints (only presence flags,
  redacted prefixes and error *types*).
- Credentials are cached per process; google-auth refreshes tokens itself.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from services.config import WeatherNextConfig, get_config
from state import log_event

BIGQUERY_SCOPES = ["https://www.googleapis.com/auth/bigquery"]
OAUTH_TOKEN_URI = "https://oauth2.googleapis.com/token"

# Repository root - credential files inside the repo are rejected.
_REPO_ROOT = Path(__file__).resolve().parents[2]


class AuthStatus(str, Enum):
    DISABLED = "disabled"
    CONFIGURED = "configured"
    MISSING_CREDENTIALS = "missing_credentials"
    INVALID_CONFIG = "invalid_config"
    AUTH_FAILED = "auth_failed"
    READY = "ready"


@dataclass(frozen=True)
class CredentialsResult:
    status: AuthStatus
    mode: Optional[str] = None
    project: Optional[str] = None
    quota_project: Optional[str] = None
    errors: list[str] = None  # type: ignore
    redacted_info: dict = None  # type: ignore

    def __post_init__(self):
        if self.errors is None:
            object.__setattr__(self, "errors", [])
        if self.redacted_info is None:
            object.__setattr__(self, "redacted_info", {})


class CredentialsUnavailable(RuntimeError):
    """Raised when no credential source produced usable Google credentials.

    ``attempts`` lists ``{"source": ..., "error": <redacted>}`` per source tried.
    """

    code = "live_credentials_required"

    def __init__(self, message: str, attempts: Optional[list[dict]] = None):
        super().__init__(message)
        self.attempts = attempts or []


@dataclass
class CredentialBundle:
    """Resolved Google credentials plus the metadata the BigQuery client needs."""
    credentials: Any
    source: str                      # service_account_json | credentials_file | adc | oauth_refresh_token
    project: Optional[str]
    quota_project: Optional[str]
    principal_hint: Optional[str] = None   # redacted identity hint (e.g. SA email domain) for diagnostics
    resolved_at: float = field(default_factory=time.time)


def _redact_path(path: str) -> str:
    """Redact credential path to basename only for logs."""
    try:
        return f".../{Path(path).name}"
    except Exception:
        return ".../credentials"


_TOKEN_RE = re.compile(r"(ya29\.\S+|1//\S+|Bearer\s+\S+|\"?private_key\"?\s*[:=]\s*\S+)")


def _redact_error(exc: BaseException) -> str:
    """Error type + short message with anything token-like stripped."""
    text = str(exc).replace("\n", " ")
    # Drop access / refresh token material if a library ever echoes it.
    text = _TOKEN_RE.sub("[redacted-token]", text)
    return f"{type(exc).__name__}: {text[:200]}"


def _path_inside_repo(path: str) -> bool:
    try:
        Path(path).resolve().relative_to(_REPO_ROOT)
        return True
    except Exception:
        return False


def _running_serverless() -> bool:
    """Vercel / Lambda have no metadata server; skip the slow ambient ADC probe."""
    return bool(os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME") or os.getenv("WEATHERNEXT_SKIP_ADC_PROBE"))


# ---------------------------------------------------------------------------
# Offline validation (no network)
# ---------------------------------------------------------------------------

def validate_credentials(config: Optional[WeatherNextConfig] = None) -> CredentialsResult:
    """Validate WeatherNext credential configuration without performing network calls."""
    cfg = config or get_config().weathernext

    if not cfg.enabled:
        return CredentialsResult(
            status=AuthStatus.DISABLED,
            mode=cfg.auth_mode,
            project=cfg.project,
            quota_project=cfg.quota_project,
            errors=[],
            redacted_info={"enabled": False},
        )

    validation_errors = cfg.validate()
    if validation_errors:
        return CredentialsResult(
            status=AuthStatus.INVALID_CONFIG,
            mode=cfg.auth_mode,
            project=cfg.project,
            quota_project=cfg.quota_project,
            errors=validation_errors,
            redacted_info={"auth_mode": cfg.auth_mode, "surface": cfg.surface},
        )

    sources = cfg.credential_sources()
    redacted: dict[str, Any] = {
        "auth_mode": cfg.auth_mode,
        "project": cfg.project,
        "surface": cfg.surface,
        "credential_sources": sources,
        "has_service_account_json": cfg.has_service_account_json,
        "has_credential_file": cfg.has_credential_file,
        "has_oauth_refresh_token": cfg.has_oauth_refresh_credentials,
        "client_id_prefix": (cfg.oauth.client_id[:12] + "...") if cfg.oauth.client_id else None,
    }

    # Explicit credential file: must exist and live outside the repository.
    if cfg.google_application_credentials:
        cred_path = cfg.google_application_credentials
        redacted["credential_file"] = _redact_path(cred_path)
        if not Path(cred_path).exists():
            if not (cfg.has_service_account_json or cfg.has_oauth_refresh_credentials):
                return CredentialsResult(
                    status=AuthStatus.MISSING_CREDENTIALS,
                    mode=cfg.auth_mode,
                    project=cfg.project,
                    quota_project=cfg.quota_project,
                    errors=[f"Credential file not found: {_redact_path(cred_path)}"],
                    redacted_info=redacted,
                )
            redacted["credential_file_missing"] = True
        elif _path_inside_repo(cred_path) or ".git" in cred_path:
            return CredentialsResult(
                status=AuthStatus.INVALID_CONFIG,
                mode=cfg.auth_mode,
                project=cfg.project,
                quota_project=cfg.quota_project,
                errors=["Credential file must live outside the repository and be mounted as a secret"],
                redacted_info=redacted,
            )

    if sources:
        return CredentialsResult(
            status=AuthStatus.CONFIGURED,
            mode=cfg.auth_mode,
            project=cfg.project,
            quota_project=cfg.quota_project,
            errors=[],
            redacted_info=redacted,
        )

    if cfg.auth_mode == "adc":
        # No explicit source: ambient ADC (gcloud / attached service account) may still work.
        if _running_serverless():
            return CredentialsResult(
                status=AuthStatus.MISSING_CREDENTIALS,
                mode="adc",
                project=cfg.project,
                quota_project=cfg.quota_project,
                errors=[
                    "No credential source configured. Set GOOGLE_APPLICATION_CREDENTIALS_JSON "
                    "(service account JSON) or the GOOGLE_OAUTH_* refresh-token triple."
                ],
                redacted_info=redacted,
            )
        redacted["ambient_adc"] = "will_probe"
        return CredentialsResult(
            status=AuthStatus.CONFIGURED,
            mode="adc",
            project=cfg.project,
            quota_project=cfg.quota_project,
            errors=[],
            redacted_info=redacted,
        )

    # oauth mode without any source
    errors = []
    if not cfg.oauth.client_id:
        errors.append("Missing GOOGLE_OAUTH_CLIENT_ID")
    if not cfg.oauth.client_secret:
        errors.append("Missing GOOGLE_OAUTH_CLIENT_SECRET")
    if not cfg.oauth.refresh_token:
        errors.append("Missing GOOGLE_OAUTH_REFRESH_TOKEN (client_id+secret alone insufficient)")
    return CredentialsResult(
        status=AuthStatus.MISSING_CREDENTIALS,
        mode="oauth",
        project=cfg.project,
        quota_project=cfg.quota_project,
        errors=errors or ["No credential source configured"],
        redacted_info=redacted,
    )


# ---------------------------------------------------------------------------
# Live credential chain
# ---------------------------------------------------------------------------

_bundle_lock = threading.Lock()
_bundle: Optional[CredentialBundle] = None
_last_failure: Optional[dict] = None


def reset_credentials_cache() -> None:
    """Forget cached credentials (tests, or after rotating secrets)."""
    global _bundle, _last_failure
    with _bundle_lock:
        _bundle = None
        _last_failure = None


def _from_service_account_json(cfg: WeatherNextConfig) -> Optional[CredentialBundle]:
    raw = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    if not raw or not raw.lstrip().startswith("{"):
        return None
    from google.oauth2 import service_account  # type: ignore

    info = json.loads(raw)
    if info.get("type") != "service_account":
        raise ValueError("GOOGLE_APPLICATION_CREDENTIALS_JSON is not a service_account key")
    creds = service_account.Credentials.from_service_account_info(info, scopes=BIGQUERY_SCOPES)
    project = cfg.project or info.get("project_id")
    email = info.get("client_email") or ""
    hint = ("..." + email.split("@", 1)[1]) if "@" in email else None
    return CredentialBundle(
        credentials=creds,
        source="service_account_json",
        project=project,
        quota_project=cfg.quota_project or project,
        principal_hint=hint,
    )


def _from_credentials_file_or_adc(cfg: WeatherNextConfig) -> Optional[CredentialBundle]:
    import google.auth  # type: ignore

    path = cfg.google_application_credentials
    if path:
        if not Path(path).exists():
            raise FileNotFoundError(f"Credential file not found: {_redact_path(path)}")
        # load_credentials_from_file handles service_account, external_account
        # (workload identity federation) and authorized_user files alike.
        creds, file_project = google.auth.load_credentials_from_file(path, scopes=BIGQUERY_SCOPES)
        source = "credentials_file"
    else:
        if _running_serverless() or not (cfg.auth_mode == "adc"):
            # Ambient ADC only makes sense on GCP / developer machines; on
            # serverless the metadata probe just burns ~3 s per cold start.
            return None
        creds, file_project = google.auth.default(scopes=BIGQUERY_SCOPES)
        source = "adc"

    quota_project = cfg.quota_project or cfg.project or file_project
    if quota_project and hasattr(creds, "with_quota_project") and getattr(creds, "quota_project_id", None) is None:
        try:
            creds = creds.with_quota_project(quota_project)
        except Exception:  # pragma: no cover - not all credential types support it
            pass
    return CredentialBundle(
        credentials=creds,
        source=source,
        project=cfg.project or file_project,
        quota_project=quota_project,
    )


def _from_oauth_refresh_token(cfg: WeatherNextConfig) -> Optional[CredentialBundle]:
    if not cfg.has_oauth_refresh_credentials:
        return None
    from google.auth.transport.requests import Request  # type: ignore
    from google.oauth2.credentials import Credentials  # type: ignore

    creds = Credentials(
        token=None,
        refresh_token=cfg.oauth.refresh_token,
        token_uri=OAUTH_TOKEN_URI,
        client_id=cfg.oauth.client_id,
        client_secret=cfg.oauth.client_secret,
        scopes=BIGQUERY_SCOPES,
        quota_project_id=cfg.quota_project or cfg.project,
    )
    # Refresh eagerly so a bad/revoked refresh token surfaces here as a
    # credential problem instead of as an opaque BigQuery 401 later.
    creds.refresh(Request())
    return CredentialBundle(
        credentials=creds,
        source="oauth_refresh_token",
        project=cfg.project,
        quota_project=cfg.quota_project or cfg.project,
        principal_hint=(cfg.oauth.client_id[:12] + "...") if cfg.oauth.client_id else None,
    )


_CHAIN = (
    ("service_account_json", _from_service_account_json),
    ("credentials_file_or_adc", _from_credentials_file_or_adc),
    ("oauth_refresh_token", _from_oauth_refresh_token),
)


def get_bigquery_credentials(config: Optional[WeatherNextConfig] = None, *, force_refresh: bool = False) -> CredentialBundle:
    """Resolve Google credentials via SA JSON -> ADC -> OAuth refresh token.

    Raises ``CredentialsUnavailable`` (code ``live_credentials_required``) when
    no source works. Never raises with secret material in the message.
    """
    global _bundle, _last_failure
    cfg = config or get_config().weathernext

    if not cfg.enabled:
        raise CredentialsUnavailable("WeatherNext disabled", attempts=[])

    with _bundle_lock:
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
                attempts.append({"source": name, "error": _redact_error(exc)})
                log_event("WARN", f"WeatherNext credential source '{name}' failed", {"error": _redact_error(exc)})
                continue
            if bundle is None:
                attempts.append({"source": name, "error": "not_configured"})
                continue
            if not bundle.project:
                attempts.append({"source": name, "error": "no billing project (set GOOGLE_CLOUD_PROJECT)"})
                continue
            _bundle = bundle
            _last_failure = None
            log_event("INFO", "WeatherNext credentials resolved", {"source": bundle.source, "project": bundle.project})
            return bundle

        _last_failure = {"attempts": attempts, "at": time.time()}
        raise CredentialsUnavailable(
            "No usable Google credentials (tried: " + ", ".join(a["source"] for a in attempts) + ")",
            attempts=attempts,
        )


def get_active_credential_source() -> Optional[str]:
    return _bundle.source if _bundle else None


def get_credentials_factory_status() -> dict:
    """Safe status for health endpoints (no secrets)."""
    result = validate_credentials()
    cfg = get_config().weathernext
    status: dict[str, Any] = {
        "status": result.status.value,
        "mode": result.mode,
        "project": result.project,
        "quota_project": result.quota_project,
        "enabled": cfg.enabled,
        "surface": cfg.surface,
        "errors": result.errors,
        "redacted": result.redacted_info,
        "chain_order": ["service_account_json", "credentials_file_or_adc", "oauth_refresh_token"],
        "active_source": get_active_credential_source(),
        "active_principal_hint": _bundle.principal_hint if _bundle else None,
        "last_failure": _last_failure,
    }
    if result.status == AuthStatus.CONFIGURED and _bundle is not None:
        status["status"] = AuthStatus.READY.value
    return status


def build_google_credentials():
    """Build Google credentials if possible.

    Returns ``(CredentialBundle | None, error_message | None)``. Kept for
    backward compatibility with callers of the earlier placeholder API.
    """
    cfg = get_config().weathernext
    validation = validate_credentials(cfg)

    if validation.status == AuthStatus.DISABLED:
        return None, "WeatherNext disabled"
    if validation.status in (AuthStatus.INVALID_CONFIG, AuthStatus.MISSING_CREDENTIALS):
        return None, "; ".join(validation.errors)
    try:
        return get_bigquery_credentials(cfg), None
    except CredentialsUnavailable as exc:
        return None, str(exc)
    except Exception as exc:  # pragma: no cover - defensive
        log_event("WARN", f"Failed to build Google credentials: {type(exc).__name__}", {})
        return None, f"Credential construction failed: {type(exc).__name__}"


# ---------------------------------------------------------------------------
# Connectivity check (admin-only, bounded)
# ---------------------------------------------------------------------------

def check_connectivity(probe: bool = False) -> dict:
    """Bounded connectivity check without exposing secrets.

    ``probe=False`` only resolves credentials (a token refresh at most).
    ``probe=True`` additionally runs a BigQuery *dry run* of the point query
    (no bytes billed) and reports the estimated bytes.
    """
    cfg = get_config().weathernext
    cred_status = validate_credentials(cfg)

    if cred_status.status == AuthStatus.DISABLED:
        return {"status": "disabled", "message": "WeatherNext disabled, no Google reads attempted", "configured": False}

    if cred_status.status != AuthStatus.CONFIGURED:
        return {
            "status": cred_status.status.value,
            "message": "; ".join(cred_status.errors) if cred_status.errors else "Not configured",
            "configured": False,
            "errors": cred_status.errors,
        }

    try:
        import google.auth  # type: ignore  # noqa: F401
    except ImportError:
        return {
            "status": "configured_no_library",
            "message": "google-auth / google-cloud-bigquery not installed, but configuration appears valid",
            "configured": True,
            "mode": cfg.auth_mode,
            "project": cfg.project,
            "surface": cfg.surface,
        }

    try:
        bundle = get_bigquery_credentials(cfg)
    except CredentialsUnavailable as exc:
        return {
            "status": "auth_failed",
            "code": exc.code,
            "message": str(exc),
            "attempts": exc.attempts,
            "configured": True,
            "mode": cfg.auth_mode,
        }
    except Exception as exc:
        return {"status": "auth_failed", "message": _redact_error(exc), "configured": True, "mode": cfg.auth_mode}

    out: dict[str, Any] = {
        "status": "ready",
        "message": f"Credentials resolved via {bundle.source} for project={bundle.project}",
        "configured": True,
        "mode": cfg.auth_mode,
        "credential_source": bundle.source,
        "principal_hint": bundle.principal_hint,
        "project": bundle.project,
        "quota_project": bundle.quota_project,
        "surface": cfg.surface,
        "table": cfg.bq.surface_table,
    }

    if probe and cfg.surface == "bigquery":
        try:
            from services.weathernext_bigquery import get_bigquery_adapter
            out["dry_run"] = get_bigquery_adapter().estimate_point_query(lat=22.0, lon=72.0, horizon_hours=72)
        except Exception as exc:
            out["dry_run"] = {"status": "failed", "error": _redact_error(exc), "code": getattr(exc, "code", None)}
    return out
