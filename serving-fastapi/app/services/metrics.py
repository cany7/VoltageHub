from fastapi import Depends

from app.cache.query_cache import QueryCache, get_query_cache
from app.repositories.metrics import MetricsRepository, get_metrics_repository
from voltage_hub_core.services import MetricsService


def get_metrics_service(
    repository: MetricsRepository = Depends(get_metrics_repository),
    cache: QueryCache = Depends(get_query_cache),
) -> MetricsService:
    return MetricsService(repository=repository, cache=cache)


__all__ = ["MetricsService", "get_metrics_service"]
