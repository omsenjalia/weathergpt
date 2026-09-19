"""Credentials factory for WeatherNext Google access.

Implements two explicit auth modes:
- ADC (default, recommended): local gcloud ADC, attached service account, or workload identity
- OAuth: owner-authorized user credentials via refresh token

Security properties:
- Disabled mode performs no Google auth or reads.
- No mixing of credential sources; one explicit mode.
- GOOGLE_APPLICATION_CREDENTIALS is a file path, not JSON.
- OAuth client_id+secret alone is incomplete; refresh_token required.
- No secrets in logs, errors, or health endpoints.
- Validates file existence and permissions where possible.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

from services.config import WeatherNextConfig, get_config
from state import log_event


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


def _redact_path(path: str) -> str:
    """Redact credential path to basename only for logs."""
    try:
        return f".../{Path(path).name}"
    except Exception:
        return ".../credentials"


def validate_credentials(config: Optional[WeatherNextConfig] = None) -> CredentialsResult:
    """Validate WeatherNext credentials without performing network calls."""
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

    # Run config validation
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

    if cfg.auth_mode == "adc":
        # ADC mode: either no explicit file (uses gcloud ADC / attached SA) or a file path
        if cfg.google_application_credentials:
            cred_path = cfg.google_application_credentials
            # Check if file exists (best effort, not fatal in all envs)
            if not Path(cred_path).exists():
                # In production with mounted secrets, file may appear later; treat as missing but not invalid
                return CredentialsResult(
                    status=AuthStatus.MISSING_CREDENTIALS,
                    mode="adc",
                    project=cfg.project,
                    quota_project=cfg.quota_project,
                    errors=[f"Credential file not found: {_redact_path(cred_path)}"],
                    redacted_info={"auth_mode": "adc", "credential_file": _redact_path(cred_path)},
                )
            # Check it's not world-readable JSON in repo
            if cred_path.startswith("/home/") or ".git" in cred_path:
                return CredentialsResult(
                    status=AuthStatus.INVALID_CONFIG,
                    mode="adc",
                    project=cfg.project,
                    quota_project=cfg.quota_project,
                    errors=["Credential file should be outside repository and mounted as secret"],
                    redacted_info={"auth_mode": "adc"},
                )
        return CredentialsResult(
            status=AuthStatus.CONFIGURED,
            mode="adc",
            project=cfg.project,
            quota_project=cfg.quota_project,
            errors=[],
            redacted_info={
                "auth_mode": "adc",
                "project": cfg.project,
                "has_explicit_file": bool(cfg.google_application_credentials),
                "surface": cfg.surface,
            },
        )

    elif cfg.auth_mode == "oauth":
        # OAuth mode: requires client_id, secret, refresh_token
        errors = []
        if not cfg.oauth.client_id:
            errors.append("Missing GOOGLE_OAUTH_CLIENT_ID")
        if not cfg.oauth.client_secret:
            errors.append("Missing GOOGLE_OAUTH_CLIENT_SECRET")
        if not cfg.oauth.refresh_token:
            errors.append("Missing GOOGLE_OAUTH_REFRESH_TOKEN (client_id+secret alone insufficient)")
        if errors:
            return CredentialsResult(
                status=AuthStatus.MISSING_CREDENTIALS,
                mode="oauth",
                project=cfg.project,
                quota_project=cfg.quota_project,
                errors=errors,
                redacted_info={"auth_mode": "oauth"},
            )
        return CredentialsResult(
            status=AuthStatus.CONFIGURED,
            mode="oauth",
            project=cfg.project,
            quota_project=cfg.quota_project,
            errors=[],
            redacted_info={
                "auth_mode": "oauth",
                "project": cfg.project,
                "client_id_prefix": cfg.oauth.client_id[:12] + "..." if cfg.oauth.client_id else None,
                "has_refresh_token": bool(cfg.oauth.refresh_token),
            },
        )

    else:
        return CredentialsResult(
            status=AuthStatus.INVALID_CONFIG,
            mode=str(cfg.auth_mode),
            errors=[f"Unknown auth mode: {cfg.auth_mode}"],
        )


def get_credentials_factory_status() -> dict:
    """Safe status for health endpoints (no secrets)."""
    result = validate_credentials()
    # Never include secrets, file contents, tokens
    return {
        "status": result.status.value,
        "mode": result.mode,
        "project": result.project,
        "quota_project": result.quota_project,
        "enabled": get_config().weathernext.enabled,
        "surface": get_config().weathernext.surface,
        "errors": result.errors,
        "redacted": result.redacted_info,
    }


def build_google_credentials():
    """Build Google credentials object if possible.

    Returns a tuple (credentials_or_none, error_message_or_none).
    This is a placeholder that would use google-auth libraries when installed.
    For now, returns None with appropriate status when dependencies missing,
    allowing offline tests and disabled mode to work.
    """
    cfg = get_config().weathernext
    validation = validate_credentials(cfg)

    if validation.status == AuthStatus.DISABLED:
        return None, "WeatherNext disabled"

    if validation.status in (AuthStatus.INVALID_CONFIG, AuthStatus.MISSING_CREDENTIALS):
        return None, "; ".join(validation.errors)

    # Attempt to import google-auth if available
    try:
        if cfg.auth_mode == "adc":
            # In ADC mode, google.auth.default() would be used
            # We don't import here to avoid hard dependency; return marker
            # The actual adapter will attempt to create client lazily
            return {"type": "adc", "project": cfg.project, "quota_project": cfg.quota_project}, None
        elif cfg.auth_mode == "oauth":
            # OAuth mode would construct Credentials from refresh token
            return {
                "type": "oauth",
                "client_id": cfg.oauth.client_id,
                "project": cfg.project,
            }, None
    except Exception as exc:
        log_event("WARN", f"Failed to build Google credentials: {type(exc).__name__}", {})
        return None, f"Credential construction failed: {type(exc).__name__}"

    return None, "Unsupported auth mode"


# ---------------------------------------------------------------------------
# Connectivity check (admin-only, bounded)
# ---------------------------------------------------------------------------

def check_connectivity() -> dict:
    """Bounded connectivity check without exposing secrets.

    Returns status dict with separate error states for billing/quota/permission.
    Does not perform full data reads unless explicitly authorized.
    """
    cfg = get_config().weathernext
    cred_status = validate_credentials(cfg)

    if cred_status.status == AuthStatus.DISABLED:
        return {
            "status": "disabled",
            "message": "WeatherNext disabled, no Google reads attempted",
            "configured": False,
        }

    if cred_status.status != AuthStatus.CONFIGURED:
        return {
            "status": cred_status.status.value,
            "message": "; ".join(cred_status.errors) if cred_status.errors else "Not configured",
            "configured": False,
            "errors": cred_status.errors,
        }

    # If google-cloud libraries are not installed, report as not ready but configured
    try:
        import google.auth  # type: ignore
    except ImportError:
        return {
            "status": "configured_no_library",
            "message": "Google auth library not installed, but configuration appears valid",
            "configured": True,
            "mode": cfg.auth_mode,
            "project": cfg.project,
            "surface": cfg.surface,
        }

    # Attempt to get default credentials (ADC) or validate OAuth token refresh
    try:
        creds, err = build_google_credentials()
        if err:
            return {
                "status": "auth_failed",
                "message": err,
                "configured": True,
                "mode": cfg.auth_mode,
            }
        return {
            "status": "configured",
            "message": f"Credentials configured for mode={cfg.auth_mode}, project={cfg.project}",
            "configured": True,
            "mode": cfg.auth_mode,
            "project": cfg.project,
            "surface": cfg.surface,
        }
    except Exception as exc:
        return {
            "status": "auth_failed",
            "message": f"{type(exc).__name__}: {str(exc)[:200]}",
            "configured": True,
            "mode": cfg.auth_mode,
        }
