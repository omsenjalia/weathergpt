"""Bounded BigQuery point-forecast adapter for WeatherNext 3 surface tables.

Table contract (developers.google.com/weathernext/guides/bigquery):

    weathernext_3_0_0_0p1deg   0.1 deg grid, 19 surface variables x 6 statistics
    weathernext_3_0_0_0p05deg  0.05 deg station-head 2 m temperature / dew point

    init_time          TIMESTAMP  partition key (always filtered - never a full scan)
    geography          GEOGRAPHY  cell centre, clustering column (ST_DWITHIN prunes blocks)
    geography_polygon  GEOGRAPHY  cell footprint
    forecast           REPEATED RECORD {time, hours, <variable>_{mean,p10,p25,p50,p75,p90}}

Cost rules implemented here:
- exact ``init_time = @init_time`` partition filter on every query
- explicit leaf columns only (never ``SELECT *`` / never the whole ``forecast`` record)
- spatial predicate on the *clustered* ``geography`` column
- ``maximum_bytes_billed`` on every job (fails without charge when exceeded)
- bounded wait with job cancellation on timeout
- per-process diagnostics (bytes billed / processed, cache hit, job id)

Run selection: WeatherNext 3 initialises hourly; only 00/06/12/18 UTC runs carry
the 15-day horizon and runs appear on BigQuery ~7 h after init. We try the
newest expected run first and step back through older runs when a partition is
not there yet (an empty partition costs nothing).
"""

from __future__ import annotations

import concurrent.futures
import math
import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from services.config import AppConfig, WeatherNextConfig, get_config
from services.weathernext_auth import CredentialBundle, CredentialsUnavailable, get_bigquery_credentials
from state import log_event

MODEL_ID = "weathernext_3_0_0"
MODEL_VERSION = "3.0.0"
ENSEMBLE_MEMBERS = 64
INTERIM_RUN_HORIZON_HOURS = 48

# Public aliases from the deployment plan.  Runtime configuration is resolved
# through ``get_config().weathernext.bq.table_for`` so tests and serverless
# instances can change env vars without re-importing this module.
# NOTE: the WN2 Analytics Hub tables are ``weathernext_2_0_0`` (forecasts) and
# ``weathernext_2_0_0_mean`` (mean forecasts) - there is no WN2 0.1 deg table,
# and WN2 leaves use ERA5-style names (``2m_temperature``), not the WN3
# ``temperature_2m_*`` vocabulary.
TABLES = {
    "wn3_0p1": os.getenv("WEATHERNEXT_TABLE_3") or os.getenv("WEATHERNEXT_TABLE") or "cool-archery-296710.weathernext.weathernext_3_0_0_0p1deg",
    "wn3_0p05": os.getenv("WEATHERNEXT_TABLE_3_HR") or "cool-archery-296710.weathernext.weathernext_3_0_0_0p05deg",
    "wn2": os.getenv("WEATHERNEXT_TABLE_2") or "cool-archery-296710.weathernext.weathernext_2_0_0",
    "wn2_mean": os.getenv("WEATHERNEXT_TABLE_2_MEAN") or "cool-archery-296710.weathernext.weathernext_2_0_0_mean",
}

_TABLE_RE = re.compile(r"^[A-Za-z0-9_\-]+\.[A-Za-z0-9_]+\.[A-Za-z0-9_]+$")
# Leaf identifiers are lowercase alphanumerics/underscores. A leading digit is
# allowed because WN2 uses ERA5-style names (`2m_temperature`); those leaves are
# backticked in the generated SQL. Anything else (spaces, quotes, semicolons)
# is rejected before it can reach BigQuery.
_COLUMN_RE = re.compile(r"^[a-z0-9][a-z0-9_]*$")
_RUN_ID_RE = re.compile(r"(\d{4})(\d{2})(\d{2})(\d{2})$")


class WeatherNextQueryError(RuntimeError):
    """A bounded, classified failure of the BigQuery surface.

    ``code`` is a stable machine-readable reason that ends up in
    ``fallback_reasons`` (never secret material)."""

    def __init__(self, code: str, message: str, details: Optional[dict] = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


@dataclass
class QueryDiagnostics:
    job_id: Optional[str] = None
    cache_hit: Optional[bool] = None
    total_bytes_processed: Optional[int] = None
    total_bytes_billed: Optional[int] = None
    slot_millis: Optional[int] = None
    duration_ms: Optional[float] = None
    dry_run: bool = False
    rows: int = 0

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "cache_hit": self.cache_hit,
            "total_bytes_processed": self.total_bytes_processed,
            "total_bytes_billed": self.total_bytes_billed,
            "slot_millis": self.slot_millis,
            "duration_ms": round(self.duration_ms, 1) if self.duration_ms is not None else None,
            "dry_run": self.dry_run,
            "rows": self.rows,
        }


@dataclass
class PointForecastResult:
    """Raw (native-unit) point extraction for one run and one grid cell."""
    table: str
    init_time: datetime
    horizon_hours: int              # horizon requested/allowed for this run
    run_horizon_hours: int          # 360 for synoptic runs, 48 for interim
    cell_lat: float
    cell_lon: float
    distance_km: float
    resolution_deg: float
    columns: tuple[str, ...]
    steps: list[dict]               # [{"time": datetime, "<column>": float, ...}] sorted by time
    diagnostics: QueryDiagnostics
    attempted_inits: list[str] = field(default_factory=list)
    credential_source: Optional[str] = None
    # Surface/model metadata is kept on the raw result so normalization can
    # preserve provenance for WN2, WN3, BigQuery, and GCS uniformly.
    model_id: str = MODEL_ID
    model_version: str = MODEL_VERSION
    surface: str = "bigquery"

    @property
    def run_id(self) -> str:
        return run_id_for(self.init_time, self.model_id)


def run_id_for(init_time: datetime, model: str = "weathernext_3_0_0") -> str:
    return f"{model}_{init_time.astimezone(timezone.utc):%Y%m%d%H}"


def parse_run_id(run_id: str) -> Optional[datetime]:
    """Accept ``weathernext_3_0_0_2026091900``, ``2026091900`` or ISO-8601."""
    if not run_id:
        return None
    text = run_id.strip()
    m = _RUN_ID_RE.search(text)
    if m and (text.startswith("weathernext_3_0_0") or text.startswith("weathernext_2_0_0") or text.isdigit()):
        y, mo, d, h = (int(g) for g in m.groups())
        try:
            return datetime(y, mo, d, h, tzinfo=timezone.utc)
        except ValueError:
            return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


def resolution_for_table(table: str) -> float:
    return 0.05 if "0p05" in table else 0.1


def run_horizon_hours(init_time: datetime, max_horizon: int) -> int:
    """Synoptic (00/06/12/18 UTC) runs carry the full horizon; interim runs 48 h."""
    return max_horizon if init_time.hour % 6 == 0 else INTERIM_RUN_HORIZON_HOURS


def candidate_init_times(
    now: datetime,
    policy_run_hours: tuple[int, ...],
    delivery_latency_hours: float,
    max_attempts: int,
    horizon_hours: int,
    max_horizon: int,
    run_id: Optional[str] = None,
    freshness_hours: Optional[float] = None,
) -> list[datetime]:
    """Newest-first list of init times worth querying for ``horizon_hours``."""
    if run_id:
        pinned = parse_run_id(run_id)
        if pinned is None:
            raise WeatherNextQueryError("invalid_run_id", f"Unrecognised run_id '{run_id[:40]}'")
        return [pinned]

    latest_allowed = (now - timedelta(hours=delivery_latency_hours)).astimezone(timezone.utc)
    t = latest_allowed.replace(minute=0, second=0, microsecond=0)
    # Never look further back than 3 days, and never past the *expiry* horizon
    # (2x the freshness budget): a run older than that is expired and cannot be
    # served even with allow_stale, so querying its partition only burns a
    # BigQuery job that the freshness gate is guaranteed to reject.
    lookback_hours = 72.0
    if freshness_hours and freshness_hours > 0:
        lookback_hours = min(lookback_hours, 2.0 * float(freshness_hours))
    floor = now - timedelta(hours=lookback_hours)
    out: list[datetime] = []
    while len(out) < max_attempts and t >= floor:
        if t.hour in policy_run_hours and run_horizon_hours(t, max_horizon) >= min(horizon_hours, max_horizon):
            out.append(t)
        t -= timedelta(hours=1)
    return out


def build_point_query(
    table: str,
    columns: tuple[str, ...],
    lat: float,
    lon: float,
    init_time: datetime,
    horizon_hours: int,
    radius_km: float,
) -> tuple[str, list]:
    """Return ``(sql, query_parameters)`` for a bounded nearest-cell extraction.

    Pure function so tests can assert the cost rules without a client.
    """
    if not _TABLE_RE.match(table):
        raise WeatherNextQueryError("invalid_table", "WEATHERNEXT_BQ_SURFACE_TABLE must be project.dataset.table")
    bad = [c for c in columns if not _COLUMN_RE.match(c)]
    if bad or not columns:
        raise WeatherNextQueryError("invalid_columns", f"Invalid column names: {bad[:3]}")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise WeatherNextQueryError("invalid_coordinates", "lat/lon out of range")

    init_utc = init_time.astimezone(timezone.utc)
    max_time = init_utc + timedelta(hours=int(horizon_hours))

    def _leaf(col: str) -> str:
        # WN2's ERA5-style names start with a digit (`2m_temperature`) and must
        # be backticked in BigQuery SQL; WN3 names are emitted bare so query
        # plans (and tests asserting `f.temperature_2m_mean`) stay readable.
        return f"f.`{col}`" if col[0].isdigit() else f"f.{col}"

    leaf_select = ",\n            ".join(_leaf(c) for c in columns)
    sql = f"""
        SELECT
          ST_Y(t.geography) AS cell_lat,
          ST_X(t.geography) AS cell_lon,
          ST_DISTANCE(t.geography, ST_GEOGPOINT(@lon, @lat)) AS distance_m,
          ARRAY(
            SELECT AS STRUCT
              f.time,
              {leaf_select}
            FROM UNNEST(t.forecast) AS f
            WHERE f.time > @init_time AND f.time <= @max_time
            ORDER BY f.time
          ) AS steps
        FROM `{table}` AS t
        WHERE t.init_time = @init_time
          AND ST_DWITHIN(t.geography, ST_GEOGPOINT(@lon, @lat), @radius_m)
        ORDER BY distance_m ASC
        LIMIT 1
    """
    # Plain tuples keep this function importable/testable without google libs;
    # ``_job_config`` converts them to ScalarQueryParameter.
    params: list[tuple[str, str, Any]] = [
        ("lat", "FLOAT64", float(lat)),
        ("lon", "FLOAT64", float(lon)),
        ("init_time", "TIMESTAMP", init_utc),
        ("max_time", "TIMESTAMP", max_time),
        ("radius_m", "FLOAT64", float(radius_km) * 1000.0),
    ]
    return sql, params


def _extract_required_bytes(message: str) -> Optional[int]:
    # "Query exceeded limit for bytes billed: 1000000. 10485760 or higher required."
    m = re.search(r"(\d+) or higher required", message)
    return int(m.group(1)) if m else None


def classify_bigquery_exception(exc: BaseException) -> WeatherNextQueryError:
    """Map google exceptions to stable reason codes (no secrets)."""
    if isinstance(exc, WeatherNextQueryError):
        return exc
    if isinstance(exc, CredentialsUnavailable):
        return WeatherNextQueryError(exc.code, str(exc), {"attempts": exc.attempts})

    name = type(exc).__name__
    message = str(exc).replace("\n", " ")
    short = f"{name}: {message[:200]}"
    lowered = message.lower()

    try:
        from google.api_core import exceptions as gexc  # type: ignore
    except ImportError:  # pragma: no cover
        gexc = None
    try:
        from google.auth.exceptions import RefreshError, TransportError  # type: ignore
    except ImportError:  # pragma: no cover
        RefreshError = TransportError = ()  # type: ignore

    if RefreshError and isinstance(exc, RefreshError):
        return WeatherNextQueryError("credential_refresh_failed", short)
    if isinstance(exc, (concurrent.futures.TimeoutError, TimeoutError)):
        return WeatherNextQueryError("query_timeout", short)

    if gexc is not None:
        if isinstance(exc, gexc.Forbidden):
            if "billing" in lowered:
                return WeatherNextQueryError("billing_disabled", short)
            if "quota" in lowered or "rate" in lowered:
                return WeatherNextQueryError("quota_exceeded", short)
            return WeatherNextQueryError("permission_denied", short)
        if isinstance(exc, gexc.Unauthorized):
            return WeatherNextQueryError("unauthenticated", short)
        if isinstance(exc, gexc.NotFound):
            return WeatherNextQueryError("table_not_found", short)
        if isinstance(exc, gexc.BadRequest):
            if "bytes billed" in lowered or "bytesbilledlimitexceeded" in lowered:
                return WeatherNextQueryError(
                    "bytes_billed_limit_exceeded", short,
                    {"required_bytes": _extract_required_bytes(message)},
                )
            if "unrecognized name" in lowered or "field name" in lowered or "not found inside" in lowered:
                return WeatherNextQueryError("schema_mismatch", short)
            if "partition" in lowered:
                return WeatherNextQueryError("partition_filter_required", short)
            return WeatherNextQueryError("bad_request", short)
        if isinstance(exc, (gexc.TooManyRequests, gexc.ResourceExhausted)):
            return WeatherNextQueryError("quota_exceeded", short)
        if isinstance(exc, gexc.DeadlineExceeded):
            return WeatherNextQueryError("query_timeout", short)
        if isinstance(exc, (gexc.ServiceUnavailable, gexc.InternalServerError, gexc.BadGateway)):
            return WeatherNextQueryError("bigquery_unavailable", short)
        if isinstance(exc, gexc.GoogleAPICallError):
            return WeatherNextQueryError("bigquery_error", short)
    if TransportError and isinstance(exc, TransportError):
        return WeatherNextQueryError("network_error", short)
    return WeatherNextQueryError("query_failed", short)


class WeatherNextBigQueryAdapter:
    """Thread-safe adapter with a cached client and bounded point queries.

    ``client_factory`` / ``credentials_getter`` are injectable for tests.
    """

    def __init__(
        self,
        config_getter: Callable[[], AppConfig] = get_config,
        credentials_getter: Callable[..., CredentialBundle] = get_bigquery_credentials,
        client_factory: Optional[Callable[[CredentialBundle, WeatherNextConfig], Any]] = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self._config_getter = config_getter
        self._credentials_getter = credentials_getter
        self._client_factory = client_factory
        self._clock = clock
        self._client = None
        self._client_source: Optional[str] = None
        self._lock = threading.Lock()
        self.query_count = 0
        self.bytes_billed_total = 0
        self.last_query: Optional[dict] = None
        self.last_error: Optional[dict] = None

    # -- client -------------------------------------------------------------

    @property
    def cfg(self) -> WeatherNextConfig:
        return self._config_getter().weathernext

    def reset_client(self) -> None:
        with self._lock:
            self._client = None
            self._client_source = None

    def now(self) -> datetime:
        """Current time on the adapter's (injectable) clock.

        Callers that classify freshness for a result this adapter produced must
        use the same clock that selected the run - otherwise run selection and
        freshness judgement disagree whenever the clock is injected (tests) and
        drift by the query duration in production.
        """
        return self._clock()

    def get_client(self):
        """Build (once) a BigQuery client from the credential chain."""
        with self._lock:
            if self._client is not None:
                return self._client
            cfg = self.cfg
            if not cfg.enabled:
                raise CredentialsUnavailable("WeatherNext disabled")
            bundle = self._credentials_getter(cfg)  # raises CredentialsUnavailable
            if self._client_factory is not None:
                client = self._client_factory(bundle, cfg)
            else:
                try:
                    from google.cloud import bigquery  # type: ignore
                except ImportError as exc:
                    raise WeatherNextQueryError("missing_dependency_bigquery", f"google-cloud-bigquery not installed: {exc}")
                client = bigquery.Client(
                    project=bundle.project,
                    credentials=bundle.credentials,
                    location=cfg.bq.location,
                )
            self._client = client
            self._client_source = bundle.source
            return client

    # -- queries ------------------------------------------------------------

    def _job_config(self, params: list, dry_run: bool):
        from google.cloud import bigquery  # type: ignore

        cfg = self.cfg
        # A dry run is the cost-inspection path.  BigQuery applies
        # ``maximum_bytes_billed`` to dry runs too, so putting the production
        # cap on the estimate query makes the diagnostic fail with the same
        # "N or higher required" error it is supposed to explain.  Dry runs do
        # not bill bytes; leave the cap unset and compare the returned estimate
        # with the configured cap in ``estimate_point_query`` instead.
        maximum_bytes_billed = None if dry_run else int(cfg.bq.max_bytes_billed)
        job_config = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter(name, kind, value) for name, kind, value in params],
            maximum_bytes_billed=maximum_bytes_billed,
            use_query_cache=True,
            use_legacy_sql=False,
            dry_run=dry_run,
            labels={"app": "weathergpt", "component": "weathernext", "kind": "point"},
        )
        # Server-side job timeout (supported by google-cloud-bigquery >= 3.13).
        try:
            job_config.job_timeout_ms = int(cfg.bq.query_timeout_seconds * 1000)
        except Exception:  # pragma: no cover - older client versions
            pass
        return job_config

    def run_query(self, sql: str, params: list, *, dry_run: bool = False) -> tuple[list[dict], QueryDiagnostics]:
        """Execute one bounded job. Returns ``(rows, diagnostics)``; raises WeatherNextQueryError."""
        cfg = self.cfg
        started = time.perf_counter()
        diag = QueryDiagnostics(dry_run=dry_run)
        job = None
        try:
            client = self.get_client()
            job = client.query(sql, job_config=self._job_config(params, dry_run), location=cfg.bq.location)
            diag.job_id = getattr(job, "job_id", None)
            if dry_run:
                diag.total_bytes_processed = getattr(job, "total_bytes_processed", None)
                diag.duration_ms = (time.perf_counter() - started) * 1000
                self.last_query = {"dry_run": True, **diag.to_dict()}
                return [], diag
            rows_iter = job.result(timeout=cfg.bq.query_timeout_seconds)
            rows = [dict(r) for r in rows_iter]
            diag.rows = len(rows)
            diag.cache_hit = getattr(job, "cache_hit", None)
            diag.total_bytes_processed = getattr(job, "total_bytes_processed", None)
            diag.total_bytes_billed = getattr(job, "total_bytes_billed", None)
            diag.slot_millis = getattr(job, "slot_millis", None)
            diag.duration_ms = (time.perf_counter() - started) * 1000
            self.query_count += 1
            self.bytes_billed_total += int(diag.total_bytes_billed or 0)
            self.last_query = diag.to_dict()
            return rows, diag
        except Exception as exc:
            if job is not None and isinstance(exc, (concurrent.futures.TimeoutError, TimeoutError)):
                try:
                    job.cancel()
                except Exception:  # pragma: no cover - best effort
                    pass
            err = classify_bigquery_exception(exc)
            self.last_error = {"code": err.code, "message": str(err)[:200], "at": self._clock().isoformat()}
            log_event("WARN", f"WeatherNext BigQuery query failed: {err.code}", {"message": str(err)[:200]})
            raise err from exc

    def _effective_table(self, table: Optional[str], model: str = "weathernext_3", *, high_resolution: bool = False) -> str:
        try:
            chosen = table or self.cfg.bq.table_for(model, high_resolution=high_resolution)
        except ValueError as exc:
            raise WeatherNextQueryError("unsupported_model", str(exc)) from exc
        if not chosen:
            raise WeatherNextQueryError("table_not_configured", f"No BigQuery table configured for {model}")
        return chosen

    def fetch_point_forecast(
        self,
        lat: float,
        lon: float,
        *,
        horizon_hours: int = 72,
        run_id: Optional[str] = None,
        table: Optional[str] = None,
        model: str = "weathernext_3",
        high_resolution: bool = False,
        columns: Optional[tuple[str, ...]] = None,
    ) -> PointForecastResult:
        """Nearest-cell forecast for the newest available WN2/WN3 run."""
        cfg = self.cfg
        table_id = self._effective_table(table, model, high_resolution=high_resolution)
        policy = cfg.run_policy
        horizon = max(1, min(int(horizon_hours), policy.max_horizon_hours))
        now = self._clock()
        candidates = candidate_init_times(
            now,
            policy.run_hours,
            policy.delivery_latency_hours,
            policy.max_run_attempts,
            horizon,
            policy.max_horizon_hours,
            run_id=run_id,
            freshness_hours=policy.freshness_hours,
        )
        if not candidates:
            raise WeatherNextQueryError("no_candidate_run", "Run policy produced no candidate init times")

        attempted: list[str] = []
        last_diag: Optional[QueryDiagnostics] = None
        # Column vocabulary must match the *queried table's* schema: WN2 speaks
        # ERA5-style names, and the WN3 0.05 deg station table only carries
        # ``station_head_*`` leaves. Using the WN3 gridded profile for either
        # produces BigQuery "Unrecognized name" errors (schema_mismatch).
        default_columns = cfg.bq.columns_for(
            model, station=high_resolution or "0p05" in table_id
        )
        for init_time in candidates:
            allowed_horizon = min(horizon, run_horizon_hours(init_time, policy.max_horizon_hours))
            selected_columns = columns or default_columns
            sql, params = build_point_query(
                table_id, selected_columns, lat, lon, init_time, allowed_horizon, cfg.bq.nearest_radius_km
            )
            rows, diag = self.run_query(sql, params)
            model_id = "weathernext_2_0_0" if model.lower().replace("-", "_") in {"weathernext_2", "weathernext_2_0_0", "wn2", "2", "2.0.0"} else "weathernext_3_0_0"
            attempted.append(run_id_for(init_time, model_id))
            last_diag = diag
            if not rows:
                continue  # partition not delivered yet (or cell missing) - try an older run
            row = rows[0]
            steps = _coerce_steps(row.get("steps") or [])
            if not steps:
                continue
            distance_m = float(row.get("distance_m") or 0.0)
            return PointForecastResult(
                table=table_id,
                init_time=init_time,
                horizon_hours=allowed_horizon,
                run_horizon_hours=run_horizon_hours(init_time, policy.max_horizon_hours),
                cell_lat=float(row.get("cell_lat")),
                cell_lon=float(row.get("cell_lon")),
                distance_km=round(distance_m / 1000.0, 3),
                resolution_deg=resolution_for_table(table_id),
                columns=selected_columns,
                steps=steps,
                diagnostics=diag,
                attempted_inits=attempted,
                credential_source=self._client_source,
                model_id=("weathernext_2_0_0" if model.lower().replace("-", "_") in {"weathernext_2", "wn2", "2", "2.0.0"} else "weathernext_3_0_0"),
                model_version=("2.0.0" if model.lower().replace("-", "_") in {"weathernext_2", "wn2", "2", "2.0.0"} else "3.0.0"),
                surface="bigquery",
            )

        raise WeatherNextQueryError(
            "no_recent_run" if not run_id else "run_not_available",
            "No WeatherNext run with data for this location within the run policy window",
            {"attempted_runs": attempted, "last_query": last_diag.to_dict() if last_diag else None},
        )

    def query_wn3_point(self, lat: float, lon: float, init_time: Optional[datetime] = None, **kwargs) -> PointForecastResult:
        run_id = run_id_for(init_time) if init_time else kwargs.pop("run_id", None)
        return self.fetch_point_forecast(lat, lon, model="weathernext_3", run_id=run_id, **kwargs)

    def query_wn3_mean_point(self, lat: float, lon: float, init_time: Optional[datetime] = None, **kwargs) -> PointForecastResult:
        run_id = run_id_for(init_time) if init_time else kwargs.pop("run_id", None)
        mean_columns = tuple(c for c in self.cfg.bq.columns if c.endswith("_mean"))
        return self.fetch_point_forecast(lat, lon, model="weathernext_3", run_id=run_id, columns=mean_columns, **kwargs)

    def query_wn2_point(self, lat: float, lon: float, init_time: Optional[datetime] = None, **kwargs) -> PointForecastResult:
        run_id = run_id_for(init_time, "weathernext_2_0_0") if init_time else kwargs.pop("run_id", None)
        return self.fetch_point_forecast(lat, lon, model="weathernext_2", run_id=run_id, **kwargs)

    def query_wn2_mean_point(self, lat: float, lon: float, init_time: Optional[datetime] = None, **kwargs) -> PointForecastResult:
        run_id = run_id_for(init_time, "weathernext_2_0_0") if init_time else kwargs.pop("run_id", None)
        # The WN2 mean table already carries ensemble means and its leaves have
        # no statistic suffix, so the WN2 profile *is* the mean projection.
        # Filtering the WN3 profile for "_mean" queried WN3 names against a WN2
        # table - a guaranteed "Unrecognized name" (schema_mismatch) failure.
        mean_columns = self.cfg.bq.columns_for("weathernext_2")
        return self.fetch_point_forecast(lat, lon, model="weathernext_2", run_id=run_id, columns=mean_columns, **kwargs)

    def estimate_point_query(self, lat: float, lon: float, *, horizon_hours: int = 72, table: Optional[str] = None) -> dict:
        """Dry-run cost estimate (upper bound before cluster pruning). Bills nothing."""
        cfg = self.cfg
        table_id = self._effective_table(table)
        policy = cfg.run_policy
        candidates = candidate_init_times(
            self._clock(), policy.run_hours, policy.delivery_latency_hours, 1,
            horizon_hours, policy.max_horizon_hours,
        )
        init_time = candidates[0]
        sql, params = build_point_query(table_id, cfg.bq.columns, lat, lon, init_time, horizon_hours, cfg.bq.nearest_radius_km)
        _, diag = self.run_query(sql, params, dry_run=True)
        estimate = diag.total_bytes_processed or 0
        maximum_bytes_billed = int(cfg.bq.max_bytes_billed)
        within_cap = estimate <= maximum_bytes_billed
        return {
            "status": "ok",
            "table": table_id,
            "run_id": run_id_for(init_time),
            "columns": list(cfg.bq.columns),
            "estimated_bytes_upper_bound": estimate,
            "estimated_gib_upper_bound": round(estimate / 1024 ** 3, 3),
            "maximum_bytes_billed": maximum_bytes_billed,
            "within_cap": within_cap,
            "budget_status": "within_cap" if within_cap else "estimate_exceeds_cap",
            "note": "Dry-run estimates ignore geography cluster pruning; bytes actually billed are usually far lower. The dry run is uncapped and does not bill bytes.",
        }

    def stats(self) -> dict:
        cfg = self.cfg
        return {
            "client_ready": self._client is not None,
            "credential_source": self._client_source,
            "query_count": self.query_count,
            "bytes_billed_total": self.bytes_billed_total,
            "gib_billed_total": round(self.bytes_billed_total / 1024 ** 3, 4),
            "last_query": self.last_query,
            "last_error": self.last_error,
            "table": cfg.bq.surface_table,
            "column_profile": cfg.bq.column_profile,
            "columns": list(cfg.bq.columns),
            "maximum_bytes_billed": int(cfg.bq.max_bytes_billed),
            "run_policy": {
                "run_hours_utc": list(cfg.run_policy.run_hours),
                "delivery_latency_hours": cfg.run_policy.delivery_latency_hours,
                "max_run_attempts": cfg.run_policy.max_run_attempts,
                "freshness_hours": cfg.run_policy.freshness_hours,
                "cache_ttl_seconds": cfg.run_policy.cache_ttl_seconds,
            },
        }


def _coerce_steps(raw_steps: list) -> list[dict]:
    """Normalise BigQuery Row/dict structs to plain dicts sorted by time."""
    steps: list[dict] = []
    for item in raw_steps:
        try:
            step = dict(item)
        except Exception:
            continue
        t = step.get("time")
        if isinstance(t, str):
            try:
                t = datetime.fromisoformat(t.replace("Z", "+00:00"))
            except ValueError:
                t = None
        if not isinstance(t, datetime):
            continue
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        step["time"] = t.astimezone(timezone.utc)
        for key, value in list(step.items()):
            if key == "time":
                continue
            if value is None:
                continue
            try:
                num = float(value)
            except (TypeError, ValueError):
                step[key] = None
                continue
            step[key] = num if math.isfinite(num) else None
        steps.append(step)
    steps.sort(key=lambda s: s["time"])
    return steps


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_adapter: Optional[WeatherNextBigQueryAdapter] = None
_adapter_lock = threading.Lock()


def get_bigquery_adapter() -> WeatherNextBigQueryAdapter:
    global _adapter
    with _adapter_lock:
        if _adapter is None:
            _adapter = WeatherNextBigQueryAdapter()
        return _adapter


def set_bigquery_adapter(adapter: Optional[WeatherNextBigQueryAdapter]) -> None:
    """Inject an adapter (tests) or reset with ``None``."""
    global _adapter
    with _adapter_lock:
        _adapter = adapter


def query_wn3_point(lat: float, lon: float, init_time: Optional[datetime] = None, **kwargs) -> PointForecastResult:
    """Plan-compatible WN3 BigQuery point adapter."""
    run_id = run_id_for(init_time) if init_time else kwargs.pop("run_id", None)
    return get_bigquery_adapter().fetch_point_forecast(lat, lon, model="weathernext_3", run_id=run_id, **kwargs)


def query_wn3_mean_point(lat: float, lon: float, init_time: Optional[datetime] = None, **kwargs) -> PointForecastResult:
    """WN3 Mean is the statistics-only view of the same WN3 table."""
    kwargs.setdefault("table", get_config().weathernext.bq.table_3 or get_config().weathernext.bq.surface_table)
    run_id = run_id_for(init_time) if init_time else kwargs.pop("run_id", None)
    return get_bigquery_adapter().query_wn3_mean_point(lat, lon, run_id=run_id, **kwargs)


def query_wn2_point(lat: float, lon: float, init_time: Optional[datetime] = None, **kwargs) -> PointForecastResult:
    """WN2 BigQuery point adapter used for historical/comparison requests."""
    run_id = run_id_for(init_time, "weathernext_2_0_0") if init_time else kwargs.pop("run_id", None)
    return get_bigquery_adapter().fetch_point_forecast(lat, lon, model="weathernext_2", run_id=run_id, **kwargs)


def query_wn2_mean_point(lat: float, lon: float, init_time: Optional[datetime] = None, **kwargs) -> PointForecastResult:
    run_id = run_id_for(init_time, "weathernext_2_0_0") if init_time else kwargs.pop("run_id", None)
    return get_bigquery_adapter().query_wn2_mean_point(lat, lon, run_id=run_id, **kwargs)
