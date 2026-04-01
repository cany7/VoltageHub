from __future__ import annotations

from dataclasses import dataclass

from voltage_hub_core.bigquery import get_bigquery_client
from voltage_hub_core.cache import QueryCache
from voltage_hub_core.repositories import (
    ControlPlaneRepository,
    DimensionRepository,
    MetricsRepository,
    get_control_plane_repository,
    get_dimension_repository,
    get_metrics_repository,
)
from voltage_hub_core.schemas import AppSettings
from voltage_hub_core.services import ControlPlaneService, MetricsService, SchemaService

from app.config.settings import get_mcp_settings


@dataclass(frozen=True)
class Runtime:
    settings: AppSettings
    cache: QueryCache
    metrics_repository: MetricsRepository
    control_plane_repository: ControlPlaneRepository
    dimension_repository: DimensionRepository
    metrics_service: MetricsService
    control_plane_service: ControlPlaneService
    schema_service: SchemaService


def create_runtime() -> Runtime:
    mcp_settings = get_mcp_settings()
    settings = AppSettings.model_validate(
        {
            "GCP_PROJECT_ID": mcp_settings.gcp_project_id,
            "BQ_DATASET_MARTS": mcp_settings.bq_dataset_marts,
            "BQ_DATASET_META": mcp_settings.bq_dataset_meta,
            "CACHE_TTL_SECONDS": mcp_settings.cache_ttl_seconds,
            "GOOGLE_APPLICATION_CREDENTIALS": mcp_settings.google_application_credentials,
        }
    )
    cache = QueryCache(ttl_seconds=settings.cache_ttl_seconds)
    client = get_bigquery_client(settings)
    control_plane_repository = get_control_plane_repository(settings=settings, client=client)
    metrics_repository = get_metrics_repository(settings=settings, client=client)
    dimension_repository = get_dimension_repository(settings=settings, client=client)
    return Runtime(
        settings=settings,
        cache=cache,
        metrics_repository=metrics_repository,
        control_plane_repository=control_plane_repository,
        dimension_repository=dimension_repository,
        metrics_service=MetricsService(repository=metrics_repository, cache=cache),
        control_plane_service=ControlPlaneService(repository=control_plane_repository),
        schema_service=SchemaService(repository=dimension_repository, cache=cache),
    )
