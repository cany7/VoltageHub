from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from google.cloud import bigquery

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SERVING_ROOT = PROJECT_ROOT / "serving-fastapi"
if str(SERVING_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVING_ROOT))

from app.main import create_app  # noqa: E402

pytestmark = pytest.mark.integration

RUN_SERVING_TESTS = os.environ.get("VOLTAGE_HUB_RUN_PIPELINE_TESTS") == "1"


def _require_serving_test_mode() -> None:
    if not RUN_SERVING_TESTS:
        pytest.skip(
            "Set VOLTAGE_HUB_RUN_PIPELINE_TESTS=1 to execute real serving API integration tests."
        )


@pytest.fixture(scope="module")
def project_id() -> str:
    _require_serving_test_mode()
    value = os.environ.get("GCP_PROJECT_ID")
    if not value:
        pytest.skip("GCP_PROJECT_ID is required for serving integration tests.")
    return value


@pytest.fixture(scope="module")
def datasets() -> dict[str, str]:
    return {
        "marts": os.environ.get("BQ_DATASET_MARTS", "marts"),
        "meta": os.environ.get("BQ_DATASET_META", "meta"),
    }


@pytest.fixture(scope="module", autouse=True)
def host_credentials_path() -> None:
    _require_serving_test_mode()
    configured_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if configured_path and Path(configured_path).exists():
        return

    local_key_path = PROJECT_ROOT / "keys" / "service-account.json"
    if not local_key_path.exists():
        pytest.skip("No local service-account key is available for host-side integration tests.")

    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(local_key_path)


@pytest.fixture(scope="module")
def bigquery_client(project_id: str) -> bigquery.Client:
    return bigquery.Client(project=project_id)


@pytest.fixture(scope="module")
def client(project_id: str) -> TestClient:
    _ = project_id
    return TestClient(create_app())


@pytest.fixture(scope="module")
def load_context(
    bigquery_client: bigquery.Client,
    project_id: str,
    datasets: dict[str, str],
) -> dict[str, Any]:
    row = _one_row(
        bigquery_client,
        f"""
        select
            region,
            observation_date,
            total_load
        from `{project_id}.{datasets["marts"]}.agg_load_daily`
        order by observation_date desc, region asc
        limit 1
        """,
    )
    if row is None:
        pytest.skip("agg_load_daily has no rows for serving integration tests.")
    return row


@pytest.fixture(scope="module")
def generation_mix_context(
    bigquery_client: bigquery.Client,
    project_id: str,
    datasets: dict[str, str],
) -> dict[str, Any]:
    row = _one_row(
        bigquery_client,
        f"""
        select
            region,
            observation_date,
            energy_source,
            daily_total_generation
        from `{project_id}.{datasets["marts"]}.agg_generation_mix`
        order by observation_date desc, region asc, energy_source asc
        limit 1
        """,
    )
    if row is None:
        pytest.skip("agg_generation_mix has no rows for serving integration tests.")
    return row


@pytest.fixture(scope="module")
def top_regions_context(
    bigquery_client: bigquery.Client,
    project_id: str,
    datasets: dict[str, str],
) -> dict[str, Any]:
    row = _one_row(
        bigquery_client,
        f"""
        select
            observation_date,
            region,
            rank,
            daily_total_load
        from `{project_id}.{datasets["marts"]}.agg_top_regions`
        order by observation_date desc, rank asc
        limit 1
        """,
    )
    if row is None:
        pytest.skip("agg_top_regions has no rows for serving integration tests.")
    return row


def test_health_endpoint_returns_healthy_without_bigquery_query(client: TestClient) -> None:
    response = client.get("/health", headers={"x-request-id": "serving-int-health"})

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}
    assert response.headers["x-request-id"] == "serving-int-health"


def test_control_plane_endpoints_return_real_meta_records(
    client: TestClient,
) -> None:
    freshness_response = client.get("/freshness")
    pipeline_response = client.get("/pipeline/status")
    anomalies_response = client.get("/anomalies")

    assert freshness_response.status_code == 200
    freshness_payload = freshness_response.json()
    assert {
        "pipeline_freshness_timestamp",
        "data_freshness_timestamp",
        "pipeline_freshness_status",
        "data_freshness_status",
        "freshness_status",
        "checked_at",
    } <= freshness_payload.keys()

    assert pipeline_response.status_code == 200
    pipeline_payload = pipeline_response.json()
    assert {
        "pipeline_name",
        "last_successful_window_start",
        "last_successful_window_end",
        "last_successful_run_id",
        "updated_at",
    } <= pipeline_payload.keys()

    assert anomalies_response.status_code == 200
    assert isinstance(anomalies_response.json(), list)


def test_load_metrics_endpoint_returns_real_precomputed_rows_and_metadata(
    client: TestClient,
    load_context: dict[str, Any],
) -> None:
    observation_date = load_context["observation_date"].isoformat()
    response = client.get(
        "/metrics/load",
        params={
            "region": load_context["region"],
            "start_date": observation_date,
            "end_date": observation_date,
            "granularity": "daily",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]
    assert payload["data"][0]["region"] == load_context["region"]
    assert payload["data"][0]["observation_date"] == observation_date
    assert payload["data"][0]["total_load"] == pytest.approx(load_context["total_load"])
    _assert_response_metadata(payload["metadata"])


def test_generation_mix_endpoint_returns_real_precomputed_rows_and_metadata(
    client: TestClient,
    generation_mix_context: dict[str, Any],
) -> None:
    observation_date = generation_mix_context["observation_date"].isoformat()
    response = client.get(
        "/metrics/generation-mix",
        params={
            "region": generation_mix_context["region"],
            "start_date": observation_date,
            "end_date": observation_date,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]
    assert payload["data"][0]["region"] == generation_mix_context["region"]
    assert payload["data"][0]["observation_date"] == observation_date
    assert payload["data"][0]["energy_source"] == generation_mix_context["energy_source"]
    assert payload["data"][0]["daily_total_generation"] == pytest.approx(
        generation_mix_context["daily_total_generation"]
    )
    _assert_response_metadata(payload["metadata"])


def test_top_regions_endpoint_returns_real_ranked_rows_and_metadata(
    client: TestClient,
    top_regions_context: dict[str, Any],
) -> None:
    observation_date = top_regions_context["observation_date"].isoformat()
    response = client.get(
        "/metrics/top-regions",
        params={
            "start_date": observation_date,
            "end_date": observation_date,
            "limit": top_regions_context["rank"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]
    assert payload["data"][0]["observation_date"] == observation_date
    assert payload["data"][0]["region"] == top_regions_context["region"]
    assert payload["data"][0]["rank"] == top_regions_context["rank"]
    assert payload["data"][0]["daily_total_load"] == pytest.approx(
        top_regions_context["daily_total_load"]
    )
    _assert_response_metadata(payload["metadata"])


def test_metric_endpoints_return_structured_validation_errors(client: TestClient) -> None:
    response = client.get(
        "/metrics/load",
        params={
            "region": "ERCO",
            "start_date": "2026-03-29",
            "end_date": "2026-03-28",
            "granularity": "daily",
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "error": "validation_error",
        "detail": "start_date must be less than or equal to end_date",
    }


def _one_row(client: bigquery.Client, query: str) -> dict[str, Any] | None:
    rows = list(client.query(query).result())
    if not rows:
        return None
    return dict(rows[0].items())


def _assert_response_metadata(metadata: dict[str, Any]) -> None:
    assert {"data_as_of", "pipeline_run_id", "freshness_status"} <= metadata.keys()
    assert metadata["freshness_status"] in {"fresh", "stale", "unknown"}

