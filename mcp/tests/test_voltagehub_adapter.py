from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

from app.adapters.voltagehub import (
    ANOMALIES_MAX_ROWS,
    VoltageHubMCPAdapter,
    resource_specs,
    tool_specs,
)
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
        self.load_calls: list[dict[str, object]] = []
        self.generation_calls: list[dict[str, object]] = []
        self.top_region_calls: list[dict[str, object]] = []
        self.load_rows: list[object] = []
        self.generation_rows: list[GenerationMixRecord] = []
        self.top_region_rows: list[TopRegionsRecord] = []
        self.bounds = {"start_date": date(2026, 3, 20), "end_date": date(2026, 3, 28)}
        self.metadata = ResponseMetadata(
            data_as_of=datetime(2026, 3, 28, 9, 30, tzinfo=UTC),
            pipeline_run_id="scheduled__2026-03-28T10:00:00+00:00",
            freshness_status="fresh",
        )

    def get_load_metrics(self, **kwargs):
        self.load_calls.append(kwargs)
        return SimpleNamespace(data=self.load_rows, metadata=self.metadata)

    def get_generation_mix(self, **kwargs):
        self.generation_calls.append(kwargs)
        return SimpleNamespace(data=self.generation_rows, metadata=self.metadata)

    def get_top_regions(self, **kwargs):
        self.top_region_calls.append(kwargs)
        return SimpleNamespace(data=self.top_region_rows, metadata=self.metadata)

    def get_available_date_bounds(self):
        return self.bounds


class StubControlPlaneService:
    def __init__(self) -> None:
        self.anomaly_rows: list[AnomalyRecord] = []
        self.anomaly_calls: list[dict[str, object]] = []
        self.freshness = FreshnessResponse(
            pipeline_freshness_timestamp=datetime(2026, 3, 28, 10, 0, tzinfo=UTC),
            data_freshness_timestamp=datetime(2026, 3, 28, 9, 30, tzinfo=UTC),
            pipeline_freshness_status="fresh",
            data_freshness_status="stale",
            freshness_status="stale",
            checked_at=datetime(2026, 3, 28, 10, 15, tzinfo=UTC),
        )
        self.pipeline = PipelineStatusResponse(
            pipeline_name="eia_grid_batch",
            last_successful_window_start=datetime(2026, 3, 28, 9, 0, tzinfo=UTC),
            last_successful_window_end=datetime(2026, 3, 28, 10, 0, tzinfo=UTC),
            last_successful_run_id="scheduled__2026-03-28T10:00:00+00:00",
            updated_at=datetime(2026, 3, 28, 10, 10, tzinfo=UTC),
        )
        self.anomaly_summary = {
            "latest_observation_date": date(2026, 3, 28),
            "latest_anomaly_checked_at": datetime(2026, 3, 28, 10, 15, tzinfo=UTC),
            "flagged_anomaly_count_last_7_days": 4,
            "affected_regions_last_7_days": 2,
        }

    def get_freshness(self):
        return self.freshness

    def get_pipeline_status(self):
        return self.pipeline

    def get_anomalies(self, **kwargs):
        self.anomaly_calls.append(kwargs)
        return self.anomaly_rows

    def get_anomaly_summary(self):
        return self.anomaly_summary


class StubSchemaService:
    def __init__(self) -> None:
        self.regions = [
            RegionRecord(region="ERCO", region_name="ERCOT"),
            RegionRecord(region="CISO", region_name="California ISO"),
        ]
        self.energy_sources = [
            EnergySourceRecord(energy_source="COL"),
            EnergySourceRecord(energy_source="SUN"),
            EnergySourceRecord(energy_source="WND"),
        ]

    def list_regions(self):
        return self.regions

    def list_energy_sources(self):
        return self.energy_sources


def _build_adapter() -> tuple[VoltageHubMCPAdapter, StubMetricsService, StubControlPlaneService]:
    metrics_service = StubMetricsService()
    control_plane_service = StubControlPlaneService()
    runtime = SimpleNamespace(
        metrics_service=metrics_service,
        control_plane_service=control_plane_service,
        schema_service=StubSchemaService(),
    )
    return VoltageHubMCPAdapter(runtime), metrics_service, control_plane_service


def test_registration_exposes_six_tools_and_four_resources() -> None:
    adapter, _, _ = _build_adapter()

    assert [spec.name for spec in tool_specs(adapter)] == [
        "get_load_trends",
        "get_generation_mix",
        "get_top_demand_regions",
        "check_data_freshness",
        "get_anomalies",
        "get_pipeline_status",
    ]
    assert [spec.uri for spec in resource_specs(adapter)] == [
        "schema://grid-metrics",
        "status://data-quality",
        "schema://regions",
        "schema://energy-sources",
    ]


def test_get_load_trends_normalizes_region_name_and_shapes_envelope() -> None:
    adapter, metrics_service, _ = _build_adapter()
    metrics_service.load_rows = [
        LoadMetricDailyRecord(
            region="ERCO",
            region_name="ERCOT",
            observation_date=date(2026, 3, 28),
            avg_load=10.0,
            min_load=5.0,
            max_load=20.0,
            total_load=240.0,
            unit="megawatthours",
        )
    ]

    payload = adapter.get_load_trends(
        region="ercot",
        start_date=date(2026, 3, 28),
        end_date=date(2026, 3, 28),
        time_granularity="daily",
    )

    assert payload["summary"]["region_scope"] == ["ERCO"]
    assert payload["metadata"]["source_tables"][0] == "marts.agg_load_daily"
    assert payload["data"][0]["region_name"] == "ERCOT"
    assert metrics_service.load_calls[0]["region"] == "ERCO"


def test_get_load_trends_rejects_unknown_region_with_hint() -> None:
    adapter, _, _ = _build_adapter()

    payload = adapter.get_load_trends(
        region="unknown",
        start_date=date(2026, 3, 28),
        end_date=date(2026, 3, 28),
    )

    assert payload["error"]["code"] == "validation_error"
    assert "canonical region code" in payload["error"]["hint"]


def test_get_load_trends_rejects_hourly_window_over_seven_days() -> None:
    adapter, _, _ = _build_adapter()

    payload = adapter.get_load_trends(
        region="ERCO",
        start_date=date(2026, 3, 20),
        end_date=date(2026, 3, 28),
        time_granularity="hourly",
    )

    assert payload["error"]["code"] == "validation_error"
    assert "7 calendar days" in payload["error"]["message"]


def test_get_generation_mix_adds_row_level_percentages() -> None:
    adapter, metrics_service, _ = _build_adapter()
    metrics_service.generation_rows = [
        GenerationMixRecord(
            region="ERCO",
            region_name="ERCOT",
            observation_date=date(2026, 3, 28),
            energy_source="WND",
            daily_total_generation=75.0,
            unit="megawatthours",
        ),
        GenerationMixRecord(
            region="ERCO",
            region_name="ERCOT",
            observation_date=date(2026, 3, 28),
            energy_source="SUN",
            daily_total_generation=25.0,
            unit="megawatthours",
        ),
    ]

    payload = adapter.get_generation_mix(
        region="ERCO",
        start_date=date(2026, 3, 28),
        end_date=date(2026, 3, 28),
        include_percentages=True,
    )

    assert payload["data"][0]["generation_share_pct"] == 75.0
    assert payload["data"][1]["generation_share_pct"] == 25.0
    assert "generation_share_pct" in payload["highlights"][1]


def test_get_top_demand_regions_enforces_validation_first_row_budget() -> None:
    adapter, _, _ = _build_adapter()

    payload = adapter.get_top_demand_regions(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 3, 31),
        top_n=10,
    )

    assert payload["error"]["code"] == "validation_error"
    assert "row budget" in payload["error"]["message"]


def test_get_anomalies_truncates_and_marks_metadata() -> None:
    adapter, _, control_plane_service = _build_adapter()
    control_plane_service.anomaly_rows = [
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
        for index in range(ANOMALIES_MAX_ROWS + 5)
    ]

    payload = adapter.get_anomalies()

    assert len(payload["data"]) == ANOMALIES_MAX_ROWS
    assert payload["metadata"]["result_truncated"] is True
    assert payload["metadata"]["row_limit_applied"] == ANOMALIES_MAX_ROWS


def test_valid_empty_results_return_success_envelope() -> None:
    adapter, metrics_service, _ = _build_adapter()
    metrics_service.generation_rows = []

    payload = adapter.get_generation_mix(
        region="CISO",
        start_date=date(2026, 3, 28),
        end_date=date(2026, 3, 28),
    )

    assert payload["data"] == []
    assert payload["summary"]["main_takeaway"] == "No records found for the requested filters."
    assert payload["metadata"]["result_truncated"] is False


def test_schema_grid_metrics_resource_is_machine_readable() -> None:
    adapter, _, _ = _build_adapter()

    payload = adapter.schema_grid_metrics()

    assert payload["tools"]["get_load_trends"]["limits"]["hourly_max_days"] == 7
    assert payload["tools"]["get_generation_mix"]["derived_fields"] == ["generation_share_pct"]
    assert payload["available_date_bounds"]["start_date"] == "2026-03-20"


def test_status_data_quality_resource_anchors_operational_context() -> None:
    adapter, _, _ = _build_adapter()

    payload = adapter.status_data_quality()

    assert payload["freshness"]["freshness_status"] == "stale"
    assert payload["pipeline_status"]["pipeline_name"] == "eia_grid_batch"
    assert payload["anomaly_summary"]["flagged_anomaly_count_last_7_days"] == 4
