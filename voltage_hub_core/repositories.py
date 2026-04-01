from __future__ import annotations

from datetime import date
from typing import Any

from google.cloud import bigquery
from google.cloud.bigquery import ScalarQueryParameter

from voltage_hub_core.bigquery import get_bigquery_client
from voltage_hub_core.exceptions import RepositoryError
from voltage_hub_core.schemas import AppSettings, get_settings


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


class ControlPlaneRepository(BaseBigQueryRepository):
    """Read-only access to meta.* tables used by serving interfaces."""

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

    def get_anomaly_summary(self) -> dict[str, Any]:
        query = f"""
            with latest as (
                select max(observation_date) as latest_observation_date
                from `{self.project_id}.{self.meta_dataset}.anomaly_results`
            )
            select
                latest.latest_observation_date,
                max(results.checked_at) as latest_anomaly_checked_at,
                countif(results.anomaly_flag) as flagged_anomaly_count_last_7_days,
                count(distinct case when results.anomaly_flag then results.region end)
                    as affected_regions_last_7_days
            from latest
            left join `{self.project_id}.{self.meta_dataset}.anomaly_results` as results
              on latest.latest_observation_date is not null
             and results.observation_date >= date_sub(latest.latest_observation_date, interval 6 day)
             and results.observation_date <= latest.latest_observation_date
            group by latest.latest_observation_date
        """
        rows = self.execute_query(query)
        if not rows:
            return {
                "latest_observation_date": None,
                "latest_anomaly_checked_at": None,
                "flagged_anomaly_count_last_7_days": 0,
                "affected_regions_last_7_days": 0,
            }
        return rows[0]


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

    def get_available_date_bounds(self) -> dict[str, Any]:
        query = f"""
            with bounds as (
                select
                    min(observation_date) as min_date,
                    max(observation_date) as max_date
                from `{self.project_id}.{self.marts_dataset}.agg_load_daily`
                union all
                select
                    min(observation_date) as min_date,
                    max(observation_date) as max_date
                from `{self.project_id}.{self.marts_dataset}.agg_load_hourly`
                union all
                select
                    min(observation_date) as min_date,
                    max(observation_date) as max_date
                from `{self.project_id}.{self.marts_dataset}.agg_generation_mix`
                union all
                select
                    min(observation_date) as min_date,
                    max(observation_date) as max_date
                from `{self.project_id}.{self.marts_dataset}.agg_top_regions`
            )
            select min(min_date) as start_date, max(max_date) as end_date
            from bounds
        """
        rows = self.execute_query(query)
        if not rows:
            return {"start_date": None, "end_date": None}
        return rows[0]


class DimensionRepository(BaseBigQueryRepository):
    def __init__(
        self,
        *,
        client: bigquery.Client,
        project_id: str,
        marts_dataset: str,
    ) -> None:
        super().__init__(client=client, project_id=project_id)
        self.marts_dataset = marts_dataset

    def list_regions(self) -> list[dict[str, Any]]:
        query = f"""
            select region, region_name
            from `{self.project_id}.{self.marts_dataset}.dim_region`
            order by region asc
        """
        return self.execute_query(query)

    def list_energy_sources(self) -> list[dict[str, Any]]:
        query = f"""
            select energy_source
            from `{self.project_id}.{self.marts_dataset}.dim_energy_source`
            order by energy_source asc
        """
        return self.execute_query(query)


def get_control_plane_repository(
    settings: AppSettings | None = None,
    client: bigquery.Client | None = None,
) -> ControlPlaneRepository:
    runtime_settings = settings or get_settings()
    runtime_client = client or get_bigquery_client(runtime_settings)
    return ControlPlaneRepository(
        client=runtime_client,
        project_id=runtime_settings.gcp_project_id,
        meta_dataset=runtime_settings.bq_dataset_meta,
    )


def get_metrics_repository(
    settings: AppSettings | None = None,
    client: bigquery.Client | None = None,
) -> MetricsRepository:
    runtime_settings = settings or get_settings()
    runtime_client = client or get_bigquery_client(runtime_settings)
    meta_repository = ControlPlaneRepository(
        client=runtime_client,
        project_id=runtime_settings.gcp_project_id,
        meta_dataset=runtime_settings.bq_dataset_meta,
    )
    return MetricsRepository(
        client=runtime_client,
        project_id=runtime_settings.gcp_project_id,
        marts_dataset=runtime_settings.bq_dataset_marts,
        meta_repository=meta_repository,
    )


def get_dimension_repository(
    settings: AppSettings | None = None,
    client: bigquery.Client | None = None,
) -> DimensionRepository:
    runtime_settings = settings or get_settings()
    runtime_client = client or get_bigquery_client(runtime_settings)
    return DimensionRepository(
        client=runtime_client,
        project_id=runtime_settings.gcp_project_id,
        marts_dataset=runtime_settings.bq_dataset_marts,
    )
