"""Shared request validation for the routers."""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException

from weathergpt.config import MODES, normalize_wn_model
from weathergpt.weather.service import InvalidSource, normalize_source


def resolve_mode(mode: Optional[str], farmer_mode: Optional[bool] = None, default: str = "everyone") -> str:
    """Explicit ``mode`` wins; unknown values are rejected (never escalated); legacy farmer_mode maps to farmer."""
    if mode is not None and str(mode).strip():
        m = str(mode).strip().lower()
        if m not in MODES:
            raise HTTPException(status_code=400, detail=f"mode must be one of {'|'.join(MODES)}")
        return m
    return "farmer" if farmer_mode else default


def resolve_source(*values: Optional[str]) -> str:
    chosen = next((v for v in values if v and str(v).strip()), "auto")
    try:
        return normalize_source(chosen)
    except InvalidSource as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def resolve_model(model: Optional[str]) -> str:
    try:
        return normalize_wn_model(model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
