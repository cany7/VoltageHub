from fastapi import Depends

from app.repositories.control_plane import ControlPlaneRepository, get_control_plane_repository
from voltage_hub_core.services import ControlPlaneService, combine_freshness_status


def get_control_plane_service(
    repository: ControlPlaneRepository = Depends(get_control_plane_repository),
) -> ControlPlaneService:
    return ControlPlaneService(repository=repository)


__all__ = [
    "ControlPlaneService",
    "combine_freshness_status",
    "get_control_plane_service",
]
