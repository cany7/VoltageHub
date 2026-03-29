from __future__ import annotations

from app.schemas.health import HealthResponse


def get_health() -> HealthResponse:
    return HealthResponse(status="healthy")
