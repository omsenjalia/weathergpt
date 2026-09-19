"""Earth Engine adapter for WeatherNext map tiles.

Earth Engine is used for map display only; point forecasts never fall back to
an EE image export.  All imports and network calls are lazy so deployments
without EE access retain the rest of the weather API.
"""

from __future__ import annotations

import re
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from services.config import WeatherNextConfig, get_config
from services.weathernext_auth import CredentialsUnavailable, get_ee_credentials

WN3_EE_01 = "projects/gcp-public-data-weathernext/assets/weathernext_3_0_0_0p1deg"
WN3_EE_005 = "projects/gcp-public-data-weathernext/assets/weathernext_3_0_0_0p05deg"
# The exact WN2 asset can be overridden because Analytics Hub/EE grants may use
# a project-local alias.  Keeping a documented default makes the route usable
# without hard-coding a user's private project.
WN2_EE_DEFAULT = "projects/gcp-public-data-weathernext/assets/weathernext_2_0_0_0p1deg"


class WeatherNextEEError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def asset_for_model(model: str = "weathernext_3", high_resolution: bool = False) -> str:
    normalized = (model or "weathernext_3").lower().replace("-", "_")
    if normalized in {"weathernext_3", "weathernext_3_0_0", "wn3", "3"}:
        return WN3_EE_005 if high_resolution else WN3_EE_01
    if normalized in {"weathernext_2", "weathernext_2_0_0", "wn2", "2"}:
        return WN2_EE_DEFAULT
    raise WeatherNextEEError("unsupported_model", f"Unsupported WeatherNext Earth Engine model: {model}")


def _safe_tile_url(url: str) -> str:
    # EE returns a URL containing a token.  It is safe to hand it to the
    # backend proxy, but never log the full URL or return it as health data.
    if not isinstance(url, str) or not url.startswith(("https://", "http://")):
        raise WeatherNextEEError("invalid_tile_url", "Earth Engine did not return a tile URL")
    return url


class WeatherNextEEAdapter:
    def __init__(self, config_getter: Callable[[], Any] = get_config,
                 credentials_getter: Callable[[], Any] = get_ee_credentials,
                 ee_module: Any = None):
        self._config_getter = config_getter
        self._credentials_getter = credentials_getter
        self._ee = ee_module
        self._initialized = False
        self._lock = threading.Lock()
        self.last_layer: Optional[dict] = None
        self.last_error: Optional[dict] = None

    @property
    def cfg(self) -> WeatherNextConfig:
        return self._config_getter().weathernext

    def _module(self):
        if self._ee is None:
            try:
                import ee  # type: ignore
            except ImportError as exc:
                raise WeatherNextEEError("missing_dependency_earth_engine", "earthengine-api is not installed") from exc
            self._ee = ee
        return self._ee

    def init_ee(self):
        if not self.cfg.enabled:
            raise WeatherNextEEError("weathernext_disabled", "WeatherNext is disabled")
        with self._lock:
            if self._initialized:
                return self._ee
            try:
                credentials = self._credentials_getter()
                ee = self._module()
                ee.Initialize(credentials=credentials, project=self.cfg.ee_project or self.cfg.project)
                self._initialized = True
                return ee
            except CredentialsUnavailable as exc:
                raise WeatherNextEEError(exc.code, str(exc)) from exc
            except WeatherNextEEError:
                raise
            except Exception as exc:
                message = str(exc).replace("\n", " ")[:200]
                raise WeatherNextEEError("earth_engine_unavailable", message) from exc

    def get_tile_url(self, variable: str, run_id: str = "", *, model: str = "weathernext_3",
                     high_resolution: bool = False, statistic: str = "mean") -> str:
        if not variable or not re.match(r"^[a-zA-Z0-9_]+$", variable):
            raise WeatherNextEEError("invalid_variable", "Invalid Earth Engine variable")
        ee = self.init_ee()
        asset = asset_for_model(model, high_resolution)
        try:
            collection = ee.ImageCollection(asset)
            if run_id:
                # WeatherNext assets expose run metadata as system:index in the
                # public collection.  If a release uses a different property,
                # the collection's normal first image remains the honest error.
                filtered = collection.filter(ee.Filter.eq("system:index", run_id))
                image = filtered.first()
            else:
                image = collection.sort("system:time_start", False).first()
            if image is None:
                raise WeatherNextEEError("run_not_available", "No Earth Engine image matched the requested run")
            image = image.select([variable])
            map_id = image.getMapId({"bands": [variable], "format": "png"})
            fetcher = map_id.get("tile_fetcher") if isinstance(map_id, dict) else getattr(map_id, "tile_fetcher", None)
            url = getattr(fetcher, "url_format", None) if fetcher is not None else None
            if not url and isinstance(map_id, dict):
                url = map_id.get("url_format")
            url = _safe_tile_url(url)
            self.last_layer = {"variable": variable, "run_id": run_id, "model": model,
                               "asset": asset, "statistic": statistic}
            return url
        except WeatherNextEEError:
            raise
        except Exception as exc:
            message = str(exc).replace("\n", " ")[:200]
            code = "run_not_available" if "empty" in message.lower() else "earth_engine_error"
            raise WeatherNextEEError(code, message) from exc

    def get_tile(self, variable: str, run_id: str, z: int, x: int, y: int, **kwargs) -> bytes:
        if not (0 <= z <= 24):
            raise WeatherNextEEError("invalid_tile", "zoom must be between 0 and 24")
        limit = 1 << z
        if not (0 <= x < limit and 0 <= y < limit):
            raise WeatherNextEEError("invalid_tile", "tile coordinates are outside the zoom range")
        template = self.get_tile_url(variable, run_id, **kwargs)
        url = template.replace("{z}", str(z)).replace("{x}", str(x)).replace("{y}", str(y))
        try:
            import httpx
            response = httpx.get(url, timeout=15.0)
            response.raise_for_status()
            return response.content
        except WeatherNextEEError:
            raise
        except Exception as exc:
            raise WeatherNextEEError("tile_fetch_failed", type(exc).__name__) from exc

    def health(self) -> dict:
        return {
            "enabled": self.cfg.enabled,
            "configured": bool(self.cfg.ee_project or self.cfg.project),
            "initialized": self._initialized,
            "last_layer": self.last_layer,
        }


_adapter: Optional[WeatherNextEEAdapter] = None
_adapter_lock = threading.Lock()


def get_ee_adapter() -> WeatherNextEEAdapter:
    global _adapter
    with _adapter_lock:
        if _adapter is None:
            _adapter = WeatherNextEEAdapter()
        return _adapter


def set_ee_adapter(adapter: Optional[WeatherNextEEAdapter]) -> None:
    global _adapter
    with _adapter_lock:
        _adapter = adapter


def init_ee():
    return get_ee_adapter().init_ee()


def get_tile_url(variable: str, run_id: str = "", col_name: str = "", **kwargs) -> str:
    # ``col_name`` is accepted for compatibility with the plan; model aliases
    # are preferred because they prevent arbitrary asset access.
    model = kwargs.pop("model", "weathernext_3")
    if "weathernext_2" in col_name:
        model = "weathernext_2"
    return get_ee_adapter().get_tile_url(variable, run_id, model=model, **kwargs)
