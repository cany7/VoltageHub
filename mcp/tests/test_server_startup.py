from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

from app.main import create_server
from voltage_hub_core.exceptions import RepositoryError
from voltage_hub_core.schemas import (
    EnergySourceRecord,
    FreshnessResponse,
    PipelineStatusResponse,
    RegionRecord,
)


class StubMetricsService:
    def get_available_date_bounds(self):
        return {"start_date": date(2026, 3, 20), "end_date": date(2026, 3, 28)}


class StubControlPlaneService:
    def get_freshness(self):
        return FreshnessResponse(
            pipeline_freshness_timestamp=datetime(2026, 3, 28, 10, 0, tzinfo=UTC),
            data_freshness_timestamp=datetime(2026, 3, 28, 9, 30, tzinfo=UTC),
            pipeline_freshness_status="fresh",
            data_freshness_status="fresh",
            freshness_status="fresh",
            checked_at=datetime(2026, 3, 28, 10, 15, tzinfo=UTC),
        )

    def get_pipeline_status(self):
        return PipelineStatusResponse(
            pipeline_name="eia_grid_batch",
            last_successful_window_start=datetime(2026, 3, 28, 9, 0, tzinfo=UTC),
            last_successful_window_end=datetime(2026, 3, 28, 10, 0, tzinfo=UTC),
            last_successful_run_id="scheduled__2026-03-28T10:00:00+00:00",
            updated_at=datetime(2026, 3, 28, 10, 10, tzinfo=UTC),
        )

    def get_anomaly_summary(self):
        return {
            "latest_observation_date": date(2026, 3, 28),
            "latest_anomaly_checked_at": datetime(2026, 3, 28, 10, 15, tzinfo=UTC),
            "flagged_anomaly_count_last_7_days": 0,
            "affected_regions_last_7_days": 0,
        }


class StubSchemaService:
    def list_regions(self):
        return [
            RegionRecord(region="ERCO", region_name="ERCOT"),
            RegionRecord(region="CISO", region_name="California ISO"),
        ]

    def list_energy_sources(self):
        return [
            EnergySourceRecord(energy_source="COL"),
            EnergySourceRecord(energy_source="SUN"),
        ]


def test_create_server_registers_documented_tools_and_resources(monkeypatch) -> None:
    runtime = SimpleNamespace(
        metrics_service=StubMetricsService(),
        control_plane_service=StubControlPlaneService(),
        schema_service=StubSchemaService(),
    )
    monkeypatch.setattr("app.main.create_runtime", lambda: runtime)

    server = create_server()

    assert set(server._tool_manager._tools.keys()) == {
        "get_load_trends",
        "get_generation_mix",
        "get_top_demand_regions",
        "check_data_freshness",
        "get_anomalies",
        "get_pipeline_status",
    }
    assert set(server._resource_manager._resources.keys()) == {
        "schema://grid-metrics",
        "status://data-quality",
        "schema://regions",
        "schema://energy-sources",
    }


def test_schema_region_and_energy_resources_match_v1_contract() -> None:
    from app.adapters.voltagehub import VoltageHubMCPAdapter

    runtime = SimpleNamespace(
        metrics_service=SimpleNamespace(
            get_available_date_bounds=lambda: {
                "start_date": date(2026, 3, 20),
                "end_date": date(2026, 3, 28),
            }
        ),
        control_plane_service=StubControlPlaneService(),
        schema_service=StubSchemaService(),
    )
    adapter = VoltageHubMCPAdapter(runtime)

    assert adapter.schema_regions() == {
        "regions": [
            {"region": "ERCO", "region_name": "ERCOT"},
            {"region": "CISO", "region_name": "California ISO"},
        ]
    }
    assert adapter.schema_energy_sources() == {
        "energy_sources": [
            {"energy_source": "COL"},
            {"energy_source": "SUN"},
        ]
    }


def test_resource_repository_failures_return_structured_error_envelope() -> None:
    from app.adapters.voltagehub import VoltageHubMCPAdapter

    runtime = SimpleNamespace(
        metrics_service=SimpleNamespace(
            get_available_date_bounds=lambda: (_ for _ in ()).throw(
                RepositoryError("BigQuery query execution failed")
            )
        ),
        control_plane_service=StubControlPlaneService(),
        schema_service=SimpleNamespace(
            list_regions=lambda: (_ for _ in ()).throw(
                RepositoryError("BigQuery query execution failed")
            ),
            list_energy_sources=lambda: [],
        ),
    )
    adapter = VoltageHubMCPAdapter(runtime)

    assert adapter.schema_grid_metrics() == {
        "error": {
            "code": "repository_error",
            "message": "BigQuery query execution failed",
        }
    }
    assert adapter.schema_regions() == {
        "error": {
            "code": "repository_error",
            "message": "BigQuery query execution failed",
        }
    }
