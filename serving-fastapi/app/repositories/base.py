from __future__ import annotations

from typing import Any

from google.cloud import bigquery
from google.cloud.bigquery import ScalarQueryParameter

from app.exceptions.base import RepositoryError


class BaseBigQueryRepository:
    """Thin helper around parameterized BigQuery query execution."""

    def __init__(self, *, client: bigquery.Client, project_id: str) -> None:
        self.client = client
        self.project_id = project_id

    def execute_query(
        self,
        query: str,
        *,
        parameters: list[ScalarQueryParameter] | None = None,
    ) -> list[dict[str, Any]]:
        try:
            job_config = bigquery.QueryJobConfig(query_parameters=parameters or [])
            result = self.client.query(query, job_config=job_config).result()
        except Exception as exc:  # pragma: no cover - BigQuery failure surface
            raise RepositoryError("BigQuery query execution failed") from exc

        return [dict(row.items()) for row in result]
