from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests
from google.cloud import bigquery, storage
from requests import Response, Session

REGION_DATA_ENDPOINT = "https://api.eia.gov/v2/electricity/rto/region-data/data/"
FUEL_TYPE_DATA_ENDPOINT = "https://api.eia.gov/v2/electricity/rto/fuel-type-data/data/"
RAW_TABLE_NAME = "eia_grid_batch"
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "raw_eia_batch.json"


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
