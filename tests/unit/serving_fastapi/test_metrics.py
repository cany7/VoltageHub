from __future__ import annotations

import sys
from datetime import UTC, date, datetime
from pathlib import Path

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SERVING_ROOT = PROJECT_ROOT / "serving-fastapi"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(SERVING_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVING_ROOT))

from app.main import create_app  # noqa: E402
from app.cache.query_cache import QueryCache  # noqa: E402
from app.routers.metrics import get_metrics_service  # noqa: E402
from app.schemas.metrics import ResponseMetadata  # noqa: E402
from app.services.metrics import MetricsService  # noqa: E402


class StubMetricsService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.metadata = {
            "data_as_of": "2026-03-28T09:30:00+00:00",
            "pipeline_run_id": "scheduled__2026-03-28T10:00:00+00:00",
            "freshness_status": "fresh",
        }

    def get_load_metrics(
        self,
        *,
        region: str,
        start_date: date,
        end_date: date,
        granularity: str,
    ) -> dict[str, object]:
        self.calls.append(
            {
                "endpoint": "load",
                "region": region,
                "start_date": start_date,
                "end_date": end_date,
                "granularity": granularity,
            }
        )
        return {
            "data": [
                {
                    "region": region,
                    "region_name": "California ISO",
                    "observation_date": date(2026, 3, 28),
                    "avg_load": 10.0,
                    "min_load": 5.0,
                    "max_load": 20.0,
                    "total_load": 240.0,
                    "unit": "megawatthours",
                }
            ],
            "metadata": self.metadata,
        }

    def get_generation_mix(
        self,
        *,
        region: str,
        start_date: date,
        end_date: date,
    ) -> dict[str, object]:
        self.calls.append(
            {
                "endpoint": "generation-mix",
                "region": region,
                "start_date": start_date,
                "end_date": end_date,
            }
        )
        return {
            "data": [
                {
                    "region": region,
                    "region_name": "ERCOT",
                    "observation_date": date(2026, 3, 28),
                    "energy_source": "WND",
                    "daily_total_generation": 999.0,
                    "unit": "megawatthours",
                }
            ],
            "metadata": self.metadata,
        }

    def get_top_regions(
        self,
        *,
        start_date: date,
        end_date: date,
        limit: int,
    ) -> dict[str, object]:
        self.calls.append(
            {
                "endpoint": "top-regions",
                "start_date": start_date,
                "end_date": end_date,
                "limit": limit,
            }
        )
        return {
            "data": [
                {
                    "observation_date": date(2026, 3, 27),
                    "region": "ERCO",
                    "region_name": "ERCOT",
                    "daily_total_load": 123.0,
                    "rank": 1,
                }
            ],
            "metadata": self.metadata,
        }


class FakeMetricsRepository:
    def __init__(self) -> None:
        self.load_call_count = 0

    def list_load_metrics(self, **_: object) -> list[dict[str, object]]:
        self.load_call_count += 1
        return [
            {
                "region": "ERCO",
                "region_name": "ERCOT",
                "observation_timestamp": datetime(2026, 3, 28, 1, 0, tzinfo=UTC),
                "observation_date": date(2026, 3, 28),
                "hourly_load": 42.0,
                "unit": "megawatthours",
            }
        ]

    def list_generation_mix(self, **_: object) -> list[dict[str, object]]:
        return []

    def list_top_regions(self, **_: object) -> list[dict[str, object]]:
        return []

    def get_response_metadata(self) -> dict[str, object]:
        return {
            "freshness": {
                "data_freshness_timestamp": datetime(2026, 3, 28, 9, 0, tzinfo=UTC),
                "pipeline_freshness_status": "fresh",
                "data_freshness_status": "stale",
            },
            "pipeline": {
                "last_successful_run_id": "scheduled__2026-03-28T10:00:00+00:00",
            },
        }


def _build_test_client(service: StubMetricsService) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_metrics_service] = lambda: service
    return TestClient(app)


def _build_metrics_service(repository: FakeMetricsRepository) -> MetricsService:
    return MetricsService(
        repository=repository,  # type: ignore[arg-type]
        cache=QueryCache(ttl_seconds=300),
    )


def _build_test_client_with_real_metrics_service(
    repository: FakeMetricsRepository | None = None,
) -> TestClient:
    app = create_app()
    service = _build_metrics_service(repository or FakeMetricsRepository())
    app.dependency_overrides[get_metrics_service] = lambda: service
    return TestClient(app)


def test_load_metrics_endpoint_returns_response_envelope() -> None:
    service = StubMetricsService()
    client = _build_test_client(service)

    response = client.get(
        "/metrics/load",
        params={
            "region": "CISO",
            "start_date": "2026-03-20",
            "end_date": "2026-03-28",
            "granularity": "daily",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert datetime.fromisoformat(
        payload["metadata"]["data_as_of"].replace("Z", "+00:00")
    ) == datetime(2026, 3, 28, 9, 30, tzinfo=UTC)
    assert payload["metadata"]["pipeline_run_id"] == "scheduled__2026-03-28T10:00:00+00:00"
    assert payload["metadata"]["freshness_status"] == "fresh"
    assert payload["data"][0]["region"] == "CISO"
    assert service.calls == [
        {
            "endpoint": "load",
            "region": "CISO",
            "start_date": date(2026, 3, 20),
            "end_date": date(2026, 3, 28),
            "granularity": "daily",
        }
    ]


def test_generation_mix_endpoint_returns_precomputed_rows() -> None:
    service = StubMetricsService()
    client = _build_test_client(service)

    response = client.get(
        "/metrics/generation-mix",
        params={
            "region": "ERCO",
            "start_date": "2026-03-20",
            "end_date": "2026-03-28",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"][0]["energy_source"] == "WND"
    assert datetime.fromisoformat(
        payload["metadata"]["data_as_of"].replace("Z", "+00:00")
    ) == datetime(2026, 3, 28, 9, 30, tzinfo=UTC)
    assert (
        payload["metadata"]["pipeline_run_id"]
        == "scheduled__2026-03-28T10:00:00+00:00"
    )
    assert payload["metadata"]["freshness_status"] == "fresh"


def test_top_regions_endpoint_uses_daily_limit_parameter() -> None:
    service = StubMetricsService()
    client = _build_test_client(service)

    response = client.get(
        "/metrics/top-regions",
        params={
            "start_date": "2026-03-20",
            "end_date": "2026-03-28",
            "limit": 5,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"][0]["rank"] == 1
    assert datetime.fromisoformat(
        payload["metadata"]["data_as_of"].replace("Z", "+00:00")
    ) == datetime(2026, 3, 28, 9, 30, tzinfo=UTC)
    assert payload["metadata"]["pipeline_run_id"] == "scheduled__2026-03-28T10:00:00+00:00"
    assert payload["metadata"]["freshness_status"] == "fresh"
    assert service.calls == [
        {
            "endpoint": "top-regions",
            "start_date": date(2026, 3, 20),
            "end_date": date(2026, 3, 28),
            "limit": 5,
        }
    ]


def test_metrics_service_builds_metadata_from_meta_tables() -> None:
    service = _build_metrics_service(FakeMetricsRepository())

    response = service.get_load_metrics(
        region="ERCO",
        start_date=date(2026, 3, 28),
        end_date=date(2026, 3, 28),
        granularity="hourly",
    )

    assert response.metadata == ResponseMetadata(
        data_as_of=datetime(2026, 3, 28, 9, 0, tzinfo=UTC),
        pipeline_run_id="scheduled__2026-03-28T10:00:00+00:00",
        freshness_status="stale",
    )
    assert response.data[0].hourly_load == 42.0


def test_metrics_service_returns_unknown_metadata_when_meta_tables_are_empty() -> None:
    class EmptyMetadataRepository(FakeMetricsRepository):
        def get_response_metadata(self) -> dict[str, object] | None:
            return None

    service = _build_metrics_service(EmptyMetadataRepository())

    response = service.get_generation_mix(
        region="ERCO",
        start_date=date(2026, 3, 28),
        end_date=date(2026, 3, 28),
    )

    assert response.metadata == ResponseMetadata(
        data_as_of=None,
        pipeline_run_id=None,
        freshness_status="unknown",
    )
    assert response.data == []


def test_load_metrics_endpoint_rejects_invalid_granularity() -> None:
    client = _build_test_client(StubMetricsService())

    response = client.get(
        "/metrics/load",
        params={
            "region": "ERCO",
            "start_date": "2026-03-20",
            "end_date": "2026-03-28",
            "granularity": "weekly",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"] == "validation_error"
    assert "granularity" in response.json()["detail"]


def test_load_metrics_endpoint_rejects_empty_region_with_structured_error() -> None:
    client = _build_test_client_with_real_metrics_service()

    response = client.get(
        "/metrics/load",
        params={
            "region": "   ",
            "start_date": "2026-03-20",
            "end_date": "2026-03-28",
            "granularity": "daily",
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "error": "validation_error",
        "detail": "region must not be empty",
    }


def test_generation_mix_endpoint_rejects_inverted_date_range() -> None:
    client = _build_test_client_with_real_metrics_service()

    response = client.get(
        "/metrics/generation-mix",
        params={
            "region": "ERCO",
            "start_date": "2026-03-29",
            "end_date": "2026-03-28",
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "error": "validation_error",
        "detail": "start_date must be less than or equal to end_date",
    }


def test_top_regions_endpoint_rejects_zero_limit_with_structured_error() -> None:
    client = _build_test_client(StubMetricsService())

    response = client.get(
        "/metrics/top-regions",
        params={
            "start_date": "2026-03-20",
            "end_date": "2026-03-28",
            "limit": 0,
        },
    )

    assert response.status_code == 400
    assert response.json()["error"] == "validation_error"
    assert "limit" in response.json()["detail"]


def test_metrics_service_caches_repeated_load_requests_within_ttl() -> None:
    repository = FakeMetricsRepository()
    service = _build_metrics_service(repository)

    first_response = service.get_load_metrics(
        region="ERCO",
        start_date=date(2026, 3, 28),
        end_date=date(2026, 3, 28),
        granularity="hourly",
    )
    second_response = service.get_load_metrics(
        region="ERCO",
        start_date=date(2026, 3, 28),
        end_date=date(2026, 3, 28),
        granularity="hourly",
    )

    assert repository.load_call_count == 1
    assert first_response == second_response


def test_metric_endpoints_include_request_id_header() -> None:
    client = _build_test_client(StubMetricsService())

    response = client.get(
        "/metrics/top-regions",
        params={
            "start_date": "2026-03-20",
            "end_date": "2026-03-28",
            "limit": 3,
        },
        headers={"x-request-id": "req-123"},
    )

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "req-123"
