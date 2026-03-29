from __future__ import annotations

from datetime import date

from fastapi import Depends
from google.cloud import bigquery

from app.config.bigquery import get_bigquery_client
from app.config.settings import AppSettings, get_settings
from app.repositories.base import BaseBigQueryRepository


class ControlPlaneRepository(BaseBigQueryRepository):
    """Read-only access to meta.* tables used by control-plane endpoints."""

    def __init__(
        self,
        *,
        client: bigquery.Client,
        project_id: str,
        meta_dataset: str,
    ) -> None:
        super().__init__(client=client, project_id=project_id)
        self.meta_dataset = meta_dataset

    def get_latest_freshness(self) -> dict | None:
        query = f"""
            select
                pipeline_freshness_timestamp,
                data_freshness_timestamp,
                pipeline_freshness_status,
                data_freshness_status,
                checked_at
            from `{self.project_id}.{self.meta_dataset}.freshness_log`
            order by checked_at desc
            limit 1
        """
        rows = self.execute_query(query)
        return rows[0] if rows else None

    def get_latest_pipeline_status(self) -> dict | None:
        query = f"""
            select
                pipeline_name,
                last_successful_window_start,
                last_successful_window_end,
                last_successful_run_id,
                updated_at
            from `{self.project_id}.{self.meta_dataset}.pipeline_state`
            order by updated_at desc
            limit 1
        """
        rows = self.execute_query(query)
        return rows[0] if rows else None

    def list_anomalies(
        self,
        *,
        region: str | None,
        start_date: date | None,
        end_date: date | None,
        anomaly_only: bool,
    ) -> list[dict]:
        filters = ["1 = 1"]
        parameters: list[bigquery.ScalarQueryParameter] = []

        if region is not None:
            filters.append("region = @region")
            parameters.append(bigquery.ScalarQueryParameter("region", "STRING", region))

        if start_date is not None:
            filters.append("observation_date >= @start_date")
            parameters.append(
                bigquery.ScalarQueryParameter("start_date", "DATE", start_date)
            )

        if end_date is not None:
            filters.append("observation_date <= @end_date")
            parameters.append(bigquery.ScalarQueryParameter("end_date", "DATE", end_date))

        if anomaly_only:
            filters.append("anomaly_flag is true")

        query = f"""
            select
                observation_date,
                region,
                metric_name,
                current_value,
                rolling_7d_avg,
                pct_deviation,
                anomaly_flag,
                checked_at
            from `{self.project_id}.{self.meta_dataset}.anomaly_results`
            where {" and ".join(filters)}
            order by observation_date desc, checked_at desc, region asc, metric_name asc
        """
        return self.execute_query(query, parameters=parameters)


def get_control_plane_repository(
    settings: AppSettings = Depends(get_settings),
    client: bigquery.Client = Depends(get_bigquery_client),
) -> ControlPlaneRepository:
    return ControlPlaneRepository(
        client=client,
        project_id=settings.gcp_project_id,
        meta_dataset=settings.bq_dataset_meta,
    )
