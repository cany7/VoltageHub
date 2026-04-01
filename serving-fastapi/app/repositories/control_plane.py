from fastapi import Depends
from google.cloud import bigquery

from app.config.bigquery import get_bigquery_client
from app.config.settings import AppSettings, get_settings
from voltage_hub_core.repositories import ControlPlaneRepository


def get_control_plane_repository(
    settings: AppSettings = Depends(get_settings),
    client: bigquery.Client = Depends(get_bigquery_client),
) -> ControlPlaneRepository:
    return ControlPlaneRepository(
        client=client,
        project_id=settings.gcp_project_id,
        meta_dataset=settings.bq_dataset_meta,
    )


__all__ = ["ControlPlaneRepository", "get_control_plane_repository"]
