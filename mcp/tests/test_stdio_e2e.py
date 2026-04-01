from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from textwrap import dedent

import anyio
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


SERVER_SCRIPT = dedent(
    """
    from datetime import UTC, date, datetime, timedelta
    from types import SimpleNamespace

    import app.main as main_module
    from app.main import create_server
    from voltage_hub_core.schemas import (
        AnomalyRecord,
        EnergySourceRecord,
        FreshnessResponse,
        GenerationMixRecord,
        LoadMetricDailyRecord,
        PipelineStatusResponse,
        RegionRecord,
        ResponseMetadata,
        TopRegionsRecord,
    )


    class StubMetricsService:
        def __init__(self) -> None:
            self.bounds = {"start_date": date(2026, 3, 20), "end_date": date(2026, 3, 28)}
            self.metadata = ResponseMetadata(
                data_as_of=datetime(2026, 3, 28, 9, 30, tzinfo=UTC),
                pipeline_run_id="scheduled__2026-03-28T10:00:00+00:00",
                freshness_status="stale",
            )

        def get_load_metrics(self, **kwargs):
            return SimpleNamespace(
                data=[
                    LoadMetricDailyRecord(
                        region=kwargs["region"],
                        region_name="ERCOT",
                        observation_date=date(2026, 3, 28),
                        avg_load=10.0,
                        min_load=5.0,
                        max_load=20.0,
                        total_load=240.0,
                        unit="megawatthours",
                    )
                ],
                metadata=self.metadata,
            )

        def get_generation_mix(self, **kwargs):
            return SimpleNamespace(
                data=[
                    GenerationMixRecord(
                        region=kwargs["region"],
                        region_name="ERCOT",
                        observation_date=date(2026, 3, 28),
                        energy_source="SUN",
                        daily_total_generation=25.0,
                        unit="megawatthours",
                    ),
                    GenerationMixRecord(
                        region=kwargs["region"],
                        region_name="ERCOT",
                        observation_date=date(2026, 3, 28),
                        energy_source="WND",
                        daily_total_generation=75.0,
                        unit="megawatthours",
                    ),
                ],
                metadata=self.metadata,
            )

        def get_top_regions(self, **kwargs):
            return SimpleNamespace(
                data=[
                    TopRegionsRecord(
                        observation_date=date(2026, 3, 28),
                        region="ERCO",
                        region_name="ERCOT",
                        daily_total_load=240.0,
                        rank=1,
                    )
                ],
                metadata=self.metadata,
            )

        def get_available_date_bounds(self):
            return self.bounds


    class StubControlPlaneService:
        def get_freshness(self):
            return FreshnessResponse(
                pipeline_freshness_timestamp=datetime(2026, 3, 28, 10, 0, tzinfo=UTC),
                data_freshness_timestamp=datetime(2026, 3, 28, 9, 30, tzinfo=UTC),
                pipeline_freshness_status="fresh",
                data_freshness_status="stale",
                freshness_status="stale",
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

        def get_anomalies(self, **kwargs):
            return [
                AnomalyRecord(
                    observation_date=date(2026, 3, 28) - timedelta(days=index // 4),
                    region="ERCO",
                    metric_name="demand",
                    current_value=100.0 + index,
                    rolling_7d_avg=90.0,
                    pct_deviation=10.0,
                    anomaly_flag=True,
                    checked_at=datetime(2026, 3, 28, 10, 15, tzinfo=UTC),
                )
                for index in range(3)
            ]

        def get_anomaly_summary(self):
            return {
                "latest_observation_date": date(2026, 3, 28),
                "latest_anomaly_checked_at": datetime(2026, 3, 28, 10, 15, tzinfo=UTC),
                "flagged_anomaly_count_last_7_days": 2,
                "affected_regions_last_7_days": 1,
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
                EnergySourceRecord(energy_source="WND"),
            ]


    main_module.create_runtime = lambda: SimpleNamespace(
        metrics_service=StubMetricsService(),
        control_plane_service=StubControlPlaneService(),
        schema_service=StubSchemaService(),
    )
    create_server().run(transport="stdio")
    """
)


def _run_client(action: Callable[[ClientSession], Awaitable[object]]) -> object:
    async def _runner() -> object:
        params = StdioServerParameters(command="python", args=["-c", SERVER_SCRIPT])
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                return await action(session)

    return anyio.run(_runner)


def test_stdio_subprocess_discovery_matches_documented_surface() -> None:
    async def action(session: ClientSession) -> tuple[list[str], list[str]]:
        tools = await session.list_tools()
        resources = await session.list_resources()
        return (
            [tool.name for tool in tools.tools],
            [str(resource.uri) for resource in resources.resources],
        )

    result = _run_client(action)

    tool_names, resource_uris = result
    assert tool_names == [
        "get_load_trends",
        "get_generation_mix",
        "get_top_demand_regions",
        "check_data_freshness",
        "get_anomalies",
        "get_pipeline_status",
    ]
    assert resource_uris == [
        "schema://grid-metrics",
        "status://data-quality",
        "schema://regions",
        "schema://energy-sources",
    ]


def test_stdio_subprocess_success_contracts_for_tool_and_resource() -> None:
    async def action(session: ClientSession) -> tuple[dict[str, object], dict[str, object]]:
        tool_result = await session.call_tool("check_data_freshness", {})
        resource_result = await session.read_resource("schema://regions")
        return (
            tool_result.structuredContent,
            json.loads(resource_result.contents[0].text),
        )

    result = _run_client(action)

    tool_payload, resource_payload = result
    assert sorted(tool_payload.keys()) == ["data", "highlights", "metadata", "summary"]
    assert tool_payload["summary"]["question"] == "Current data freshness status"
    assert tool_payload["metadata"]["freshness_status"] == "stale"
    assert tool_payload["data"]["data_freshness_status"] == "stale"
    assert resource_payload == {
        "regions": [
            {"region": "ERCO", "region_name": "ERCOT"},
            {"region": "CISO", "region_name": "California ISO"},
        ]
    }
