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
