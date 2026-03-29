from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
from google.cloud import bigquery


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = PROJECT_ROOT / "airflow" / "dags" / "eia_grid_batch_tasks.py"
FIXTURE_PATH = PROJECT_ROOT / "tests" / "fixtures" / "eia_response.json"


def _load_tasks_module():
    spec = importlib.util.spec_from_file_location("eia_grid_batch_tasks", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


tasks = _load_tasks_module()


@pytest.fixture
def eia_response_payload() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def raw_payload() -> dict[str, object]:
    return {
        "_batch_id": "20260327T000000_20260327T010000",
        "_source_url": "multiple",
        "_ingestion_timestamp": "2026-03-27T01:05:00+00:00",
        "batch_date": "2026-03-27",
        "data_interval_start": "2026-03-27T00:00:00+00:00",
        "data_interval_end": "2026-03-27T01:00:00+00:00",
        "response": {
            "data": [
                {
                    "respondent": "MISO",
                    "respondent-name": "Midcontinent ISO",
                    "type": "D",
                    "type-name": "Demand",
                    "value": "1234.5",
                    "value-units": "megawatthours",
                    "period": "2026-03-27T00",
                    "__row_kind": "region",
                    "__source_url": "https://example.test/region",
                },
                {
                    "respondent": "MISO",
                    "respondent-name": "Midcontinent ISO",
                    "fueltype": "NG",
                    "type-name": "Natural Gas",
                    "value": "456.7",
                    "value-units": "megawatthours",
                    "period": "2026-03-27T00",
                    "__row_kind": "fuel_type",
                    "__source_url": "https://example.test/fuel",
                },
            ]
        },
    }


class FakeResponse:
    def __init__(self, *, status_code: int = 200, payload=None, url: str = "https://example.test"):
        self.status_code = status_code
        self._payload = payload
        self.url = url

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status={self.status_code}", response=self)


class SequenceSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def get(self, endpoint, params=None, timeout=None):
        self.calls.append(
            {
                "endpoint": endpoint,
                "params": dict(params or {}),
                "timeout": timeout,
            }
        )
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_extract_grid_batch_builds_expected_requests(eia_response_payload):
    session = SequenceSession(
        [
            FakeResponse(payload=eia_response_payload, url=tasks.REGION_DATA_ENDPOINT + "?offset=0"),
            FakeResponse(payload=eia_response_payload, url=tasks.FUEL_TYPE_DATA_ENDPOINT + "?offset=0"),
        ]
    )

    result = tasks.extract_grid_batch(
        "2026-03-27T00:00:00+00:00",
        "2026-03-27T01:00:00+00:00",
        api_key="test-key",
        session=session,
    )

    assert len(session.calls) == 2
    assert [call["endpoint"] for call in session.calls] == [
        tasks.REGION_DATA_ENDPOINT,
        tasks.FUEL_TYPE_DATA_ENDPOINT,
    ]
    for call in session.calls:
        assert call["params"]["api_key"] == "test-key"
        assert call["params"]["start"] == "2026-03-27T00"
        assert call["params"]["end"] == "2026-03-27T01"
        assert call["params"]["offset"] == 0
        assert call["timeout"] == (120, 300)

    assert result["batch_date"] == "2026-03-27"
    assert result["_batch_id"] == "20260327T000000_20260327T010000"
    assert result["_source_url"] == "multiple"
    assert result["response"]["total"] == 2
    assert {row["__row_kind"] for row in result["response"]["data"]} == {"region", "fuel_type"}


@pytest.mark.parametrize(
    ("responses", "expected_message", "expected_sleep_calls"),
    [
        (
            [
                FakeResponse(status_code=429, payload={"response": {"data": [], "total": 0}}),
                FakeResponse(payload={"response": {"data": [{"value": "1"}], "total": 1}}),
            ],
            None,
            [60],
        ),
        (
            [
                FakeResponse(status_code=503, payload={"response": {"data": [], "total": 0}}),
                FakeResponse(payload={"response": {"data": [{"value": "1"}], "total": 1}}),
            ],
            None,
            [120],
        ),
        (
            [requests.Timeout(), FakeResponse(payload={"response": {"data": [{"value": "1"}], "total": 1}})],
            None,
            [120],
        ),
        (
            [FakeResponse(payload={"unexpected": []})],
            "EIA response is missing the response object",
            [],
        ),
    ],
)
def test_request_retry_and_validation_behavior(
    monkeypatch,
    responses,
    expected_message,
    expected_sleep_calls,
):
    sleep_calls = []
    monkeypatch.setattr(tasks.time, "sleep", sleep_calls.append)
    session = SequenceSession(responses)

    if expected_message is None:
        response = tasks._request_with_retries(
            session,
            tasks.REGION_DATA_ENDPOINT,
            {"length": 5000},
        )
        assert isinstance(response, FakeResponse)
    else:
        with pytest.raises(tasks.ExtractionError, match=expected_message):
            tasks._fetch_endpoint_rows(
                session,
                tasks.REGION_DATA_ENDPOINT,
                {"length": 5000},
                row_kind="region",
            )

    assert sleep_calls == expected_sleep_calls


def test_extract_grid_batch_rejects_empty_response():
    empty_payload = {"response": {"data": [], "total": 0}}
    session = SequenceSession(
        [
            FakeResponse(payload=empty_payload, url=tasks.REGION_DATA_ENDPOINT + "?offset=0"),
            FakeResponse(payload=empty_payload, url=tasks.FUEL_TYPE_DATA_ENDPOINT + "?offset=0"),
        ]
    )

    with pytest.raises(tasks.ExtractionError, match="contained no rows"):
        tasks.extract_grid_batch(
            datetime(2026, 3, 27, 0, 0, tzinfo=UTC),
            datetime(2026, 3, 27, 1, 0, tzinfo=UTC),
            api_key="test-key",
            session=session,
        )


def test_land_raw_to_gcs_uploads_ndjson_to_expected_path(raw_payload):
    uploaded = {}

    class FakeBlob:
        def __init__(self, path):
            self.path = path

        def upload_from_string(self, payload, content_type):
            uploaded["path"] = self.path
            uploaded["payload"] = payload
            uploaded["content_type"] = content_type

    class FakeBucket:
        def blob(self, path):
            return FakeBlob(path)

    class FakeStorageClient:
        def bucket(self, name):
            uploaded["bucket"] = name
            return FakeBucket()

    uri = tasks.land_raw_to_gcs(
        raw_payload,
        bucket_name="voltage-hub-raw",
        storage_client=FakeStorageClient(),
    )

    assert (
        uri
        == "gs://voltage-hub-raw/voltage-hub/raw/year=2026/month=03/day=27/"
        "window=2026-03-27T00:00:00+00:00/batch.json"
    )
    assert uploaded["bucket"] == "voltage-hub-raw"
    assert uploaded["path"] == (
        "voltage-hub/raw/year=2026/month=03/day=27/"
        "window=2026-03-27T00:00:00+00:00/batch.json"
    )
    assert uploaded["content_type"] == "application/json"

    rows = [json.loads(line) for line in uploaded["payload"].splitlines()]
    assert len(rows) == 2
    assert rows[0]["type"] == "D"
    assert rows[0]["fueltype"] is None
    assert rows[1]["type"] == "generation"
    assert rows[1]["fueltype"] == "NG"
    assert rows[1]["_source_url"] == "https://example.test/fuel"


def test_load_to_bq_raw_uses_expected_load_configuration(raw_payload):
    captured = {}

    class FakeLoadJob:
        def result(self):
            return SimpleNamespace(job_id="job-123", output_rows=42)

    class FakeBigQueryClient:
        def load_table_from_uri(self, gcs_uri, destination_table, job_config):
            captured["gcs_uri"] = gcs_uri
            captured["destination_table"] = destination_table
            captured["job_config"] = job_config
            return FakeLoadJob()

    result = tasks.load_to_bq_raw(
        "gs://voltage-hub-raw/voltage-hub/raw/year=2026/month=03/day=27/window=2026-03-27T00:00:00+00:00/batch.json",
        raw_payload,
        project_id="voltage-hub-dev",
        dataset_name="raw",
        bq_client=FakeBigQueryClient(),
    )

    assert result == {
        "destination_table": "voltage-hub-dev.raw.eia_grid_batch$20260327",
        "job_id": "job-123",
        "output_rows": 42,
        "gcs_uri": "gs://voltage-hub-raw/voltage-hub/raw/year=2026/month=03/day=27/window=2026-03-27T00:00:00+00:00/batch.json",
    }

    job_config = captured["job_config"]
    assert captured["destination_table"] == "voltage-hub-dev.raw.eia_grid_batch$20260327"
    assert job_config.source_format == bigquery.SourceFormat.NEWLINE_DELIMITED_JSON
    assert job_config.write_disposition == bigquery.WriteDisposition.WRITE_TRUNCATE
    assert job_config.time_partitioning.type_ == bigquery.TimePartitioningType.DAY
    assert job_config.time_partitioning.field == "batch_date"
    assert [field.name for field in job_config.schema] == [
        "respondent",
        "respondent_name",
        "type",
        "type_name",
        "value",
        "value_units",
        "period",
        "fueltype",
        "fueltype_name",
        "batch_date",
        "_batch_id",
        "_source_url",
        "_ingestion_timestamp",
    ]


@pytest.mark.parametrize(
    ("timestamp_value", "expected_status"),
    [
        (datetime(2026, 3, 27, 5, 0, tzinfo=UTC), "fresh"),
        (datetime(2026, 3, 26, 23, 59, 59, tzinfo=UTC), "stale"),
        (None, "unknown"),
    ],
)
def test_freshness_status_uses_documented_threshold(timestamp_value, expected_status):
    checked_at = datetime(2026, 3, 27, 11, 0, tzinfo=UTC)

    assert tasks._freshness_status(timestamp_value, checked_at) == expected_status


def test_build_freshness_row_records_both_freshness_signals(monkeypatch):
    checked_at = datetime(2026, 3, 27, 11, 0, tzinfo=UTC)
    monkeypatch.setenv("GCP_PROJECT_ID", "voltage-hub-dev")

    class FakeBigQueryClient:
        def query(self, query):
            return SimpleNamespace(
                result=lambda: iter(
                    [
                        SimpleNamespace(
                            pipeline_freshness_timestamp=datetime(
                                2026, 3, 27, 8, 0, tzinfo=UTC
                            ),
                            data_freshness_timestamp=datetime(
                                2026, 3, 27, 4, 30, tzinfo=UTC
                            ),
                        )
                    ]
                )
            )

    freshness_row = tasks._build_freshness_row(
        client=FakeBigQueryClient(),
        run_id="manual__2026-03-27T11:00:00+00:00",
        checked_at=checked_at,
    )

    assert freshness_row == {
        "run_id": "manual__2026-03-27T11:00:00+00:00",
        "pipeline_freshness_timestamp": "2026-03-27T08:00:00+00:00",
        "data_freshness_timestamp": "2026-03-27T04:30:00+00:00",
        "pipeline_freshness_status": "fresh",
        "data_freshness_status": "stale",
        "checked_at": "2026-03-27T11:00:00+00:00",
    }


def test_check_anomalies_is_warning_only_when_internal_query_fails(monkeypatch):
    monkeypatch.setenv("GCP_PROJECT_ID", "voltage-hub-dev")
    monkeypatch.setattr(tasks, "_build_bigquery_client", lambda: SimpleNamespace())
    monkeypatch.setattr(tasks, "_ensure_meta_tables", lambda client: None)
    monkeypatch.setattr(
        tasks,
        "_get_affected_observation_dates",
        lambda client, batch_date: ["2026-03-27"],
    )
    monkeypatch.setattr(
        tasks,
        "_build_anomaly_rows",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    result = tasks.check_anomalies(
        data_interval_start="2026-03-27T00:00:00+00:00",
        run_id="manual__2026-03-27T01:00:00+00:00",
    )

    assert result["status"] == "warning"
    assert result["task"] == "check_anomalies"
    assert result["rows_inserted"] == 0
    assert result["affected_dates"] == []
    assert "boom" in result["error"]


def test_record_run_metrics_falls_back_to_unknown_freshness(monkeypatch):
    inserted_rows: list[tuple[str, list[dict[str, object]]]] = []

    monkeypatch.setenv("GCP_PROJECT_ID", "voltage-hub-dev")
    monkeypatch.setattr(tasks, "_build_bigquery_client", lambda: SimpleNamespace())
    monkeypatch.setattr(tasks, "_ensure_meta_tables", lambda client: None)
    monkeypatch.setattr(
        tasks,
        "_build_freshness_row",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("freshness unavailable")),
    )
    monkeypatch.setattr(
        tasks,
        "_insert_rows_json",
        lambda *, client, table_id, rows: inserted_rows.append((table_id, rows)),
    )
    monkeypatch.setattr(tasks, "_determine_run_status", lambda context: "success")
    monkeypatch.setattr(tasks, "_task_state", lambda context, task_id: "success")
    monkeypatch.setattr(
        tasks,
        "_read_dbt_run_results",
        lambda: {
            "models_passed": 4,
            "tests_passed": 8,
            "tests_failed": 0,
            "bytes_processed": 12345,
        },
    )

    context = {
        "run_id": "manual__2026-03-27T01:00:00+00:00",
        "dag": SimpleNamespace(dag_id="eia_grid_batch"),
        "dag_run": SimpleNamespace(start_date=datetime(2026, 3, 27, 1, 0, tzinfo=UTC)),
        "data_interval_start": "2026-03-27T00:00:00+00:00",
        "data_interval_end": "2026-03-27T01:00:00+00:00",
        "logical_date": datetime(2026, 3, 27, 1, 0, tzinfo=UTC),
        "ti": SimpleNamespace(
            xcom_pull=lambda task_ids: {"output_rows": 42}
            if task_ids == "load_to_bq_raw"
            else {}
        ),
    }

    result = tasks.record_run_metrics(**context)

    freshness_insert = next(
        rows for table_id, rows in inserted_rows if table_id.endswith(".freshness_log")
    )
    freshness_row = freshness_insert[0]
    assert freshness_row["pipeline_freshness_timestamp"] is None
    assert freshness_row["data_freshness_timestamp"] is None
    assert freshness_row["pipeline_freshness_status"] == "unknown"
    assert freshness_row["data_freshness_status"] == "unknown"

    run_metrics_insert = next(
        rows for table_id, rows in inserted_rows if table_id.endswith(".run_metrics")
    )
    run_metrics_row = run_metrics_insert[0]
    assert run_metrics_row["rows_loaded"] == 42
    assert run_metrics_row["status"] == "success"
    assert run_metrics_row["dbt_models_passed"] == 4
    assert run_metrics_row["dbt_tests_passed"] == 8

    assert result["freshness_status"] == {
        "pipeline": "unknown",
        "data": "unknown",
    }
    assert result["rows_loaded"] == 42


def test_record_run_metrics_persists_failed_status_when_upstream_failed(monkeypatch):
    inserted_rows: list[tuple[str, list[dict[str, object]]]] = []

    monkeypatch.setenv("GCP_PROJECT_ID", "voltage-hub-dev")
    monkeypatch.setattr(tasks, "_build_bigquery_client", lambda: SimpleNamespace())
    monkeypatch.setattr(tasks, "_ensure_meta_tables", lambda client: None)
    monkeypatch.setattr(
        tasks,
        "_build_freshness_row",
        lambda **kwargs: {
            "run_id": "manual__2026-03-27T01:00:00+00:00",
            "pipeline_freshness_timestamp": "2026-03-27T00:55:00+00:00",
            "data_freshness_timestamp": "2026-03-27T00:00:00+00:00",
            "pipeline_freshness_status": "fresh",
            "data_freshness_status": "fresh",
            "checked_at": "2026-03-27T01:05:00+00:00",
        },
    )
    monkeypatch.setattr(
        tasks,
        "_insert_rows_json",
        lambda *, client, table_id, rows: inserted_rows.append((table_id, rows)),
    )
    monkeypatch.setattr(tasks, "_determine_run_status", lambda context: "failed")
    monkeypatch.setattr(
        tasks,
        "_task_state",
        lambda context, task_id: "failed" if task_id == "dbt_build" else "success",
    )
    monkeypatch.setattr(
        tasks,
        "_empty_dbt_run_results",
        lambda: {
            "models_passed": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "bytes_processed": 0,
        },
    )

    context = {
        "run_id": "manual__2026-03-27T01:00:00+00:00",
        "dag": SimpleNamespace(dag_id="eia_grid_batch"),
        "dag_run": SimpleNamespace(start_date=datetime(2026, 3, 27, 1, 0, tzinfo=UTC)),
        "data_interval_start": "2026-03-27T00:00:00+00:00",
        "data_interval_end": "2026-03-27T01:00:00+00:00",
        "logical_date": datetime(2026, 3, 27, 1, 0, tzinfo=UTC),
        "ti": SimpleNamespace(
            xcom_pull=lambda task_ids: {"output_rows": 0}
            if task_ids == "load_to_bq_raw"
            else {}
        ),
    }

    result = tasks.record_run_metrics(**context)

    run_metrics_insert = next(
        rows for table_id, rows in inserted_rows if table_id.endswith(".run_metrics")
    )
    run_metrics_row = run_metrics_insert[0]
    assert run_metrics_row["status"] == "failed"
    assert run_metrics_row["dbt_models_passed"] == 0
    assert run_metrics_row["dbt_tests_passed"] == 0
    assert run_metrics_row["dbt_tests_failed"] == 0
    assert result["run_status"] == "failed"
