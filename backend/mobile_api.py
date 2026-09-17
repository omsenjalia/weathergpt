"""Backwards-compatibility shim — the mobile routes now live in `routers/mobile.py`."""

from routers.mobile import router  # noqa: F401

__all__ = ["router"]
