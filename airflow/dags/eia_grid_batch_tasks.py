from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests
from google.api_core.exceptions import NotFound
from google.cloud import bigquery, storage
from requests import Response, Session

REGION_DATA_ENDPOINT = "https://api.eia.gov/v2/electricity/rto/region-data/data/"
FUEL_TYPE_DATA_ENDPOINT = "https://api.eia.gov/v2/electricity/rto/fuel-type-data/data/"
RAW_TABLE_NAME = "eia_grid_batch"
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "raw_eia_batch.json"
PIPELINE_NAME = "eia_grid_batch"
DEFAULT_FRESHNESS_THRESHOLD_HOURS = 6
WARNING_ONLY_ANOMALY_THRESHOLD_PCT = 50.0
LOGGER = logging.getLogger(__name__)


class ExtractionError(RuntimeError):
    """Raised when the EIA extract response is invalid or cannot be fetched."""


class RawLoadError(RuntimeError):
    """Raised when raw landing payloads cannot be normalized for storage."""


@dataclass(frozen=True)
class BatchWindow:
    start: datetime
    end: datetime

    @property
    def batch_date(self) -> str:
        return self.start.date().isoformat()

    @property
    def gcs_window_segment(self) -> str:
        return self.start.isoformat()

    @property
    def batch_id(self) -> str:
        return f"{self.start.strftime('%Y%m%dT%H%M%S')}_{self.end.strftime('%Y%m%dT%H%M%S')}"


def extract_grid_batch(
    data_interval_start: datetime | str,
    data_interval_end: datetime | str,
    *,
    api_key: str | None = None,
    session: Session | None = None,
) -> dict[str, Any]:
    """Request one EIA batch window and return the raw payload plus batch metadata."""

    window = BatchWindow(
        start=_coerce_datetime(data_interval_start),
        end=_coerce_datetime(data_interval_end),
    )
    if window.end <= window.start:
        raise ExtractionError("data_interval_end must be greater than data_interval_start")

    resolved_api_key = api_key or os.environ.get("EIA_API_KEY")
    if not resolved_api_key:
        raise ExtractionError("EIA_API_KEY is required for grid batch extraction")

    request_session = session or requests.Session()
    params = _build_request_params(window, resolved_api_key)

    region_rows = _fetch_endpoint_rows(
        request_session,
        REGION_DATA_ENDPOINT,
        params,
        row_kind="region",
    )
    fuel_rows = _fetch_endpoint_rows(
        request_session,
        FUEL_TYPE_DATA_ENDPOINT,
        params,
        row_kind="fuel_type",
    )
    all_rows = region_rows + fuel_rows

    if not all_rows:
        raise ExtractionError("EIA response contained no rows for the requested window")

    return {
        "_batch_id": window.batch_id,
        "_source_url": "multiple",
        "_ingestion_timestamp": datetime.now(tz=UTC).isoformat(),
        "batch_date": window.batch_date,
        "data_interval_start": window.start.isoformat(),
        "data_interval_end": window.end.isoformat(),
        "response": {
            "data": all_rows,
            "total": len(all_rows),
        },
    }


def land_raw_to_gcs(
    raw_payload: dict[str, Any],
    *,
    bucket_name: str | None = None,
    storage_client: storage.Client | None = None,
) -> str:
    """Upload the extracted batch rows as newline-delimited JSON to GCS."""

    resolved_bucket_name = bucket_name or os.environ.get("GCS_BUCKET_NAME")
    if not resolved_bucket_name:
        raise RawLoadError("GCS_BUCKET_NAME is required for raw landing")

    rows = _normalize_raw_rows(raw_payload)
    window_start = _coerce_datetime(raw_payload["data_interval_start"])
    object_path = (
        f"voltage-hub/raw/"
        f"year={window_start:%Y}/month={window_start:%m}/day={window_start:%d}/"
        f"window={window_start.isoformat()}/batch.json"
    )
    blob_payload = "\n".join(json.dumps(row, separators=(",", ":")) for row in rows)

    client = storage_client or storage.Client(project=os.environ.get("GCP_PROJECT_ID"))
    bucket = client.bucket(resolved_bucket_name)
    blob = bucket.blob(object_path)
    blob.upload_from_string(blob_payload, content_type="application/json")

    return f"gs://{resolved_bucket_name}/{object_path}"


def load_to_bq_raw(
    gcs_uri: str,
    raw_payload: dict[str, Any],
    *,
    project_id: str | None = None,
    dataset_name: str | None = None,
    bq_client: bigquery.Client | None = None,
) -> dict[str, Any]:
    """Load the raw batch from GCS into the partitioned raw table."""

    resolved_project_id = project_id or os.environ.get("GCP_PROJECT_ID")
    resolved_dataset_name = dataset_name or os.environ.get("BQ_DATASET_RAW", "raw")
    if not resolved_project_id:
        raise RawLoadError("GCP_PROJECT_ID is required for raw BigQuery loads")

    batch_date = _coerce_datetime(raw_payload["data_interval_start"]).strftime("%Y%m%d")
    destination_table = (
        f"{resolved_project_id}.{resolved_dataset_name}.{RAW_TABLE_NAME}${batch_date}"
    )
    schema = _load_bq_schema()

    client = bq_client or bigquery.Client(project=resolved_project_id)
    job_config = bigquery.LoadJobConfig(
        schema=schema,
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        time_partitioning=bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.DAY,
            field="batch_date",
        ),
    )

    job = client.load_table_from_uri(
        gcs_uri,
        destination_table,
        job_config=job_config,
    )
    result = job.result()

    return {
        "destination_table": destination_table,
        "job_id": result.job_id,
        "output_rows": result.output_rows,
        "gcs_uri": gcs_uri,
    }


def check_anomalies(**context: Any) -> dict[str, Any]:
    """Compute warning-only anomaly results for the affected observation dates."""
    try:
        client = _build_bigquery_client()
        _ensure_meta_tables(client)

        batch_date = _coerce_datetime(context["data_interval_start"]).date().isoformat()
        affected_dates = _get_affected_observation_dates(client, batch_date)
        checked_at = datetime.now(tz=UTC)

        if not affected_dates:
            return {
                "status": "skipped",
                "task": "check_anomalies",
                "rows_inserted": 0,
                "affected_dates": [],
            }

        anomaly_rows = _build_anomaly_rows(
            client=client,
            affected_dates=affected_dates,
            run_id=str(context["run_id"]),
            checked_at=checked_at,
        )

        if anomaly_rows:
            _insert_rows_json(
                client=client,
                table_id=_table_id("meta", "anomaly_results"),
                rows=anomaly_rows,
            )

        return {
            "status": "success",
            "task": "check_anomalies",
            "rows_inserted": len(anomaly_rows),
            "affected_dates": affected_dates,
        }
    except Exception as exc:
        LOGGER.warning("Warning-only anomaly detection failed: %s", exc, exc_info=True)
        return {
            "status": "warning",
            "task": "check_anomalies",
            "rows_inserted": 0,
            "affected_dates": [],
            "error": str(exc),
        }


def record_run_metrics(**context: Any) -> dict[str, Any]:
    """Persist run metrics plus the two-signal freshness log for the DAG run."""

    client = _build_bigquery_client()
    _ensure_meta_tables(client)

    task_instance = context["ti"]
    load_result = task_instance.xcom_pull(task_ids="load_to_bq_raw") or {}
    checked_at = datetime.now(tz=UTC)
    run_status = _determine_run_status(context)
    try:
        freshness_row = _build_freshness_row(
            client=client,
            run_id=str(context["run_id"]),
            checked_at=checked_at,
        )
    except Exception as exc:
        LOGGER.warning("Freshness logging fell back to unknown values: %s", exc, exc_info=True)
        freshness_row = {
            "run_id": str(context["run_id"]),
            "pipeline_freshness_timestamp": None,
            "data_freshness_timestamp": None,
            "pipeline_freshness_status": "unknown",
            "data_freshness_status": "unknown",
            "checked_at": checked_at.isoformat(),
        }
    _insert_rows_json(
        client=client,
        table_id=_table_id("meta", "freshness_log"),
        rows=[freshness_row],
    )

    dbt_build_state = _task_state(context, "dbt_build")
    run_results = _read_dbt_run_results() if dbt_build_state == "success" else _empty_dbt_run_results()
    dag_run = context.get("dag_run")
    dag_start = getattr(dag_run, "start_date", None)
    duration_seconds = (
        max((checked_at - dag_start).total_seconds(), 0.0)
        if isinstance(dag_start, datetime)
        else 0.0
    )
    logical_date = context.get("logical_date") or context.get("execution_date")

    run_metrics_row = {
        "run_id": str(context["run_id"]),
        "dag_id": str(context["dag"].dag_id),
        "execution_date": _to_bq_timestamp(logical_date),
        "window_start": _to_bq_timestamp(context["data_interval_start"]),
        "window_end": _to_bq_timestamp(context["data_interval_end"]),
        "rows_loaded": int(load_result.get("output_rows", 0)),
        "dbt_models_passed": run_results["models_passed"],
        "dbt_tests_passed": run_results["tests_passed"],
        "dbt_tests_failed": run_results["tests_failed"],
        "bytes_processed": run_results["bytes_processed"],
        "duration_seconds": duration_seconds,
        "status": run_status,
        "created_at": checked_at.isoformat(),
    }
    _insert_rows_json(
        client=client,
        table_id=_table_id("meta", "run_metrics"),
        rows=[run_metrics_row],
    )

    return {
        "status": "success",
        "task": "record_run_metrics",
        "run_status": run_status,
        "rows_loaded": run_metrics_row["rows_loaded"],
        "freshness_status": {
            "pipeline": freshness_row["pipeline_freshness_status"],
            "data": freshness_row["data_freshness_status"],
        },
        "dbt_results": run_results,
    }


def update_pipeline_state(**context: Any) -> dict[str, Any]:
    """Upsert the latest successful pipeline watermark."""

    client = _build_bigquery_client()
    _ensure_meta_tables(client)

    query = f"""
        merge `{_table_id('meta', 'pipeline_state')}` as target
        using (
            select
                @pipeline_name as pipeline_name,
                @window_start as last_successful_window_start,
                @window_end as last_successful_window_end,
                @run_id as last_successful_run_id,
                @updated_at as updated_at
        ) as source
        on target.pipeline_name = source.pipeline_name
        when matched then update set
            last_successful_window_start = source.last_successful_window_start,
            last_successful_window_end = source.last_successful_window_end,
            last_successful_run_id = source.last_successful_run_id,
            updated_at = source.updated_at
        when not matched then insert (
            pipeline_name,
            last_successful_window_start,
            last_successful_window_end,
            last_successful_run_id,
            updated_at
        ) values (
            source.pipeline_name,
            source.last_successful_window_start,
            source.last_successful_window_end,
            source.last_successful_run_id,
            source.updated_at
        )
    """
    now = datetime.now(tz=UTC)
    client.query(
        query,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("pipeline_name", "STRING", PIPELINE_NAME),
                bigquery.ScalarQueryParameter(
                    "window_start",
                    "TIMESTAMP",
                    _coerce_datetime(context["data_interval_start"]),
                ),
                bigquery.ScalarQueryParameter(
                    "window_end",
                    "TIMESTAMP",
                    _coerce_datetime(context["data_interval_end"]),
                ),
                bigquery.ScalarQueryParameter("run_id", "STRING", str(context["run_id"])),
                bigquery.ScalarQueryParameter("updated_at", "TIMESTAMP", now),
            ]
        ),
    ).result()

    return {
        "status": "success",
        "task": "update_pipeline_state",
        "pipeline_name": PIPELINE_NAME,
        "updated_at": now.isoformat(),
    }


def _build_request_params(window: BatchWindow, api_key: str) -> dict[str, Any]:
    return {
        "api_key": api_key,
        "frequency": "hourly",
        "data[0]": "value",
        "start": window.start.strftime("%Y-%m-%dT%H"),
        "end": window.end.strftime("%Y-%m-%dT%H"),
        "sort[0][column]": "period",
        "sort[0][direction]": "asc",
        "length": 5000,
    }


def _request_with_retries(
    session: Session,
    endpoint: str,
    params: dict[str, Any],
) -> Response:
    rate_limit_backoff = 60
    server_backoff = 120
    timeout = (120, 300)

    for attempt in range(4):
        try:
            response = session.get(endpoint, params=params, timeout=timeout)
        except requests.Timeout as exc:
            if attempt == 3:
                raise ExtractionError("EIA request timed out after 3 retries") from exc
            time.sleep(server_backoff)
            continue
        except requests.RequestException as exc:
            raise ExtractionError("EIA request failed before receiving a response") from exc

        if response.status_code == 429:
            if attempt == 3:
                raise ExtractionError("EIA API rate limit persisted after 3 retries")
            time.sleep(rate_limit_backoff * (2**attempt))
            continue

        if 500 <= response.status_code < 600:
            if attempt == 3:
                raise ExtractionError(
                    f"EIA API returned {response.status_code} after 3 retries"
                )
            time.sleep(server_backoff)
            continue

        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise ExtractionError(
                f"EIA API returned unexpected status {response.status_code}"
            ) from exc

        return response

    raise ExtractionError("EIA request exhausted retries without a terminal response")


def _fetch_endpoint_rows(
    session: Session,
    endpoint: str,
    params: dict[str, Any],
    *,
    row_kind: str,
) -> list[dict[str, Any]]:
    all_rows: list[dict[str, Any]] = []
    offset = 0
    total_records: int | None = None

    while total_records is None or offset < total_records:
        paged_params = {**params, "offset": offset}
        response = _request_with_retries(session, endpoint, paged_params)

        try:
            payload = response.json()
        except ValueError as exc:
            raise ExtractionError("EIA response body is not valid JSON") from exc

        rows = _extract_response_rows(payload)
        pagination = payload.get("response", {}).get("total")

        if total_records is None:
            total_records = _coerce_total_records(pagination, len(rows))

        all_rows.extend(
            {
                **row,
                "__source_url": response.url,
                "__row_kind": row_kind,
            }
            for row in rows
        )
        offset += len(rows)

        if not rows or len(rows) < int(params["length"]):
            break

    return all_rows


def _extract_response_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    response = payload.get("response")
    if not isinstance(response, dict):
        raise ExtractionError("EIA response is missing the response object")

    rows = response.get("data")
    if not isinstance(rows, list):
        raise ExtractionError("EIA response is missing response.data")

    return rows


def _normalize_raw_rows(raw_payload: dict[str, Any]) -> list[dict[str, Any]]:
    response = raw_payload.get("response")
    if not isinstance(response, dict):
        raise RawLoadError("raw_payload must contain a response object")

    source_rows = response.get("data")
    if not isinstance(source_rows, list) or not source_rows:
        raise RawLoadError("raw_payload response.data must contain at least one row")

    batch_date = raw_payload.get("batch_date")
    batch_id = raw_payload.get("_batch_id")
    source_url = raw_payload.get("_source_url")
    ingestion_timestamp = raw_payload.get("_ingestion_timestamp")

    if not all([batch_date, batch_id, source_url, ingestion_timestamp]):
        raise RawLoadError("raw_payload is missing required batch metadata")

    normalized_rows = [
        _normalize_single_row(
            row,
            batch_date=batch_date,
            batch_id=batch_id,
            source_url=source_url,
            ingestion_timestamp=ingestion_timestamp,
        )
        for row in source_rows
    ]

    return normalized_rows


def _normalize_single_row(
    row: dict[str, Any],
    *,
    batch_date: str,
    batch_id: str,
    source_url: str,
    ingestion_timestamp: str,
) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise RawLoadError("EIA response rows must be objects")

    row_kind = row.get("__row_kind")
    if row_kind == "region":
        missing_fields = [
            field
            for field in (
                "respondent",
                "respondent-name",
                "type",
                "type-name",
                "value",
                "value-units",
                "period",
            )
            if row.get(field) in (None, "")
        ]
        type_value = str(row["type"])
        type_name_value = str(row["type-name"])
        fueltype_value = None
        fueltype_name_value = None
    elif row_kind == "fuel_type":
        missing_fields = [
            field
            for field in (
                "respondent",
                "respondent-name",
                "fueltype",
                "type-name",
                "value",
                "value-units",
                "period",
            )
            if row.get(field) in (None, "")
        ]
        # Assumption: fuel-type rows represent generation metrics split by source, so the
        # raw contract stores a stable category in type/type_name and keeps the source-
        # specific label in fueltype/fueltype_name.
        type_value = "generation"
        type_name_value = "Generation"
        fueltype_value = str(row["fueltype"])
        fueltype_name_value = str(row["type-name"])
    else:
        raise RawLoadError("EIA response row is missing the internal row kind marker")

    if missing_fields:
        raise RawLoadError(
            f"EIA response row is missing required fields: {', '.join(missing_fields)}"
        )

    try:
        metric_value = float(row["value"])
    except (TypeError, ValueError) as exc:
        raise RawLoadError("EIA response row value must be numeric") from exc

    return {
        "respondent": str(row["respondent"]),
        "respondent_name": str(row["respondent-name"]),
        "type": type_value,
        "type_name": type_name_value,
        "value": metric_value,
        "value_units": str(row["value-units"]),
        "period": str(row["period"]),
        "fueltype": _nullable_string(fueltype_value),
        "fueltype_name": _nullable_string(fueltype_name_value),
        "batch_date": batch_date,
        "_batch_id": batch_id,
        "_source_url": str(row.get("__source_url", source_url)),
        "_ingestion_timestamp": ingestion_timestamp,
    }


def _load_bq_schema() -> list[bigquery.SchemaField]:
    with SCHEMA_PATH.open("r", encoding="utf-8") as schema_file:
        schema_json = json.load(schema_file)

    return [
        bigquery.SchemaField(
            field["name"],
            field["type"],
            mode=field.get("mode", "NULLABLE"),
            description=field.get("description"),
        )
        for field in schema_json
    ]


def _nullable_string(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _coerce_datetime(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _coerce_total_records(total: Any, fallback: int) -> int:
    if total is None:
        return fallback
    try:
        return int(total)
    except (TypeError, ValueError):
        return fallback


def _build_bigquery_client() -> bigquery.Client:
    project_id = os.environ.get("GCP_PROJECT_ID")
    if not project_id:
        raise RawLoadError("GCP_PROJECT_ID is required for control-plane BigQuery writes")
    return bigquery.Client(project=project_id)


def _dataset_name(dataset_key: str) -> str:
    mapping = {
        "raw": os.environ.get("BQ_DATASET_RAW", "raw"),
        "staging": os.environ.get("BQ_DATASET_STAGING", "staging"),
        "marts": os.environ.get("BQ_DATASET_MARTS", "marts"),
        "meta": os.environ.get("BQ_DATASET_META", "meta"),
    }
    return mapping[dataset_key]


def _table_id(dataset_key: str, table_name: str) -> str:
    project_id = os.environ.get("GCP_PROJECT_ID")
    if not project_id:
        raise RawLoadError("GCP_PROJECT_ID is required for BigQuery table resolution")
    return f"{project_id}.{_dataset_name(dataset_key)}.{table_name}"


def _ensure_meta_tables(client: bigquery.Client) -> None:
    table_definitions = {
        "pipeline_state": [
            bigquery.SchemaField("pipeline_name", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("last_successful_window_start", "TIMESTAMP"),
            bigquery.SchemaField("last_successful_window_end", "TIMESTAMP"),
            bigquery.SchemaField("last_successful_run_id", "STRING"),
            bigquery.SchemaField("updated_at", "TIMESTAMP"),
        ],
        "run_metrics": [
            bigquery.SchemaField("run_id", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("dag_id", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("execution_date", "TIMESTAMP"),
            bigquery.SchemaField("window_start", "TIMESTAMP"),
            bigquery.SchemaField("window_end", "TIMESTAMP"),
            bigquery.SchemaField("rows_loaded", "INT64"),
            bigquery.SchemaField("dbt_models_passed", "INT64"),
            bigquery.SchemaField("dbt_tests_passed", "INT64"),
            bigquery.SchemaField("dbt_tests_failed", "INT64"),
            bigquery.SchemaField("bytes_processed", "INT64"),
            bigquery.SchemaField("duration_seconds", "FLOAT64"),
            bigquery.SchemaField("status", "STRING"),
            bigquery.SchemaField("created_at", "TIMESTAMP"),
        ],
        "freshness_log": [
            bigquery.SchemaField("run_id", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("pipeline_freshness_timestamp", "TIMESTAMP"),
            bigquery.SchemaField("data_freshness_timestamp", "TIMESTAMP"),
            bigquery.SchemaField("pipeline_freshness_status", "STRING"),
            bigquery.SchemaField("data_freshness_status", "STRING"),
            bigquery.SchemaField("checked_at", "TIMESTAMP"),
        ],
        "anomaly_results": [
            bigquery.SchemaField("observation_date", "DATE", mode="REQUIRED"),
            bigquery.SchemaField("region", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("metric_name", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("current_value", "FLOAT64"),
            bigquery.SchemaField("rolling_7d_avg", "FLOAT64"),
            bigquery.SchemaField("pct_deviation", "FLOAT64"),
            bigquery.SchemaField("anomaly_flag", "BOOLEAN"),
            bigquery.SchemaField("run_id", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("checked_at", "TIMESTAMP"),
        ],
    }

    for table_name, schema in table_definitions.items():
        table_id = _table_id("meta", table_name)
        try:
            client.get_table(table_id)
        except NotFound:
            client.create_table(bigquery.Table(table_id, schema=schema))


def _build_freshness_row(
    *,
    client: bigquery.Client,
    run_id: str,
    checked_at: datetime,
) -> dict[str, Any]:
    freshness_query = f"""
        select
            (
                select max(_ingestion_timestamp)
                from `{_table_id('raw', RAW_TABLE_NAME)}`
            ) as pipeline_freshness_timestamp,
            (
                select max(observation_timestamp)
                from `{_table_id('staging', 'stg_grid_metrics')}`
            ) as data_freshness_timestamp
    """
    row = next(client.query(freshness_query).result(), None)
    pipeline_timestamp = getattr(row, "pipeline_freshness_timestamp", None) if row else None
    data_timestamp = getattr(row, "data_freshness_timestamp", None) if row else None

    return {
        "run_id": run_id,
        "pipeline_freshness_timestamp": _to_bq_timestamp(pipeline_timestamp),
        "data_freshness_timestamp": _to_bq_timestamp(data_timestamp),
        "pipeline_freshness_status": _freshness_status(pipeline_timestamp, checked_at),
        "data_freshness_status": _freshness_status(data_timestamp, checked_at),
        "checked_at": checked_at.isoformat(),
    }


def _freshness_status(timestamp_value: Any, checked_at: datetime) -> str:
    if timestamp_value is None:
        return "unknown"

    # Assumption: in the absence of a separately documented data-freshness threshold,
    # both freshness signals use the SPEC warn threshold of 6 hours to classify
    # consumer-facing `fresh` versus `stale` status in `meta.freshness_log`.
    age = checked_at - _coerce_datetime(timestamp_value)
    if age.total_seconds() <= DEFAULT_FRESHNESS_THRESHOLD_HOURS * 3600:
        return "fresh"
    return "stale"


def _get_affected_observation_dates(client: bigquery.Client, batch_date: str) -> list[str]:
    query = f"""
        with parsed_periods as (
            select
                coalesce(
                    safe.parse_timestamp('%Y-%m-%dT%H:%M:%E*S%Ez', period),
                    safe.parse_timestamp('%Y-%m-%dT%H', period),
                    safe.parse_timestamp('%Y-%m-%d', period)
                ) as observation_timestamp
            from `{_table_id('raw', RAW_TABLE_NAME)}`
            where batch_date = @batch_date
        )
        select distinct cast(date(observation_timestamp) as string) as observation_date
        from parsed_periods
        where observation_timestamp is not null
        order by observation_date
    """
    result = client.query(
        query,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("batch_date", "DATE", batch_date),
            ]
        ),
    ).result()
    return [row.observation_date for row in result]


def _build_anomaly_rows(
    *,
    client: bigquery.Client,
    affected_dates: list[str],
    run_id: str,
    checked_at: datetime,
) -> list[dict[str, Any]]:
    query = f"""
        with daily_metrics as (
            select
                observation_date,
                region,
                'demand' as metric_name,
                total_load as current_value
            from `{_table_id('marts', 'agg_load_daily')}`

            union all

            select
                observation_date,
                region,
                'generation' as metric_name,
                sum(daily_total_generation) as current_value
            from `{_table_id('marts', 'agg_generation_mix')}`
            group by observation_date, region
        ),
        scored_metrics as (
            select
                current_day.observation_date,
                current_day.region,
                current_day.metric_name,
                current_day.current_value,
                (
                    select avg(history_day.current_value)
                    from daily_metrics as history_day
                    where history_day.region = current_day.region
                        and history_day.metric_name = current_day.metric_name
                        and history_day.observation_date between date_sub(current_day.observation_date, interval 7 day)
                            and date_sub(current_day.observation_date, interval 1 day)
                ) as rolling_7d_avg
            from daily_metrics as current_day
        )
        select
            observation_date,
            region,
            metric_name,
            current_value,
            rolling_7d_avg,
            case
                when rolling_7d_avg is null or rolling_7d_avg = 0 then null
                else ((current_value - rolling_7d_avg) / rolling_7d_avg) * 100
            end as pct_deviation,
            coalesce(
                abs(
                    case
                        when rolling_7d_avg is null or rolling_7d_avg = 0 then null
                        else ((current_value - rolling_7d_avg) / rolling_7d_avg) * 100
                    end
                ) > {WARNING_ONLY_ANOMALY_THRESHOLD_PCT},
                false
            ) as anomaly_flag
        from scored_metrics
        where observation_date in unnest(@affected_dates)
        order by observation_date, region, metric_name
    """
    result = client.query(
        query,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("affected_dates", "DATE", affected_dates),
            ]
        ),
    ).result()

    rows: list[dict[str, Any]] = []
    for row in result:
        rows.append(
            {
                "observation_date": row.observation_date.isoformat(),
                "region": row.region,
                "metric_name": row.metric_name,
                "current_value": row.current_value,
                "rolling_7d_avg": row.rolling_7d_avg,
                "pct_deviation": row.pct_deviation,
                "anomaly_flag": row.anomaly_flag,
                "run_id": run_id,
                "checked_at": checked_at.isoformat(),
            }
        )

    return rows


def _determine_run_status(context: dict[str, Any]) -> str:
    relevant_task_ids = (
        "extract_grid_batch",
        "land_raw_to_gcs",
        "load_to_bq_raw",
        "dbt_source_freshness",
        "dbt_build",
        "check_anomalies",
    )
    return (
        "success"
        if all(_task_state(context, task_id) == "success" for task_id in relevant_task_ids)
        else "failed"
    )


def _task_state(context: dict[str, Any], task_id: str) -> str | None:
    dag_run = context.get("dag_run")
    if dag_run is None:
        return None

    for task_instance in dag_run.get_task_instances():
        if task_instance.task_id == task_id:
            return task_instance.state
    return None


def _insert_rows_json(
    *,
    client: bigquery.Client,
    table_id: str,
    rows: list[dict[str, Any]],
) -> None:
    if not rows:
        return
    errors = client.insert_rows_json(table_id, rows)
    if errors:
        raise RawLoadError(f"BigQuery insert_rows_json failed for {table_id}: {errors}")


def _read_dbt_run_results() -> dict[str, int]:
    dbt_run_results_path = _resolve_dbt_run_results_path()
    if dbt_run_results_path is None:
        return _empty_dbt_run_results()

    run_results = json.loads(dbt_run_results_path.read_text(encoding="utf-8"))
    models_passed = 0
    tests_passed = 0
    tests_failed = 0
    bytes_processed = 0

    for result in run_results.get("results", []):
        unique_id = str(result.get("unique_id", ""))
        status = str(result.get("status", ""))
        adapter_response = result.get("adapter_response") or {}
        bytes_processed += int(adapter_response.get("bytes_processed") or 0)

        if unique_id.startswith("model.") and status == "success":
            models_passed += 1
        if unique_id.startswith("test."):
            if status in {"pass", "success"}:
                tests_passed += 1
            elif status in {"fail", "error"}:
                tests_failed += 1

    return {
        "models_passed": models_passed,
        "tests_passed": tests_passed,
        "tests_failed": tests_failed,
        "bytes_processed": bytes_processed,
    }


def _empty_dbt_run_results() -> dict[str, int]:
    return {
        "models_passed": 0,
        "tests_passed": 0,
        "tests_failed": 0,
        "bytes_processed": 0,
    }


def _resolve_dbt_run_results_path() -> Path | None:
    configured_path = os.environ.get("DBT_RUN_RESULTS_PATH", "/opt/airflow/dbt/target/run_results.json")
    path = Path(configured_path)
    if path.exists():
        return path
    return None


def _to_bq_timestamp(value: Any) -> str | None:
    if value is None:
        return None
    return _coerce_datetime(value).isoformat()
