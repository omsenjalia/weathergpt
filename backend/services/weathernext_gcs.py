"""WeatherNext Google Cloud Storage (Zarr) adapter.

The public WeatherNext GCS products are the no-BigQuery-cost fallback and the
only backend surface that can return raw ensemble members.  This module keeps
all optional scientific dependencies lazy: the API can boot without xarray,
zarr, gcsfs, or google-cloud-storage and returns a classified unavailable
result instead of importing a large stack on every Vercel cold start.

The adapter is intentionally injectable.  Tests can provide ``dataset_opener``
with an in-memory xarray-like object, while production uses ``xarray.open_zarr``
against an authenticated ``gcsfs`` filesystem.
"""

from __future__ import annotations

import math
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional, Sequence

from services.config import WeatherNextConfig, get_config
from services.weathernext_auth import CredentialsUnavailable, get_credentials, STORAGE_READ_SCOPES
from services.weathernext_bigquery import (
    ENSEMBLE_MEMBERS,
    PointForecastResult,
    QueryDiagnostics,
    run_id_for,
    _coerce_steps,
)


class WeatherNextGCSQueryError(RuntimeError):
    """Stable, redacted failure from a GCS/Zarr read."""

    def __init__(self, code: str, message: str, details: Optional[dict] = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


@dataclass(frozen=True)
class GCSProduct:
    model: str
    kind: str  # ensemble or statistics
    root: str
    model_version: str


BUCKETS = {
    "wn3_full": "gs://" + (os.getenv("WEATHERNEXT_GCS_BUCKET_3") or "weathernext3_spatial") + "/weathernext_3_0_0/zarr/",
    "wn3_stats": "gs://" + (os.getenv("WEATHERNEXT_GCS_STATS_3") or "weathernext3_statistics_spatial") + "/weathernext_3_0_0_statistics/zarr/",
    "wn2_full": "gs://" + (os.getenv("WEATHERNEXT_GCS_BUCKET_2") or "weathernext2_spatial") + "/",
    "wn2_mean": "gs://" + (os.getenv("WEATHERNEXT_GCS_STATS_2") or "weathernext2_statistics_spatial") + "/",
}


_MODEL_ALIASES = {
    "weathernext_3": "weathernext_3",
    "weathernext_3_0_0": "weathernext_3",
    "wn3": "weathernext_3",
    "3": "weathernext_3",
    "weathernext_2": "weathernext_2",
    "weathernext_2_0_0": "weathernext_2",
    "wn2": "weathernext_2",
    "2": "weathernext_2",
}


def normalize_model(model: str) -> str:
    normalized = (model or "weathernext_3").lower().replace("-", "_")
    if normalized not in _MODEL_ALIASES:
        raise WeatherNextGCSQueryError("unsupported_model", f"Unsupported WeatherNext model: {model}")
    return _MODEL_ALIASES[normalized]


def _product(cfg: WeatherNextConfig, model: str, kind: str) -> GCSProduct:
    model_key = normalize_model(model)
    if kind not in {"ensemble", "statistics"}:
        raise WeatherNextGCSQueryError("unsupported_surface", f"Unsupported GCS surface: {kind}")
    root = cfg.gcs.root_for(model_key, statistics=kind == "statistics")
    return GCSProduct(model_key, kind, root, "3.0.0" if model_key == "weathernext_3" else "2.0.0")


def _split_gs_uri(uri: str) -> tuple[str, str]:
    match = re.match(r"^gs://([^/]+)(?:/(.*))?$", uri.rstrip("/"))
    if not match:
        raise WeatherNextGCSQueryError("invalid_bucket", "WeatherNext GCS root must be a gs:// URI")
    return match.group(1), match.group(2) or ""


def _coord_name(dataset: Any, candidates: Sequence[str]) -> Optional[str]:
    names = set(getattr(dataset, "coords", {}) or {}) | set(getattr(dataset, "dims", {}) or {})
    return next((name for name in candidates if name in names), None)


def _select_nearest(dataset: Any, *, lat: float, lon: float, init_time: Optional[datetime]):
    """Select one point without assuming a particular Zarr dimension spelling."""
    selection: dict[str, Any] = {}
    lat_name = _coord_name(dataset, ("lat", "latitude"))
    lon_name = _coord_name(dataset, ("lon", "longitude"))
    if lat_name:
        selection[lat_name] = lat
    if lon_name:
        selection[lon_name] = lon
    time_name = _coord_name(dataset, ("init_time", "init", "time"))
    if init_time and time_name:
        selection[time_name] = init_time
    if not selection:
        return dataset
    try:
        return dataset.sel(selection, method="nearest")
    except TypeError:
        # Some xarray versions do not accept method for a mixed scalar/index
        # selection.  Select coordinates separately and retain the same point.
        selected = dataset
        for name, value in selection.items():
            try:
                selected = selected.sel({name: value}, method="nearest")
            except Exception:
                selected = selected.sel({name: value})
        return selected


def _as_values(value: Any) -> Any:
    """Convert numpy/xarray scalars and arrays to JSON-safe Python values."""
    if hasattr(value, "values"):
        value = value.values
    if hasattr(value, "tolist"):
        value = value.tolist()
    return value


class WeatherNextGCSAdapter:
    """Read WeatherNext statistics and full-member Zarr products."""

    def __init__(
        self,
        config_getter: Callable[[], Any] = get_config,
        credentials_getter: Callable[..., Any] = get_credentials,
        dataset_opener: Optional[Callable[[str, Any], Any]] = None,
    ):
        self._config_getter = config_getter
        self._credentials_getter = credentials_getter
        self._dataset_opener = dataset_opener
        self._datasets: dict[str, Any] = {}
        self._lock = threading.Lock()
        self.last_query: Optional[dict] = None
        self.last_error: Optional[dict] = None

    @property
    def cfg(self) -> WeatherNextConfig:
        return self._config_getter().weathernext

    def _open(self, product: GCSProduct):
        if not self.cfg.enabled:
            raise WeatherNextGCSQueryError("weathernext_disabled", "WeatherNext is disabled")
        key = f"{product.model}:{product.kind}:{product.root}"
        with self._lock:
            if key in self._datasets:
                return self._datasets[key]
        try:
            # Resolve credentials before opening the filesystem.  This is also
            # what turns an absent Vercel secret into live_credentials_required.
            try:
                credentials = self._credentials_getter(STORAGE_READ_SCOPES)
            except TypeError:
                # Simple zero-argument fakes are useful for offline adapter tests.
                credentials = self._credentials_getter()
        except CredentialsUnavailable as exc:
            raise WeatherNextGCSQueryError(exc.code, str(exc), {"attempts": exc.attempts}) from exc
        except Exception as exc:
            raise WeatherNextGCSQueryError("live_credentials_required", type(exc).__name__) from exc

        try:
            if self._dataset_opener:
                dataset = self._dataset_opener(product.root, credentials)
            else:
                import xarray as xr  # type: ignore
                import gcsfs  # type: ignore
                fs = gcsfs.GCSFileSystem(
                    token=credentials,
                    project=self.cfg.gcs.user_project or self.cfg.project,
                )
                path = product.root[5:] if product.root.startswith("gs://") else product.root
                dataset = xr.open_zarr(fs.get_mapper(path), consolidated=True)
        except ImportError as exc:
            raise WeatherNextGCSQueryError("missing_dependency_gcs", f"GCS/Zarr dependencies are not installed: {type(exc).__name__}") from exc
        except Exception as exc:
            message = str(exc).replace("\n", " ")[:200]
            lowered = message.lower()
            code = "permission_denied" if "permission" in lowered or "403" in lowered else "gcs_unavailable"
            raise WeatherNextGCSQueryError(code, f"Unable to open WeatherNext Zarr: {message}") from exc

        with self._lock:
            self._datasets[key] = dataset
        return dataset

    def dataset(self, model: str = "weathernext_3", kind: str = "statistics"):
        return self._open(_product(self.cfg, model, kind))

    def open_wn3_ensemble(self, init_time: Optional[datetime] = None):
        return self.dataset("weathernext_3", "ensemble")

    def open_wn3_stats(self, init_time: Optional[datetime] = None):
        return self.dataset("weathernext_3", "statistics")

    def open_wn2_ensemble(self, init_time: Optional[datetime] = None):
        return self.dataset("weathernext_2", "ensemble")

    def open_wn2_mean(self, init_time: Optional[datetime] = None):
        return self.dataset("weathernext_2", "statistics")

    def _point_payload(self, dataset: Any, *, product: GCSProduct, lat: float, lon: float,
                       variable: str, init_time: Optional[datetime] = None,
                       statistic: str = "mean", max_steps: int = 168,
                       max_members: int = ENSEMBLE_MEMBERS) -> dict:
        selected = _select_nearest(dataset, lat=lat, lon=lon, init_time=init_time)
        variables = getattr(selected, "data_vars", {}) or {}
        if variable not in variables:
            # Some products use a statistic suffix as separate variables.
            candidates = [f"{variable}_{statistic}", variable]
            variable_name = next((name for name in candidates if name in variables), None)
            if variable_name is None:
                raise WeatherNextGCSQueryError("variable_not_found", f"Variable {variable} is not available in the WeatherNext Zarr product")
        else:
            variable_name = variable

        data = variables[variable_name]
        values = _as_values(data)
        dims = tuple(getattr(data, "dims", ()) or ())
        coords = getattr(data, "coords", {}) or {}
        member_dim = next((d for d in dims if d in {"member", "ensemble_member", "realization"}), None)
        time_dim = next((d for d in dims if d in {"time", "valid_time", "forecast_time"}), None)
        statistic_dim = next((d for d in dims if d in {"statistic", "statistics", "quantile", "quantiles"}), None)
        init_name = _coord_name(selected, ("init_time", "init"))
        init_value = _as_values(coords[init_name]) if init_name and init_name in coords else None
        if isinstance(init_value, list) and init_value:
            init_value = init_value[0]
        if member_dim:
            # Preserve member trajectories, bounded to 64 x 168.
            member_values = _as_values(data.isel({member_dim: slice(0, max_members)}))
            if hasattr(member_values, "tolist"):
                member_values = member_values.tolist()
            members = min(max_members, len(member_values)) if isinstance(member_values, list) else max_members
            return {
                "model": product.model,
                "model_version": product.model_version,
                "surface": f"gcs_{product.kind}",
                "bucket": _split_gs_uri(product.root)[0],
                "root": product.root,
                "variable": variable,
                "units": str(getattr(data, "attrs", {}).get("units", "native")),
                "run_id": run_id_for(init_time, "weathernext_2_0_0" if product.model == "weathernext_2" else "weathernext_3_0_0") if init_time else None,
                "init_time": init_value,
                "members": members,
                "member_values": member_values,
                "statistics": [],
            }

        # Statistics products generally have a time axis and one value per
        # statistic.  Convert that representation to the native step records
        # consumed by the shared normalizer.
        if time_dim:
            time_values = _as_values(coords[time_dim]) if time_dim in coords else []
            if not isinstance(time_values, list):
                time_values = [time_values]
            time_values = time_values[:max_steps]
            stat_labels = []
            if statistic_dim and statistic_dim in coords:
                raw_labels = _as_values(coords[statistic_dim])
                stat_labels = raw_labels if isinstance(raw_labels, list) else [raw_labels]
            def _label(value: Any) -> str:
                text = str(value).lower()
                if text in {"mean", "avg", "average"}:
                    return "mean"
                try:
                    number = float(value)
                    if 0 <= number <= 1:
                        number *= 100
                    return f"p{int(number)}"
                except (TypeError, ValueError):
                    return text.replace("%", "")
            step_values: list[dict] = []
            for index in range(len(time_values)):
                row: dict[str, Any] = {}
                at_time = data.isel({time_dim: index})
                if statistic_dim:
                    for stat_index, label in enumerate(stat_labels):
                        try:
                            row[f"{variable}_{_label(label)}"] = _as_values(at_time.isel({statistic_dim: stat_index}))
                        except Exception:
                            continue
                else:
                    row[f"{variable}_{statistic}"] = _as_values(at_time)
                step_values.append(row)
            values = step_values
        elif isinstance(values, list):
            values = values[:max_steps]
        return {
            "model": product.model,
            "model_version": product.model_version,
            "surface": f"gcs_{product.kind}",
            "bucket": _split_gs_uri(product.root)[0],
            "root": product.root,
            "variable": variable,
            "units": str(getattr(data, "attrs", {}).get("units", "native")),
            "run_id": run_id_for(init_time, "weathernext_2_0_0" if product.model == "weathernext_2" else "weathernext_3_0_0") if init_time else None,
            "init_time": init_value,
            "members": ENSEMBLE_MEMBERS,
            "statistics": list({split.rsplit("_", 1)[-1] for row in values if isinstance(row, dict) for split in row if split.startswith(variable + "_")}) or [statistic],
            "values": values,
            "time_coordinates": _as_values(coords[time_dim]) if time_dim and time_dim in coords else [],
        }

    def query_point(self, lat: float, lon: float, *, variable: str = "temperature_2m",
                    model: str = "weathernext_3", kind: str = "statistics",
                    init_time: Optional[datetime] = None, statistic: str = "mean") -> dict:
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise WeatherNextGCSQueryError("invalid_coordinates", "lat/lon out of range")
        product = _product(self.cfg, model, kind)
        result = self._point_payload(self._open(product), product=product, lat=lat, lon=lon,
                                     variable=variable, init_time=init_time, statistic=statistic)
        self.last_query = {"model": product.model, "kind": kind, "variable": variable,
                           "lat": lat, "lon": lon, "bucket": result.get("bucket")}
        return result

    def fetch_point_forecast(self, lat: float, lon: float, *, model: str = "weathernext_3",
                             horizon_hours: int = 72, run_id: Optional[str] = None) -> PointForecastResult:
        """Return a normalized-adapter-compatible result for the statistics Zarr.

        Zarr layouts differ slightly between releases.  The canonical layout is
        converted to the same native-unit step records as BigQuery so the
        normalization/science layer has one code path.
        """
        from services.weathernext_bigquery import parse_run_id, resolution_for_table
        product = _product(self.cfg, model, "statistics")
        init_time = parse_run_id(run_id) if run_id else None
        payload = self.query_point(lat, lon, model=model, kind="statistics", init_time=init_time)
        if not init_time and payload.get("init_time"):
            candidate_init = payload.get("init_time")
            if isinstance(candidate_init, str):
                try:
                    init_time = datetime.fromisoformat(candidate_init.replace("Z", "+00:00"))
                except ValueError:
                    init_time = None
        if not payload.get("values"):
            raise WeatherNextGCSQueryError("no_recent_run", "WeatherNext statistics Zarr returned no point values")
        times = payload.get("time_coordinates") or []
        raw_values = payload["values"]
        if not isinstance(raw_values, list):
            raw_values = [raw_values]
        steps = []
        for index, value in enumerate(raw_values[:max(1, min(horizon_hours, 360))]):
            if isinstance(value, dict):
                step = dict(value)
            else:
                step = {"temperature_2m_mean": value} if "temperature" in payload["variable"] else {f"{payload['variable']}_mean": value}
            t = times[index] if index < len(times) else None
            if isinstance(t, str):
                try:
                    t = datetime.fromisoformat(t.replace("Z", "+00:00"))
                except ValueError:
                    t = None
            if not isinstance(t, datetime):
                t = (init_time or datetime.now(timezone.utc))
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            step["time"] = t.astimezone(timezone.utc)
            steps.append(step)
        steps = _coerce_steps(steps)
        if not steps:
            raise WeatherNextGCSQueryError("no_recent_run", "WeatherNext statistics Zarr returned no usable steps")
        diagnostics = QueryDiagnostics(rows=1, dry_run=False)
        return PointForecastResult(
            table=product.root,
            init_time=init_time or steps[0]["time"],
            horizon_hours=min(horizon_hours, len(steps)),
            run_horizon_hours=min(horizon_hours, len(steps)),
            cell_lat=lat,
            cell_lon=lon,
            distance_km=0.0,
            resolution_deg=0.1 if product.model == "weathernext_3" else 0.1,
            columns=tuple(k for k in steps[0] if k != "time"),
            steps=steps,
            diagnostics=diagnostics,
            attempted_inits=[],
            credential_source="service_account_json",
            model_id=f"{product.model}_0_0",
            model_version=product.model_version,
            surface=f"gcs_{product.kind}",
        )

    def query_ensemble(self, lat: float, lon: float, *, variable: str = "temperature_2m",
                       model: str = "weathernext_3", run_id: str = "") -> dict:
        from services.weathernext_bigquery import parse_run_id
        init = parse_run_id(run_id) if run_id else None
        return self.query_point(lat, lon, variable=variable, model=model, kind="ensemble", init_time=init)

    def query_profile(self, lat: float, lon: float, *, variables: Sequence[str], levels: Sequence[int],
                      model: str = "weathernext_3", run_id: str = "") -> dict:
        """Read bounded upper-air fields from the full Zarr product."""
        from services.weathernext_bigquery import parse_run_id
        init = parse_run_id(run_id) if run_id else None
        product = _product(self.cfg, model, "ensemble")
        selected = _select_nearest(self._open(product), lat=lat, lon=lon, init_time=init)
        data_vars = getattr(selected, "data_vars", {}) or {}
        profile: list[dict] = []
        for level in levels:
            row: dict[str, Any] = {"level_hpa": level}
            for variable in variables:
                names = (f"{variable}_{level}", f"{variable}_{level}hPa", f"{variable}_at_{level}")
                name = next((candidate for candidate in names if candidate in data_vars), None)
                if name is None:
                    raise WeatherNextGCSQueryError("variable_not_found", f"Profile field {variable} at {level} hPa is not available")
                value = _as_values(data_vars[name])
                if isinstance(value, list):
                    value = value[:ENSEMBLE_MEMBERS]
                row[variable] = value
            profile.append(row)
        return {"model": product.model, "model_version": product.model_version,
                "surface": "gcs_ensemble", "bucket": _split_gs_uri(product.root)[0],
                "run_id": run_id or None, "profile": profile,
                "variables": list(variables), "levels": list(levels)}

    def stats(self) -> dict:
        cfg = self.cfg
        return {
            "enabled": cfg.enabled,
            "datasets_open": len(self._datasets),
            "roots": {"wn3_full": cfg.gcs.ensemble_root, "wn3_stats": cfg.gcs.statistics_root,
                      "wn2_full": cfg.gcs.wn2_ensemble_root, "wn2_stats": cfg.gcs.wn2_statistics_root},
            "last_query": self.last_query,
            "last_error": self.last_error,
        }


_adapter: Optional[WeatherNextGCSAdapter] = None
_adapter_lock = threading.Lock()


def get_gcs_adapter() -> WeatherNextGCSAdapter:
    global _adapter
    with _adapter_lock:
        if _adapter is None:
            _adapter = WeatherNextGCSAdapter()
        return _adapter


def set_gcs_adapter(adapter: Optional[WeatherNextGCSAdapter]) -> None:
    global _adapter
    with _adapter_lock:
        _adapter = adapter


# Plan-compatible convenience functions.  They intentionally return the
# adapter's structured payload/dataset rather than inventing values when the
# optional Zarr stack or entitlement is missing.
def open_wn3_ensemble(init_time: Optional[datetime] = None):
    return get_gcs_adapter().open_wn3_ensemble(init_time)


def open_wn3_stats(init_time: Optional[datetime] = None):
    return get_gcs_adapter().open_wn3_stats(init_time)


def open_wn2_mean(init_time: Optional[datetime] = None):
    return get_gcs_adapter().open_wn2_mean(init_time)
