from __future__ import annotations

from datetime import date

from fastapi import Depends
from google.cloud import bigquery

from app.config.bigquery import get_bigquery_client
from app.config.settings import AppSettings, get_settings
from app.repositories.base import BaseBigQueryRepository
from app.repositories.control_plane import ControlPlaneRepository


class MetricsRepository(BaseBigQueryRepository):
    """Read-only access to pre-computed marts.agg_* tables."""

    def __init__(
        self,
        *,
        client: bigquery.Client,
        project_id: str,
        marts_dataset: str,
        meta_repository: ControlPlaneRepository,
    ) -> None:
        super().__init__(client=client, project_id=project_id)
        self.marts_dataset = marts_dataset
        self.meta_repository = meta_repository

    def list_load_metrics(
        self,
        *,
        region: str,
        start_date: date,
        end_date: date,
        granularity: str,
    ) -> list[dict]:
        if granularity == "hourly":
            table_name = "agg_load_hourly"
            selected_columns = """
                region,
                region_name,
                observation_timestamp,
                observation_date,
                hourly_load,
                unit
            """
            order_by = "observation_timestamp asc"
        else:
            table_name = "agg_load_daily"
            selected_columns = """
                region,
                region_name,
                observation_date,
                avg_load,
                min_load,
                max_load,
                total_load,
                unit
            """
            order_by = "observation_date asc"

        query = f"""
            select {selected_columns}
            from `{self.project_id}.{self.marts_dataset}.{table_name}`
            where region = @region
              and observation_date >= @start_date
              and observation_date <= @end_date
            order by {order_by}
        """
        parameters = [
            bigquery.ScalarQueryParameter("region", "STRING", region),
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        ]
        return self.execute_query(query, parameters=parameters)

    def list_generation_mix(
        self,
        *,
        region: str,
        start_date: date,
        end_date: date,
    ) -> list[dict]:
        query = f"""
            select
                region,
                region_name,
                observation_date,
                energy_source,
                daily_total_generation,
                unit
            from `{self.project_id}.{self.marts_dataset}.agg_generation_mix`
            where region = @region
              and observation_date >= @start_date
              and observation_date <= @end_date
            order by observation_date asc, energy_source asc
        """
        parameters = [
            bigquery.ScalarQueryParameter("region", "STRING", region),
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        ]
        return self.execute_query(query, parameters=parameters)

    def list_top_regions(
        self,
        *,
        start_date: date,
        end_date: date,
        limit: int,
    ) -> list[dict]:
        query = f"""
            select
                observation_date,
                region,
                region_name,
                daily_total_load,
                rank
            from `{self.project_id}.{self.marts_dataset}.agg_top_regions`
            where observation_date >= @start_date
              and observation_date <= @end_date
              and rank <= @limit
            order by observation_date asc, rank asc
        """
        parameters = [
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
            bigquery.ScalarQueryParameter("limit", "INT64", limit),
        ]
        return self.execute_query(query, parameters=parameters)

    def get_response_metadata(self) -> dict | None:
        freshness_record = self.meta_repository.get_latest_freshness()
        pipeline_record = self.meta_repository.get_latest_pipeline_status()
        if freshness_record is None and pipeline_record is None:
            return None

        return {
            "freshness": freshness_record,
            "pipeline": pipeline_record,
        }


def get_metrics_repository(
    settings: AppSettings = Depends(get_settings),
    client: bigquery.Client = Depends(get_bigquery_client),
) -> MetricsRepository:
    meta_repository = ControlPlaneRepository(
        client=client,
        project_id=settings.gcp_project_id,
        meta_dataset=settings.bq_dataset_meta,
    )
    return MetricsRepository(
        client=client,
        project_id=settings.gcp_project_id,
        marts_dataset=settings.bq_dataset_marts,
        meta_repository=meta_repository,
    )
