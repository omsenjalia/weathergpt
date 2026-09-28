"""Bounded BigQuery point queries against WeatherNext surface tables.

Table contract (developers.google.com/weathernext/guides/bigquery):
    init_time  TIMESTAMP        partition key — always filtered exactly (never a full scan)
    geography  GEOGRAPHY        cell centre, clustering column (ST_DWITHIN prunes blocks)
    forecast   REPEATED RECORD  {time, hours, <variable>_{mean,p10,p25,p50,p75,p90}}

Cost rules: exact partition filter, explicit leaf columns only, spatial predicate
on the clustered column, ``maximum_bytes_billed`` on every job, bounded wait
with cancellation.

Run policy: WN3 initialises hourly but only 00/06/12/18 UTC runs carry the
15-day horizon (interim runs stop at 48 h), and runs land ~7 h after init. The
newest expected run is tried first, then older ones (an empty partition is free),
never further back than the 2x-freshness expiry horizon.
"""

from __future__ import annotations

import concurrent.futures
import math
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from weathergpt.config import normalize_wn_model, settings
from weathergpt.runtime import log_event
from weathergpt.weathernext.auth import CredentialsUnavailable, get_credentials

ENSEMBLE_MEMBERS = 64
INTERIM_RUN_HORIZON_HOURS = 48
_TABLE_RE = re.compile(r"^[A-Za-z0-9_\-]+\.[A-Za-z0-9_]+\.[A-Za-z0-9_]+$")
_COLUMN_RE = re.compile(r"^[a-z0-9][a-z0-9_]*$")
_RUN_ID_RE = re.compile(r"(\d{4})(\d{2})(\d{2})(\d{2})$")

# Configuration/entitlement problems: retrying cannot help, so they must not trip the breaker.
NON_TRANSIENT = frozenset({
    "live_credentials_required", "credential_refresh_failed", "permission_denied", "billing_disabled",
    "unauthenticated", "table_not_found", "table_not_configured", "invalid_table", "invalid_columns",
    "invalid_run_id", "schema_mismatch", "bytes_billed_limit_exceeded", "missing_dependency_bigquery",
    "no_candidate_run", "unsupported_model",
})


class WeatherNextQueryError(RuntimeError):
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
    duration_ms: Optional[float] = None
    rows: int = 0

    def to_dict(self) -> dict:
        return {k: (round(v, 1) if k == "duration_ms" and v is not None else v) for k, v in self.__dict__.items()}


@dataclass
class PointForecastResult:
    table: str
    model_id: str
    model_version: str
    init_time: datetime
    horizon_hours: int
    cell_lat: float
    cell_lon: float
    distance_km: float
    resolution_deg: float
    columns: tuple[str, ...]
    steps: list[dict]
    diagnostics: QueryDiagnostics
    attempted_runs: list[str] = field(default_factory=list)
    credential_source: Optional[str] = None

    @property
    def run_id(self) -> str:
        return run_id_for(self.init_time, self.model_id)


def model_ids(model: str) -> tuple[str, str]:
    return ("weathernext_2_0_0", "2.0.0") if normalize_wn_model(model) == "weathernext_2" else ("weathernext_3_0_0", "3.0.0")


def run_id_for(init_time: datetime, model_id: str = "weathernext_3_0_0") -> str:
    return f"{model_id}_{init_time.astimezone(timezone.utc):%Y%m%d%H}"


def parse_run_id(run_id: str) -> Optional[datetime]:
    """Accept ``weathernext_3_0_0_2026091900``, ``2026091900`` or ISO-8601."""
    text = (run_id or "").strip()
    if not text:
        return None
    m = _RUN_ID_RE.search(text)
    if m and (text.startswith("weathernext_") or text.isdigit()):
        try:
            return datetime(*(int(g) for g in m.groups()), tzinfo=timezone.utc)
        except ValueError:
            return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    dt = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


def run_horizon_hours(init_time: datetime, max_horizon: int) -> int:
    return max_horizon if init_time.hour % 6 == 0 else INTERIM_RUN_HORIZON_HOURS


def candidate_init_times(now: datetime, run_hours: tuple[int, ...], latency_hours: float, max_attempts: int,
                         horizon_hours: int, max_horizon: int, freshness_hours: float,
                         run_id: Optional[str] = None) -> list[datetime]:
    if run_id:
        pinned = parse_run_id(run_id)
        if pinned is None:
            raise WeatherNextQueryError("invalid_run_id", f"Unrecognised run_id '{run_id[:40]}'")
        return [pinned]
    t = (now - timedelta(hours=latency_hours)).astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    floor = now - timedelta(hours=min(72.0, 2.0 * freshness_hours))
    out: list[datetime] = []
    while len(out) < max_attempts and t >= floor:
        if t.hour in run_hours and run_horizon_hours(t, max_horizon) >= min(horizon_hours, max_horizon):
            out.append(t)
        t -= timedelta(hours=1)
    return out


def build_point_query(table: str, columns: tuple[str, ...], lat: float, lon: float, init_time: datetime,
                      horizon_hours: int, radius_km: float) -> tuple[str, list]:
    if not _TABLE_RE.match(table):
        raise WeatherNextQueryError("invalid_table", "table must be project.dataset.table")
    bad = [c for c in columns if not _COLUMN_RE.match(c)]
    if bad or not columns:
        raise WeatherNextQueryError("invalid_columns", f"Invalid column names: {bad[:3]}")
    init_utc = init_time.astimezone(timezone.utc)
    leaves = ",\n              ".join(f"f.`{c}`" if c[0].isdigit() else f"f.{c}" for c in columns)
    sql = f"""
        SELECT
          ST_Y(t.geography) AS cell_lat,
          ST_X(t.geography) AS cell_lon,
          ST_DISTANCE(t.geography, ST_GEOGPOINT(@lon, @lat)) AS distance_m,
          ARRAY(
            SELECT AS STRUCT
              f.time,
              {leaves}
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
    params = [
        ("lat", "FLOAT64", float(lat)), ("lon", "FLOAT64", float(lon)),
        ("init_time", "TIMESTAMP", init_utc), ("max_time", "TIMESTAMP", init_utc + timedelta(hours=int(horizon_hours))),
        ("radius_m", "FLOAT64", float(radius_km) * 1000.0),
    ]
    return sql, params


def classify_exception(exc: BaseException) -> WeatherNextQueryError:
    if isinstance(exc, WeatherNextQueryError):
        return exc
    if isinstance(exc, CredentialsUnavailable):
        return WeatherNextQueryError(exc.code, str(exc), {"attempts": exc.attempts})
    message = str(exc).replace("\n", " ")
    short = f"{type(exc).__name__}: {message[:200]}"
    low = message.lower()
    if isinstance(exc, (concurrent.futures.TimeoutError, TimeoutError)):
        return WeatherNextQueryError("query_timeout", short)
    try:
        from google.api_core import exceptions as g  # type: ignore
        from google.auth.exceptions import RefreshError, TransportError  # type: ignore
    except ImportError:
        return WeatherNextQueryError("query_failed", short)
    if isinstance(exc, RefreshError):
        return WeatherNextQueryError("credential_refresh_failed", short)
    if isinstance(exc, g.Forbidden):
        code = "billing_disabled" if "billing" in low else "quota_exceeded" if ("quota" in low or "rate" in low) else "permission_denied"
        return WeatherNextQueryError(code, short)
    if isinstance(exc, g.Unauthorized):
        return WeatherNextQueryError("unauthenticated", short)
    if isinstance(exc, g.NotFound):
        return WeatherNextQueryError("table_not_found", short)
    if isinstance(exc, g.BadRequest):
        if "bytes billed" in low or "bytesbilledlimitexceeded" in low:
            m = re.search(r"(\d+) or higher required", message)
            return WeatherNextQueryError("bytes_billed_limit_exceeded", short,
                                         {"required_bytes": int(m.group(1)) if m else None})
        if "unrecognized name" in low or "not found inside" in low:
            return WeatherNextQueryError("schema_mismatch", short)
        return WeatherNextQueryError("bad_request", short)
    if isinstance(exc, (g.TooManyRequests, g.ResourceExhausted)):
        return WeatherNextQueryError("quota_exceeded", short)
    if isinstance(exc, g.DeadlineExceeded):
        return WeatherNextQueryError("query_timeout", short)
    if isinstance(exc, (g.ServiceUnavailable, g.InternalServerError, g.BadGateway)):
        return WeatherNextQueryError("bigquery_unavailable", short)
    if isinstance(exc, TransportError):
        return WeatherNextQueryError("network_error", short)
    return WeatherNextQueryError("query_failed", short)


def _coerce_steps(raw: list) -> list[dict]:
    steps = []
    for item in raw:
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
        step["time"] = (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
        for k, v in list(step.items()):
            if k == "time" or v is None:
                continue
            try:
                num = float(v)
            except (TypeError, ValueError):
                step[k] = None
                continue
            step[k] = num if math.isfinite(num) else None
        steps.append(step)
    steps.sort(key=lambda s: s["time"])
    return steps


class BigQueryAdapter:
    def __init__(self, client_factory: Optional[Callable[[Any], Any]] = None,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self._client_factory = client_factory
        self._clock = clock
        self._client = None
        self._source: Optional[str] = None
        self._lock = threading.Lock()
        self.query_count = 0
        self.bytes_billed_total = 0
        self.last_error: Optional[dict] = None

    def now(self) -> datetime:
        return self._clock()

    def client(self):
        with self._lock:
            if self._client is not None:
                return self._client
            bundle = get_credentials()
            if self._client_factory is not None:
                self._client = self._client_factory(bundle)
            else:
                try:
                    from google.cloud import bigquery  # type: ignore
                except ImportError as exc:
                    raise WeatherNextQueryError("missing_dependency_bigquery", str(exc))
                self._client = bigquery.Client(project=bundle.project, credentials=bundle.credentials,
                                               location=settings().weathernext.location)
            self._source = bundle.source
            return self._client

    def run(self, sql: str, params: list) -> tuple[list[dict], QueryDiagnostics]:
        cfg = settings().weathernext
        diag = QueryDiagnostics()
        started = time.perf_counter()
        job = None
        try:
            from google.cloud import bigquery  # type: ignore
            job_config = bigquery.QueryJobConfig(
                query_parameters=[bigquery.ScalarQueryParameter(n, k, v) for n, k, v in params],
                maximum_bytes_billed=int(cfg.max_bytes_billed), use_query_cache=True, use_legacy_sql=False,
                labels={"app": "weathergpt", "component": "weathernext"},
            )
            job = self.client().query(sql, job_config=job_config, location=cfg.location)
            diag.job_id = getattr(job, "job_id", None)
            rows = [dict(r) for r in job.result(timeout=cfg.query_timeout_seconds)]
            diag.rows = len(rows)
            diag.cache_hit = getattr(job, "cache_hit", None)
            diag.total_bytes_processed = getattr(job, "total_bytes_processed", None)
            diag.total_bytes_billed = getattr(job, "total_bytes_billed", None)
            diag.duration_ms = (time.perf_counter() - started) * 1000
            self.query_count += 1
            self.bytes_billed_total += int(diag.total_bytes_billed or 0)
            return rows, diag
        except ImportError as exc:
            raise WeatherNextQueryError("missing_dependency_bigquery", str(exc)) from exc
        except Exception as exc:
            if job is not None and isinstance(exc, (concurrent.futures.TimeoutError, TimeoutError)):
                try:
                    job.cancel()
                except Exception:
                    pass
            err = classify_exception(exc)
            self.last_error = {"code": err.code, "message": str(err)[:200], "at": self.now().isoformat()}
            log_event("WARN", f"WeatherNext BigQuery failed: {err.code}", {"message": str(err)[:200]})
            raise err from exc

    def fetch_point(self, lat: float, lon: float, *, horizon_hours: int, model: str = "weathernext_3",
                    run_id: Optional[str] = None, high_resolution: bool = False) -> PointForecastResult:
        cfg = settings().weathernext
        try:
            model = normalize_wn_model(model)
        except ValueError as exc:
            raise WeatherNextQueryError("unsupported_model", str(exc)) from exc
        table = cfg.table_for(model, high_resolution=high_resolution)
        if not table:
            raise WeatherNextQueryError("table_not_configured", f"No BigQuery table configured for {model}")
        horizon = max(1, min(int(horizon_hours), cfg.max_horizon_hours))
        candidates = candidate_init_times(self.now(), cfg.run_hours, cfg.delivery_latency_hours, cfg.max_run_attempts,
                                          horizon, cfg.max_horizon_hours, cfg.freshness_hours, run_id)
        if not candidates:
            raise WeatherNextQueryError("no_candidate_run", "Run policy produced no candidate init times")
        columns = cfg.columns_for(model, station=high_resolution or "0p05" in table)
        model_id, model_version = model_ids(model)
        attempted: list[str] = []
        for init_time in candidates:
            allowed = min(horizon, run_horizon_hours(init_time, cfg.max_horizon_hours))
            sql, params = build_point_query(table, columns, lat, lon, init_time, allowed, cfg.nearest_radius_km)
            rows, diag = self.run(sql, params)
            attempted.append(run_id_for(init_time, model_id))
            if not rows:
                continue  # partition not delivered yet — try an older run
            steps = _coerce_steps(rows[0].get("steps") or [])
            if not steps:
                continue
            return PointForecastResult(
                table=table, model_id=model_id, model_version=model_version, init_time=init_time,
                horizon_hours=allowed, cell_lat=float(rows[0]["cell_lat"]), cell_lon=float(rows[0]["cell_lon"]),
                distance_km=round(float(rows[0].get("distance_m") or 0) / 1000, 3),
                resolution_deg=0.05 if "0p05" in table else 0.1, columns=columns, steps=steps,
                diagnostics=diag, attempted_runs=attempted, credential_source=self._source,
            )
        raise WeatherNextQueryError("run_not_available" if run_id else "no_recent_run",
                                    "No WeatherNext run with data for this location within the run policy window",
                                    {"attempted_runs": attempted})

    def stats(self) -> dict:
        cfg = settings().weathernext
        return {
            "client_ready": self._client is not None, "credential_source": self._source,
            "query_count": self.query_count, "bytes_billed_total": self.bytes_billed_total,
            "last_error": self.last_error, "table_3": cfg.table_3, "table_2": cfg.table_2,
            "column_profile": cfg.column_profile, "maximum_bytes_billed": cfg.max_bytes_billed,
            "run_policy": {"run_hours_utc": list(cfg.run_hours), "delivery_latency_hours": cfg.delivery_latency_hours,
                           "max_run_attempts": cfg.max_run_attempts, "freshness_hours": cfg.freshness_hours},
        }


_adapter: Optional[BigQueryAdapter] = None
_adapter_lock = threading.Lock()


def adapter() -> BigQueryAdapter:
    global _adapter
    with _adapter_lock:
        if _adapter is None:
            _adapter = BigQueryAdapter()
        return _adapter


def set_adapter(value: Optional[BigQueryAdapter]) -> None:
    global _adapter
    with _adapter_lock:
        _adapter = value
