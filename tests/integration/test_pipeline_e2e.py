from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from google.cloud import bigquery, storage

"""Real end-to-end pipeline tests.

Important Airflow timing note:
- ``airflow dags test <dag_id> <timestamp>`` takes the DAG run logical execution timestamp.
- For this hourly DAG, that timestamp aligns to ``data_interval_end``.
- The actual extraction window start is therefore one hour earlier unless explicitly overridden.
"""

pytestmark = pytest.mark.integration

DAG_ID = "eia_grid_batch"
RUN_PIPELINE_TESTS = os.environ.get("VOLTAGE_HUB_RUN_PIPELINE_TESTS") == "1"
RUN_FAILURE_PATH_PIPELINE_TESTS = (
    os.environ.get("VOLTAGE_HUB_RUN_FAILURE_PATH_PIPELINE_TESTS") == "1"
)


def _require_pipeline_test_mode() -> None:
    if not RUN_PIPELINE_TESTS:
        pytest.skip(
            "Set VOLTAGE_HUB_RUN_PIPELINE_TESTS=1 to execute real end-to-end pipeline tests."
        )


@pytest.fixture(scope="module")
def project_id() -> str:
    _require_pipeline_test_mode()
    value = os.environ.get("GCP_PROJECT_ID")
    if not value:
        pytest.skip("GCP_PROJECT_ID is required for integration tests.")
    return value


@pytest.fixture(scope="module")
def bucket_name() -> str:
    _require_pipeline_test_mode()
    value = os.environ.get("GCS_BUCKET_NAME")
    if not value:
        pytest.skip("GCS_BUCKET_NAME is required for integration tests.")
    return value


@pytest.fixture(scope="module")
def datasets() -> dict[str, str]:
    return {
        "raw": os.environ.get("BQ_DATASET_RAW", "raw"),
        "staging": os.environ.get("BQ_DATASET_STAGING", "staging"),
        "marts": os.environ.get("BQ_DATASET_MARTS", "marts"),
        "meta": os.environ.get("BQ_DATASET_META", "meta"),
    }


@pytest.fixture(scope="module", autouse=True)
def host_credentials_path() -> None:
    _require_pipeline_test_mode()
    configured_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if configured_path and Path(configured_path).exists():
        return

    local_key_path = Path(__file__).resolve().parents[2] / "keys" / "service-account.json"
    if not local_key_path.exists():
        pytest.skip("No local service-account key is available for host-side integration tests.")

    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(local_key_path)


@pytest.fixture(scope="module")
def bigquery_client(project_id: str) -> bigquery.Client:
    return bigquery.Client(project=project_id)


@pytest.fixture(scope="module")
def storage_client(project_id: str) -> storage.Client:
    return storage.Client(project=project_id)


@pytest.fixture(scope="module")
def airflow_execution_date() -> datetime:
    raw_value = os.environ.get(
        "VOLTAGE_HUB_TEST_EXECUTION_DATE",
        "2026-03-27T01:00:00+00:00",
    )
    return _coerce_datetime(raw_value)


@pytest.fixture(scope="module")
def extraction_window_end(airflow_execution_date: datetime) -> datetime:
    raw_value = os.environ.get("VOLTAGE_HUB_TEST_WINDOW_END")
    if raw_value:
        return _coerce_datetime(raw_value)
    return airflow_execution_date


@pytest.fixture(scope="module")
def extraction_window_start(extraction_window_end: datetime) -> datetime:
    raw_value = os.environ.get("VOLTAGE_HUB_TEST_WINDOW_START")
    if raw_value:
        return _coerce_datetime(raw_value)
    return extraction_window_end - timedelta(hours=1)


@pytest.fixture(scope="module")
def pipeline_run_context(
    bigquery_client: bigquery.Client,
    airflow_execution_date: datetime,
    extraction_window_start: datetime,
    extraction_window_end: datetime,
    project_id: str,
    datasets: dict[str, str],
) -> dict[str, Any]:
    _run_airflow_dag_test(airflow_execution_date)
    affected_dates = _fetch_affected_dates(
        client=bigquery_client,
        project_id=project_id,
        raw_dataset=datasets["raw"],
        batch_date=extraction_window_start.date().isoformat(),
    )
    return {
        "airflow_execution_date": airflow_execution_date,
        "extraction_window_start": extraction_window_start,
        "extraction_window_end": extraction_window_end,
        "batch_date": extraction_window_start.date().isoformat(),
        "affected_dates": affected_dates,
    }


@pytest.fixture(scope="module")
def isolated_failure_datasets(
    bigquery_client: bigquery.Client,
    project_id: str,
    datasets: dict[str, str],
    pipeline_run_context: dict[str, Any],
) -> dict[str, str]:
    suffix = datetime.now(tz=UTC).strftime("%Y%m%d%H%M%S")
    isolated_datasets = {
        key: f"{dataset_name}_failure_{suffix}"
        for key, dataset_name in datasets.items()
    }

    source_dataset = bigquery_client.get_dataset(f"{project_id}.{datasets['raw']}")
    for dataset_name in isolated_datasets.values():
        dataset = bigquery.Dataset(f"{project_id}.{dataset_name}")
        dataset.location = source_dataset.location
        bigquery_client.create_dataset(dataset, exists_ok=True)

    bigquery_client.query(
        f"""
        create or replace table `{project_id}.{isolated_datasets["raw"]}.eia_grid_batch` as
        select *
        from `{project_id}.{datasets["raw"]}.eia_grid_batch`
        where batch_date = @batch_date
        """,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter(
                    "batch_date",
                    "DATE",
                    pipeline_run_context["batch_date"],
                ),
            ]
        ),
    ).result()

    copied_rows = _scalar_query(
        bigquery_client,
        f"""
        select count(*) as row_count
        from `{project_id}.{isolated_datasets["raw"]}.eia_grid_batch`
        """,
    )
    if copied_rows == 0:
        raise AssertionError("The isolated failure-path raw dataset must contain copied rows.")

    try:
        yield isolated_datasets
    finally:
        for dataset_name in isolated_datasets.values():
            bigquery_client.delete_dataset(
                f"{project_id}.{dataset_name}",
                delete_contents=True,
                not_found_ok=True,
            )


@pytest.fixture(scope="module")
def date_boundary_execution_date() -> datetime:
    raw_value = os.environ.get(
        "VOLTAGE_HUB_TEST_DATE_BOUNDARY_EXECUTION_DATE",
        "2026-03-27T00:00:00+00:00",
    )
    execution_date = _coerce_datetime(raw_value)
    window_start = execution_date - timedelta(hours=1)
    if execution_date.date() == window_start.date():
        pytest.skip(
            "VOLTAGE_HUB_TEST_DATE_BOUNDARY_EXECUTION_DATE must produce a UTC window that spans midnight."
        )
    return execution_date


@pytest.fixture(scope="module")
def date_boundary_run_context(
    bigquery_client: bigquery.Client,
    date_boundary_execution_date: datetime,
    project_id: str,
    datasets: dict[str, str],
) -> dict[str, Any]:
    extraction_window_end = date_boundary_execution_date
    extraction_window_start = extraction_window_end - timedelta(hours=1)
    _run_airflow_dag_test(date_boundary_execution_date)
    affected_dates = _fetch_affected_dates(
        client=bigquery_client,
        project_id=project_id,
        raw_dataset=datasets["raw"],
        batch_date=extraction_window_start.date().isoformat(),
    )
    return {
        "airflow_execution_date": date_boundary_execution_date,
        "extraction_window_start": extraction_window_start,
        "extraction_window_end": extraction_window_end,
        "batch_date": extraction_window_start.date().isoformat(),
        "affected_dates": affected_dates,
    }


def test_single_window_pipeline_run_populates_raw_gcs_and_marts(
    pipeline_run_context: dict[str, Any],
    storage_client: storage.Client,
    bucket_name: str,
    bigquery_client: bigquery.Client,
    project_id: str,
    datasets: dict[str, str],
) -> None:
    window_start = pipeline_run_context["extraction_window_start"]
    gcs_path = (
        "voltage-hub/raw/"
        f"year={window_start:%Y}/month={window_start:%m}/day={window_start:%d}/"
        f"window={window_start.isoformat()}/batch.json"
    )
    blob = storage_client.bucket(bucket_name).blob(gcs_path)
    assert blob.exists(storage_client)

    raw_count = _scalar_query(
        bigquery_client,
        f"""
        select count(*) as row_count
        from `{project_id}.{datasets["raw"]}.eia_grid_batch`
        where batch_date = @batch_date
        """,
        [
            bigquery.ScalarQueryParameter(
                "batch_date",
                "DATE",
                pipeline_run_context["batch_date"],
            )
        ],
    )
    assert raw_count > 0

    for table_name in (
        "stg_grid_metrics",
        "fct_grid_metrics",
        "agg_load_hourly",
        "agg_load_daily",
        "agg_generation_mix",
        "agg_top_regions",
    ):
        dataset_name = datasets["staging"] if table_name == "stg_grid_metrics" else datasets["marts"]
        row_count = _date_scoped_count(
            client=bigquery_client,
            project_id=project_id,
            dataset_name=dataset_name,
            table_name=table_name,
            affected_dates=pipeline_run_context["affected_dates"],
        )
        assert row_count > 0, f"{table_name} should contain rows for the affected dates"


def test_meta_tables_and_anomaly_results_are_populated(
    pipeline_run_context: dict[str, Any],
    bigquery_client: bigquery.Client,
    project_id: str,
    datasets: dict[str, str],
) -> None:
    state_row = next(
        bigquery_client.query(
            f"""
            select
                pipeline_name,
                last_successful_window_start,
                last_successful_window_end,
                last_successful_run_id
            from `{project_id}.{datasets["meta"]}.pipeline_state`
            where pipeline_name = 'eia_grid_batch'
            """
        ).result(),
        None,
    )
    assert state_row is not None
    assert state_row.last_successful_window_start == pipeline_run_context["extraction_window_start"]
    assert state_row.last_successful_window_end == pipeline_run_context["extraction_window_end"]
    assert state_row.last_successful_run_id

    metrics_row = next(
        bigquery_client.query(
            f"""
            select *
            from `{project_id}.{datasets["meta"]}.run_metrics`
            where window_start = @window_start and window_end = @window_end
            order by created_at desc
            limit 1
            """,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter(
                        "window_start",
                        "TIMESTAMP",
                        pipeline_run_context["extraction_window_start"],
                    ),
                    bigquery.ScalarQueryParameter(
                        "window_end",
                        "TIMESTAMP",
                        pipeline_run_context["extraction_window_end"],
                    ),
                ]
            ),
        ).result(),
        None,
    )
    assert metrics_row is not None
    assert metrics_row.rows_loaded > 0
    assert metrics_row.status == "success"

    freshness_row = next(
        bigquery_client.query(
            f"""
            select *
            from `{project_id}.{datasets["meta"]}.freshness_log`
            where run_id = @run_id
            order by checked_at desc
            limit 1
            """,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("run_id", "STRING", metrics_row.run_id),
                ]
            ),
        ).result(),
        None,
    )
    assert freshness_row is not None
    assert freshness_row.pipeline_freshness_timestamp is not None
    assert freshness_row.data_freshness_timestamp is not None
    assert freshness_row.pipeline_freshness_status in {"fresh", "stale", "unknown"}
    assert freshness_row.data_freshness_status in {"fresh", "stale", "unknown"}

    anomaly_count = _scalar_query(
        bigquery_client,
        f"""
        select count(*) as row_count
        from `{project_id}.{datasets["meta"]}.anomaly_results`
        where run_id = @run_id
        """,
        [bigquery.ScalarQueryParameter("run_id", "STRING", metrics_row.run_id)],
    )
    assert anomaly_count > 0


def test_date_boundary_window_rebuilds_both_affected_dates(
    date_boundary_run_context: dict[str, Any],
    bigquery_client: bigquery.Client,
    project_id: str,
    datasets: dict[str, str],
) -> None:
    affected_dates = date_boundary_run_context["affected_dates"]

    assert len(affected_dates) == 2
    assert affected_dates == sorted(affected_dates)
    assert affected_dates[0] != affected_dates[1]

    raw_count = _scalar_query(
        bigquery_client,
        f"""
        select count(*) as row_count
        from `{project_id}.{datasets["raw"]}.eia_grid_batch`
        where batch_date = @batch_date
        """,
        [
            bigquery.ScalarQueryParameter(
                "batch_date",
                "DATE",
                date_boundary_run_context["batch_date"],
            )
        ],
    )
    assert raw_count > 0

    for table_name in (
        "stg_grid_metrics",
        "fct_grid_metrics",
        "agg_load_hourly",
        "agg_load_daily",
        "agg_generation_mix",
        "agg_top_regions",
    ):
        dataset_name = datasets["staging"] if table_name == "stg_grid_metrics" else datasets["marts"]
        row_count = _date_scoped_count(
            client=bigquery_client,
            project_id=project_id,
            dataset_name=dataset_name,
            table_name=table_name,
            affected_dates=affected_dates,
        )
        assert row_count > 0, f"{table_name} should contain rows for both date-boundary partitions"


@pytest.mark.integration_failure
def test_pipeline_freshness_warn_path_can_be_exercised_with_stale_raw_partition(
    pipeline_run_context: dict[str, Any],
    bigquery_client: bigquery.Client,
    project_id: str,
    isolated_failure_datasets: dict[str, str],
) -> None:
    if not RUN_FAILURE_PATH_PIPELINE_TESTS:
        pytest.skip(
            "Set VOLTAGE_HUB_RUN_FAILURE_PATH_PIPELINE_TESTS=1 to run targeted freshness failure-path checks."
        )

    checked_at = datetime.now(tz=UTC)
    stale_timestamp = checked_at - timedelta(hours=7)
    _set_raw_ingestion_timestamp_for_batch(
        client=bigquery_client,
        project_id=project_id,
        raw_dataset=isolated_failure_datasets["raw"],
        batch_date=pipeline_run_context["batch_date"],
        ingestion_timestamp=stale_timestamp,
    )

    result = _run_dbt_source_freshness(isolated_failure_datasets)
    source_max_timestamp = _query_raw_max_ingestion_timestamp(
        client=bigquery_client,
        project_id=project_id,
        raw_dataset=isolated_failure_datasets["raw"],
    )
    if source_max_timestamp is None:
        raise AssertionError("The isolated failure-path raw source should contain ingestion timestamps.")

    source_age = checked_at - source_max_timestamp
    assert timedelta(hours=6) < source_age < timedelta(hours=12)

    assert result.returncode == 0

    batch_max_timestamp = _query_raw_max_ingestion_timestamp(
        client=bigquery_client,
        project_id=project_id,
        raw_dataset=isolated_failure_datasets["raw"],
        batch_date=pipeline_run_context["batch_date"],
    )
    assert batch_max_timestamp is not None
    assert checked_at - batch_max_timestamp > timedelta(hours=6)
    assert checked_at - batch_max_timestamp < timedelta(hours=12)


@pytest.mark.integration_failure
def test_pipeline_freshness_error_path_fails_source_freshness_command(
    pipeline_run_context: dict[str, Any],
    bigquery_client: bigquery.Client,
    project_id: str,
    isolated_failure_datasets: dict[str, str],
) -> None:
    if not RUN_FAILURE_PATH_PIPELINE_TESTS:
        pytest.skip(
            "Set VOLTAGE_HUB_RUN_FAILURE_PATH_PIPELINE_TESTS=1 to run targeted freshness failure-path checks."
        )

    checked_at = datetime.now(tz=UTC)
    stale_timestamp = checked_at - timedelta(hours=13)
    _set_raw_ingestion_timestamp_for_batch(
        client=bigquery_client,
        project_id=project_id,
        raw_dataset=isolated_failure_datasets["raw"],
        batch_date=pipeline_run_context["batch_date"],
        ingestion_timestamp=stale_timestamp,
    )

    result = _run_dbt_source_freshness(isolated_failure_datasets)
    source_max_timestamp = _query_raw_max_ingestion_timestamp(
        client=bigquery_client,
        project_id=project_id,
        raw_dataset=isolated_failure_datasets["raw"],
    )
    if source_max_timestamp is None:
        raise AssertionError("The isolated failure-path raw source should contain ingestion timestamps.")

    source_age = checked_at - source_max_timestamp
    assert source_age > timedelta(hours=12)

    assert result.returncode != 0
    combined_output = f"{result.stdout}\n{result.stderr}".lower()
    assert "freshness" in combined_output or "stale" in combined_output


@pytest.mark.integration_heavy
def test_idempotent_rerun_preserves_data_plane_outputs(
    pipeline_run_context: dict[str, Any],
    bigquery_client: bigquery.Client,
    project_id: str,
    datasets: dict[str, str],
) -> None:
    if not os.environ.get("VOLTAGE_HUB_RUN_HEAVY_PIPELINE_TESTS"):
        pytest.skip(
            "Set VOLTAGE_HUB_RUN_HEAVY_PIPELINE_TESTS=1 to run idempotent rerun validation."
        )

    # Assumption: establish the baseline with the same execution date under test so
    # earlier smoke scenarios that touched overlapping observation_date partitions
    # do not distort the idempotency comparison.
    _run_airflow_dag_test(pipeline_run_context["airflow_execution_date"])

    affected_dates = pipeline_run_context["affected_dates"]
    before_snapshot = _build_data_plane_snapshot(
        client=bigquery_client,
        project_id=project_id,
        datasets=datasets,
        batch_date=pipeline_run_context["batch_date"],
        affected_dates=affected_dates,
    )

    _run_airflow_dag_test(pipeline_run_context["airflow_execution_date"])

    after_snapshot = _build_data_plane_snapshot(
        client=bigquery_client,
        project_id=project_id,
        datasets=datasets,
        batch_date=pipeline_run_context["batch_date"],
        affected_dates=affected_dates,
    )

    assert after_snapshot == before_snapshot


@pytest.mark.integration_heavy
def test_backfill_windows_populate_outputs_for_each_window(
    bigquery_client: bigquery.Client,
    project_id: str,
    datasets: dict[str, str],
) -> None:
    if not os.environ.get("VOLTAGE_HUB_RUN_HEAVY_PIPELINE_TESTS"):
        pytest.skip(
            "Set VOLTAGE_HUB_RUN_HEAVY_PIPELINE_TESTS=1 to run backfill validation."
        )

    backfill_hours = _resolve_backfill_hours()
    backfill_end = _resolve_backfill_end_boundary()
    expected_window_starts = [
        backfill_end - timedelta(hours=offset)
        for offset in range(backfill_hours, 0, -1)
    ]
    backfill_start = expected_window_starts[0]
    backfill_started_at = datetime.now(tz=UTC)
    _run_airflow_backfill(backfill_start, backfill_end)

    expected_batch_dates = {window_start.date().isoformat() for window_start in expected_window_starts}
    expected_windows = [
        (window_start, window_start + timedelta(hours=1))
        for window_start in expected_window_starts
    ]
    assert len(expected_windows) == backfill_hours

    for batch_date in sorted(expected_batch_dates):
        raw_count = _scalar_query(
            bigquery_client,
            f"""
            select count(*) as row_count
            from `{project_id}.{datasets["raw"]}.eia_grid_batch`
            where batch_date = @batch_date
            """,
            [bigquery.ScalarQueryParameter("batch_date", "DATE", batch_date)],
        )
        assert raw_count > 0

    for window_start, window_end in expected_windows:
        run_metrics_count = _scalar_query(
            bigquery_client,
            f"""
            select count(*) as row_count
            from `{project_id}.{datasets["meta"]}.run_metrics`
            where run_id like 'backfill__%%'
              and created_at >= @backfill_started_at
              and window_start = @window_start
              and window_end = @window_end
            """,
            [
                bigquery.ScalarQueryParameter(
                    "backfill_started_at",
                    "TIMESTAMP",
                    backfill_started_at,
                ),
                bigquery.ScalarQueryParameter("window_start", "TIMESTAMP", window_start),
                bigquery.ScalarQueryParameter("window_end", "TIMESTAMP", window_end),
            ],
        )
        assert run_metrics_count > 0, (
            "run_metrics should contain a row for every backfilled window"
        )


def _run_airflow_dag_test(execution_date: datetime) -> None:
    _run_command(
        [
            "docker",
            "compose",
            "exec",
            "airflow-webserver",
            "airflow",
            "dags",
            "test",
            DAG_ID,
            execution_date.isoformat(),
        ]
    )


def _run_airflow_backfill(start: datetime, end: datetime) -> None:
    _run_command(
        [
            "docker",
            "compose",
            "exec",
            "airflow-webserver",
            "airflow",
            "dags",
            "backfill",
            DAG_ID,
            "--start-date",
            start.isoformat(),
            "--end-date",
            end.isoformat(),
            "--reset-dagruns",
            "--yes",
        ]
    )


def _run_dbt_source_freshness(
    datasets_override: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env_flags: list[str] = []
    if datasets_override is not None:
        for env_name, dataset_key in (
            ("BQ_DATASET_RAW", "raw"),
            ("BQ_DATASET_STAGING", "staging"),
            ("BQ_DATASET_MARTS", "marts"),
            ("BQ_DATASET_META", "meta"),
        ):
            env_flags.extend(["-e", f"{env_name}={datasets_override[dataset_key]}"])
    return _run_command_result(
        [
            "docker",
            "compose",
            "exec",
            *env_flags,
            "airflow-webserver",
            "dbt",
            "source",
            "freshness",
            "--project-dir",
            "/opt/airflow/dbt",
            "--profiles-dir",
            "/opt/airflow/dbt",
            "--target",
            "dev",
        ]
    )


def _run_command(command: list[str]) -> None:
    completed = _run_command_result(command)
    if completed.returncode != 0:
        raise AssertionError(
            "Command failed:\n"
            f"command={' '.join(command)}\n"
            f"stdout={completed.stdout}\n"
            f"stderr={completed.stderr}"
        )


def _run_command_result(command: list[str]) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed


def _fetch_affected_dates(
    *,
    client: bigquery.Client,
    project_id: str,
    raw_dataset: str,
    batch_date: str,
) -> list[str]:
    query = f"""
        with parsed_periods as (
            select
                coalesce(
                    safe.parse_timestamp('%Y-%m-%dT%H:%M:%E*S%Ez', period),
                    safe.parse_timestamp('%Y-%m-%dT%H', period),
                    safe.parse_timestamp('%Y-%m-%d', period)
                ) as observation_timestamp
            from `{project_id}.{raw_dataset}.eia_grid_batch`
            where batch_date = @batch_date
        )
        select distinct cast(date(observation_timestamp) as string) as observation_date
        from parsed_periods
        where observation_timestamp is not null
        order by observation_date
    """
    results = client.query(
        query,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("batch_date", "DATE", batch_date),
            ]
        ),
    ).result()
    return [row.observation_date for row in results]


def _scalar_query(
    client: bigquery.Client,
    query: str,
    parameters: list[bigquery.ScalarQueryParameter] | None = None,
) -> int:
    result = client.query(
        query,
        job_config=bigquery.QueryJobConfig(query_parameters=parameters or []),
    ).result()
    row = next(result)
    return int(row[0])


def _date_scoped_count(
    *,
    client: bigquery.Client,
    project_id: str,
    dataset_name: str,
    table_name: str,
    affected_dates: list[str],
) -> int:
    query = f"""
        select count(*) as row_count
        from `{project_id}.{dataset_name}.{table_name}`
        where observation_date in unnest(@affected_dates)
    """
    return _scalar_query(
        client,
        query,
        [bigquery.ArrayQueryParameter("affected_dates", "DATE", affected_dates)],
    )


def _build_data_plane_snapshot(
    *,
    client: bigquery.Client,
    project_id: str,
    datasets: dict[str, str],
    batch_date: str,
    affected_dates: list[str],
) -> dict[str, Any]:
    return {
        "raw_rows": _scalar_query(
            client,
            f"""
            select count(*) as row_count
            from `{project_id}.{datasets["raw"]}.eia_grid_batch`
            where batch_date = @batch_date
            """,
            [bigquery.ScalarQueryParameter("batch_date", "DATE", batch_date)],
        ),
        "staging_rows": _date_scoped_count(
            client=client,
            project_id=project_id,
            dataset_name=datasets["staging"],
            table_name="stg_grid_metrics",
            affected_dates=affected_dates,
        ),
        "fct_rows": _date_scoped_count(
            client=client,
            project_id=project_id,
            dataset_name=datasets["marts"],
            table_name="fct_grid_metrics",
            affected_dates=affected_dates,
        ),
        "agg_load_daily": _fetch_table_rows(
            client=client,
            table_id=f"{project_id}.{datasets['marts']}.agg_load_daily",
            affected_dates=affected_dates,
        ),
        "agg_generation_mix": _fetch_table_rows(
            client=client,
            table_id=f"{project_id}.{datasets['marts']}.agg_generation_mix",
            affected_dates=affected_dates,
        ),
        "agg_top_regions": _fetch_table_rows(
            client=client,
            table_id=f"{project_id}.{datasets['marts']}.agg_top_regions",
            affected_dates=affected_dates,
        ),
    }


def _resolve_backfill_hours() -> int:
    raw_value = os.environ.get("VOLTAGE_HUB_TEST_BACKFILL_HOURS", "2")
    try:
        hours = int(raw_value)
    except ValueError as exc:
        raise ValueError("VOLTAGE_HUB_TEST_BACKFILL_HOURS must be an integer") from exc
    if hours < 2:
        raise ValueError("VOLTAGE_HUB_TEST_BACKFILL_HOURS must be at least 2")
    return hours


def _resolve_backfill_end_boundary() -> datetime:
    raw_value = os.environ.get(
        "VOLTAGE_HUB_TEST_BACKFILL_END_BOUNDARY",
        "2026-03-27T00:00:00+00:00",
    )
    value = _coerce_datetime(raw_value)
    if value.minute != 0 or value.second != 0 or value.microsecond != 0:
        raise ValueError("VOLTAGE_HUB_TEST_BACKFILL_END_BOUNDARY must align to an hour")
    return value


def _hourly_execution_dates(start: datetime, end: datetime) -> list[datetime]:
    values: list[datetime] = []
    current = start
    while current <= end:
        values.append(current)
        current += timedelta(hours=1)
    return values


def _set_raw_ingestion_timestamp_for_batch(
    *,
    client: bigquery.Client,
    project_id: str,
    raw_dataset: str,
    batch_date: str,
    ingestion_timestamp: datetime,
) -> None:
    client.query(
        f"""
        update `{project_id}.{raw_dataset}.eia_grid_batch`
        set _ingestion_timestamp = @ingestion_timestamp
        where batch_date = @batch_date
        """,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter(
                    "ingestion_timestamp",
                    "TIMESTAMP",
                    ingestion_timestamp,
                ),
                bigquery.ScalarQueryParameter("batch_date", "DATE", batch_date),
            ]
        ),
    ).result()


def _query_raw_max_ingestion_timestamp(
    *,
    client: bigquery.Client,
    project_id: str,
    raw_dataset: str,
    batch_date: str | None = None,
) -> datetime | None:
    where_clause = "where batch_date = @batch_date" if batch_date is not None else ""
    query_parameters = (
        [bigquery.ScalarQueryParameter("batch_date", "DATE", batch_date)]
        if batch_date is not None
        else []
    )
    row = next(
        client.query(
            f"""
            select max(_ingestion_timestamp) as max_ingestion_timestamp
            from `{project_id}.{raw_dataset}.eia_grid_batch`
            {where_clause}
            """,
            job_config=bigquery.QueryJobConfig(query_parameters=query_parameters),
        ).result(),
        None,
    )
    if row is None or row.max_ingestion_timestamp is None:
        return None
    return row.max_ingestion_timestamp.astimezone(UTC)


def _fetch_table_rows(
    *,
    client: bigquery.Client,
    table_id: str,
    affected_dates: list[str],
) -> list[str]:
    query = f"""
        select to_json_string(t) as row_json
        from `{table_id}` as t
        where observation_date in unnest(@affected_dates)
        order by row_json
    """
    results = client.query(
        query,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("affected_dates", "DATE", affected_dates),
            ]
        ),
    ).result()
    return [row.row_json for row in results]


def _coerce_datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
