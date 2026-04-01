from fastapi import Depends
from google.cloud import bigquery

from app.config.bigquery import get_bigquery_client
from app.config.settings import AppSettings, get_settings
from voltage_hub_core.repositories import ControlPlaneRepository, MetricsRepository


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


__all__ = ["MetricsRepository", "get_metrics_repository"]
