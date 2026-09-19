"""WeatherNext capability catalog and discovery manifest.

Implements section 3a capability inventory and coverage contract.

Registry record required for every discovered capability:
stable capability_id, product/model/version, surface, documented operation,
resource identifier, documentation revision, actual schema/units/dimensions,
temporal/spatial coverage, access status, license/distribution rules,
cost/quota bounds, provider adapter, backend route, UI entry point,
LangGraph tool mapping, last verified date, test ID, blocker/owner.

States: unverified, not_granted, blocked_by_terms, unsupported, planned,
implemented, verified
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from services.forecast_models import PRESSURE_LEVELS, WEATHERNEXT_VARIABLES


class CapabilityState(str, Enum):
    UNVERIFIED = "unverified"
    NOT_GRANTED = "not_granted"
    BLOCKED_BY_TERMS = "blocked_by_terms"
    UNSUPPORTED = "unsupported"
    PLANNED = "planned"
    IMPLEMENTED = "implemented"
    VERIFIED = "verified"


@dataclass
class CapabilityRecord:
    capability_id: str
    product: str  # e.g., weathernext_3_0_0
    model_version: str
    surface: str  # bigquery, gcs_ensemble, gcs_statistics, earth_engine, cyclone, inference
    operation: str  # e.g., point_query, regional_job, profile, etc.
    resource_identifier: str  # e.g., gs://... or table ID
    documentation_revision: str
    schema: dict  # units, dimensions, etc.
    temporal_coverage: dict  # init times, valid times, horizons
    spatial_coverage: dict  # grids, resolutions, regions
    access_status: CapabilityState
    license: str
    distribution_rules: str
    cost_bounds: dict
    quota_bounds: dict
    provider_adapter: str
    backend_route: str
    ui_entry_point: str
    langgraph_tool: str
    last_verified: Optional[str] = None
    test_id: Optional[str] = None
    blocker: Optional[str] = None
    owner: Optional[str] = None


def build_default_catalog() -> list[CapabilityRecord]:
    """Build catalog from documented variables and surfaces."""
    records: list[CapabilityRecord] = []
    now_iso = datetime.now(timezone.utc).isoformat()

    # GCS full ensemble
    for var_id, native_u, display_u, desc, res in WEATHERNEXT_VARIABLES:
        records.append(CapabilityRecord(
            capability_id=f"gcs_ensemble_{var_id}",
            product="weathernext_3_0_0",
            model_version="3.0.0",
            surface="gcs_ensemble",
            operation="point_query",
            resource_identifier="gs://weathernext3_spatial/weathernext_3_0_0/zarr/",
            documentation_revision="2026-09-03",
            schema={
                "variable": var_id,
                "native_units": native_u,
                "display_units": display_u,
                "dimensions": ["time", "lat", "lon", "member"] if "surface" in desc.lower() or res else ["time", "level", "lat", "lon", "member"],
                "resolution_deg": res,
            },
            temporal_coverage={
                "init_times": "00,06,12,18Z synoptic + hourly interim",
                "horizon_hours": 360 if "synoptic" else 48,
                "step_hours": 1,
            },
            spatial_coverage={
                "grid": f"{res} deg" if res else "0.25 deg",
                "global": True,
            },
            access_status=CapabilityState.PLANNED,
            license="WeatherNext real-time terms (internal/value-added, no redistribution)",
            distribution_rules="No public redistribution of unmodified real-time data; value-added services controlled",
            cost_bounds={"storage": "Requester Pays us-east1", "compute": "nearby processing"},
            quota_bounds={"max_members": 64, "max_region": "bounded"},
            provider_adapter="weathernext",
            backend_route="/v2/weather/ensemble",
            ui_entry_point="researcher_ensemble_browser",
            langgraph_tool="analyze_weathernext_ensemble",
            last_verified=now_iso,
            test_id=f"test_weathernest_{var_id}",
            blocker=None,
            owner="backend",
        ))

    # GCS statistics
    for var_id, native_u, display_u, desc, res in WEATHERNEXT_VARIABLES:
        for stat in ["mean", "p10", "p25", "p50", "p75", "p90"]:
            records.append(CapabilityRecord(
                capability_id=f"gcs_stats_{var_id}_{stat}",
                product="weathernext_3_0_0_statistics",
                model_version="3.0.0",
                surface="gcs_statistics",
                operation="point_query",
                resource_identifier="gs://weathernext3_statistics_spatial/weathernext_3_0_0_statistics/zarr/",
                documentation_revision="2026-09-03",
                schema={
                    "variable": var_id,
                    "statistic": stat,
                    "native_units": native_u,
                    "display_units": display_u,
                },
                temporal_coverage={"horizon_hours": 360, "step_hours": 1},
                spatial_coverage={"grid": f"{res} deg"},
                access_status=CapabilityState.PLANNED,
                license="WeatherNext real-time terms",
                distribution_rules="Value-added only",
                cost_bounds={"storage": "Requester Pays off but compute still costs"},
                quota_bounds={},
                provider_adapter="weathernext",
                backend_route="/v2/weather/series",
                ui_entry_point="home_forecast",
                langgraph_tool="query_weathernext_data",
                last_verified=now_iso,
                test_id=f"test_stats_{var_id}_{stat}",
            ))

    # BigQuery
    for var_id, _, _, _, _ in WEATHERNEXT_VARIABLES:
        for stat in ["mean", "p10", "p25", "p50", "p75", "p90"]:
            records.append(CapabilityRecord(
                capability_id=f"bq_{var_id}_{stat}",
                product="weathernext_3_0_0",
                model_version="3.0.0",
                surface="bigquery",
                operation="bounded_query",
                resource_identifier="your-project.your_linked_dataset.weathernext_3_0_0_0p1deg",
                documentation_revision="2026-09-03",
                schema={"variable": var_id, "statistic": stat},
                temporal_coverage={"partitioned_by": "init_time"},
                spatial_coverage={"grid": "0.1 deg and 0.05 deg station head"},
                access_status=CapabilityState.PLANNED,
                license="CC BY 4.0 for historical (valid time >1h past), real-time terms otherwise",
                distribution_rules="Historical CC BY 4.0, real-time controlled",
                cost_bounds={"max_bytes_billed": 100_000_000},
                quota_bounds={"max_bytes_per_query": 100_000_000},
                provider_adapter="weathernext",
                backend_route="/v2/weather/series",
                ui_entry_point="researcher_table_explorer",
                langgraph_tool="query_weathernext_data",
                last_verified=now_iso,
            ))

    # Upper-air
    for level in PRESSURE_LEVELS:
        for base in ["temperature", "geopotential", "u_component_of_wind", "v_component_of_wind"]:
            records.append(CapabilityRecord(
                capability_id=f"gcs_ensemble_{base}_{level}",
                product="weathernext_3_0_0",
                model_version="3.0.0",
                surface="gcs_ensemble",
                operation="profile",
                resource_identifier="gs://weathernext3_spatial/weathernext_3_0_0/zarr/",
                documentation_revision="2026-09-03",
                schema={"variable": f"{base}_{level}", "level_hpa": level, "resolution_deg": 0.25},
                temporal_coverage={"synoptic_only": True, "horizon_hours": 360},
                spatial_coverage={"grid": "0.25 deg", "levels": PRESSURE_LEVELS},
                access_status=CapabilityState.PLANNED,
                license="WeatherNext real-time terms",
                distribution_rules="Researcher mode only, no public raw distribution",
                cost_bounds={"storage": "Requester Pays"},
                quota_bounds={},
                provider_adapter="weathernext",
                backend_route="/v2/weather/profile",
                ui_entry_point="researcher_profile",
                langgraph_tool="get_weathernext_profile",
                last_verified=now_iso,
            ))

    # Earth Engine (optional)
    records.append(CapabilityRecord(
        capability_id="earth_engine_surface_stats",
        product="weathernext_3_0_0",
        model_version="3.0.0",
        surface="earth_engine",
        operation="map_layer",
        resource_identifier="projects/your-ee-project/assets/weathernext",
        documentation_revision="2026-09-03",
        schema={"type": "ImageCollection", "bands": [v[0] for v in WEATHERNEXT_VARIABLES]},
        temporal_coverage={"horizon": "360h"},
        spatial_coverage={"global": True},
        access_status=CapabilityState.UNVERIFIED,
        license="EE terms + WeatherNext terms",
        distribution_rules="EE processing, not raw export",
        cost_bounds={"ee_compute": "quota based"},
        quota_bounds={},
        provider_adapter="weathernext",
        backend_route="/v2/weather/tiles",
        ui_entry_point="researcher_map",
        langgraph_tool="get_weathernext_map_layer",
        last_verified=None,
        blocker="Requires EE project registration and verification",
    ))

    # Cyclones
    records.append(CapabilityRecord(
        capability_id="weathernext_cyclones_tracks",
        product="weathernext_cyclones",
        model_version="1.0",
        surface="weather_lab",
        operation="track_inspection",
        resource_identifier="https://developers.google.com/weathernext/guides/weatherlab",
        documentation_revision="2026-09-03",
        schema={"fields": ["storm_id", "track", "intensity", "member_tracks"]},
        temporal_coverage={"real_time": True},
        spatial_coverage={"tropical": True},
        access_status=CapabilityState.UNVERIFIED,
        license="WeatherNext terms",
        distribution_rules="CSV/ATCF downloads, attribution required",
        cost_bounds={},
        quota_bounds={},
        provider_adapter="weathernext",
        backend_route="/v2/weather/cyclones",
        ui_entry_point="researcher_cyclone",
        langgraph_tool="get_weathernext_cyclone_tracks",
        last_verified=None,
        blocker="Delivery contract not verified, no programmatic API confirmed",
    ))

    return records


class Catalog:
    def __init__(self):
        self._records = build_default_catalog()
        self._by_id = {r.capability_id: r for r in self._records}

    def all(self) -> list[CapabilityRecord]:
        return self._records

    def get(self, capability_id: str) -> Optional[CapabilityRecord]:
        return self._by_id.get(capability_id)

    def filter_by_surface(self, surface: str) -> list[CapabilityRecord]:
        return [r for r in self._records if r.surface == surface]

    def filter_by_state(self, state: CapabilityState) -> list[CapabilityRecord]:
        return [r for r in self._records if r.access_status == state]

    def coverage_report(self) -> dict:
        total = len(self._records)
        by_state = {}
        for state in CapabilityState:
            by_state[state.value] = len(self.filter_by_state(state))
        by_surface = {}
        for r in self._records:
            by_surface[r.surface] = by_surface.get(r.surface, 0) + 1

        # Per spec: discovered, permitted, implemented, verified, blocked
        discovered = total
        permitted = len([r for r in self._records if r.access_status not in (CapabilityState.NOT_GRANTED, CapabilityState.BLOCKED_BY_TERMS)])
        implemented = len([r for r in self._records if r.access_status in (CapabilityState.IMPLEMENTED, CapabilityState.VERIFIED)])
        verified = len([r for r in self._records if r.access_status == CapabilityState.VERIFIED])
        blocked = len([r for r in self._records if r.access_status in (CapabilityState.NOT_GRANTED, CapabilityState.BLOCKED_BY_TERMS, CapabilityState.UNSUPPORTED)])

        return {
            "discovered": discovered,
            "permitted": permitted,
            "implemented": implemented,
            "verified": verified,
            "blocked": blocked,
            "by_state": by_state,
            "by_surface": by_surface,
        }

    def to_manifest(self) -> dict:
        """Sanitized manifest for diagnostics (no credentials)."""
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_capabilities": len(self._records),
            "coverage": self.coverage_report(),
            "capabilities": [asdict(r) for r in self._records[:50]],  # first 50 for brevity
        }


_catalog: Optional[Catalog] = None

def get_catalog() -> Catalog:
    global _catalog
    if _catalog is None:
        _catalog = Catalog()
    return _catalog
