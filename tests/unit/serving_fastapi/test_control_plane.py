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
from app.routers.control_plane import get_control_plane_service  # noqa: E402
from app.exceptions.base import ValidationAppError  # noqa: E402
from app.services.control_plane import ControlPlaneService, combine_freshness_status  # noqa: E402


class StubControlPlaneService:
    def __init__(self) -> None:
        self.anomaly_calls: list[dict[str, object]] = []

    def get_freshness(self) -> dict[str, object]:
        return {
            "pipeline_freshness_timestamp": datetime(2026, 3, 28, 10, 0, tzinfo=UTC),
            "data_freshness_timestamp": datetime(2026, 3, 28, 9, 30, tzinfo=UTC),
            "pipeline_freshness_status": "fresh",
            "data_freshness_status": "stale",
            "freshness_status": "stale",
            "checked_at": datetime(2026, 3, 28, 10, 15, tzinfo=UTC),
        }

    def get_pipeline_status(self) -> dict[str, object]:
        return {
            "pipeline_name": "eia_grid_batch",
            "last_successful_window_start": datetime(2026, 3, 28, 9, 0, tzinfo=UTC),
            "last_successful_window_end": datetime(2026, 3, 28, 10, 0, tzinfo=UTC),
            "last_successful_run_id": "scheduled__2026-03-28T10:00:00+00:00",
            "updated_at": datetime(2026, 3, 28, 10, 10, tzinfo=UTC),
        }

    def get_anomalies(
        self,
        *,
        region: str | None,
        start_date: date | None,
        end_date: date | None,
        anomaly_only: bool,
    ) -> list[dict[str, object]]:
        self.anomaly_calls.append(
            {
                "region": region,
                "start_date": start_date,
                "end_date": end_date,
                "anomaly_only": anomaly_only,
            }
        )
        return [
            {
                "observation_date": date(2026, 3, 28),
                "region": region or "ERCO",
                "metric_name": "demand",
                "current_value": 100.0,
                "rolling_7d_avg": 75.0,
                "pct_deviation": 33.33,
                "anomaly_flag": anomaly_only,
                "checked_at": datetime(2026, 3, 28, 10, 15, tzinfo=UTC),
            }
        ]


class EmptyControlPlaneService:
    def __init__(self) -> None:
        self.anomaly_calls: list[dict[str, object]] = []

    def get_freshness(self) -> dict[str, object]:
        return {
            "pipeline_freshness_timestamp": None,
            "data_freshness_timestamp": None,
            "pipeline_freshness_status": "unknown",
            "data_freshness_status": "unknown",
            "freshness_status": "unknown",
            "checked_at": None,
        }

    def get_pipeline_status(self) -> dict[str, object]:
        return {
            "pipeline_name": None,
            "last_successful_window_start": None,
            "last_successful_window_end": None,
            "last_successful_run_id": None,
            "updated_at": None,
        }

    def get_anomalies(
        self,
        *,
        region: str | None,
        start_date: date | None,
        end_date: date | None,
        anomaly_only: bool,
    ) -> list[dict[str, object]]:
        self.anomaly_calls.append(
            {
                "region": region,
                "start_date": start_date,
                "end_date": end_date,
                "anomaly_only": anomaly_only,
            }
        )
        return []


class FakeControlPlaneRepository:
    def get_latest_freshness(self) -> dict[str, object] | None:
        return None

    def get_latest_pipeline_status(self) -> dict[str, object] | None:
        return None

    def list_anomalies(self, **_: object) -> list[dict[str, object]]:
        return []


def _build_test_client(service: StubControlPlaneService) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_control_plane_service] = lambda: service
    return TestClient(app)


def _build_test_client_with_real_control_plane_service() -> TestClient:
    app = create_app()
    service = ControlPlaneService(repository=FakeControlPlaneRepository())  # type: ignore[arg-type]
    app.dependency_overrides[get_control_plane_service] = lambda: service
    return TestClient(app)


def test_health_endpoint_does_not_require_bigquery() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_freshness_endpoint_returns_combined_status() -> None:
    client = _build_test_client(StubControlPlaneService())

    response = client.get("/freshness")

    assert response.status_code == 200
    payload = response.json()
    assert payload["pipeline_freshness_status"] == "fresh"
    assert payload["data_freshness_status"] == "stale"
    assert payload["freshness_status"] == "stale"


def test_freshness_endpoint_returns_unknown_when_no_records_exist() -> None:
    client = _build_test_client(EmptyControlPlaneService())

    response = client.get("/freshness")

    assert response.status_code == 200
    assert response.json() == {
        "pipeline_freshness_timestamp": None,
        "data_freshness_timestamp": None,
        "pipeline_freshness_status": "unknown",
        "data_freshness_status": "unknown",
        "freshness_status": "unknown",
        "checked_at": None,
    }


def test_pipeline_status_endpoint_returns_latest_sync_window() -> None:
    client = _build_test_client(StubControlPlaneService())

    response = client.get("/pipeline/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["pipeline_name"] == "eia_grid_batch"
    assert payload["last_successful_run_id"] == "scheduled__2026-03-28T10:00:00+00:00"


def test_pipeline_status_endpoint_returns_null_fields_when_pipeline_never_ran() -> None:
    client = _build_test_client(EmptyControlPlaneService())

    response = client.get("/pipeline/status")

    assert response.status_code == 200
    assert response.json() == {
        "pipeline_name": None,
        "last_successful_window_start": None,
        "last_successful_window_end": None,
        "last_successful_run_id": None,
        "updated_at": None,
    }


def test_anomalies_endpoint_passes_filters_through_service() -> None:
    service = StubControlPlaneService()
    client = _build_test_client(service)

    response = client.get(
        "/anomalies",
        params={
            "region": "CISO",
            "start_date": "2026-03-20",
            "end_date": "2026-03-28",
            "anomaly_only": "false",
        },
    )

    assert response.status_code == 200
    assert response.json()[0]["region"] == "CISO"
    assert service.anomaly_calls == [
        {
            "region": "CISO",
            "start_date": date(2026, 3, 20),
            "end_date": date(2026, 3, 28),
            "anomaly_only": False,
        }
    ]


def test_anomalies_endpoint_defaults_to_flagged_results_only() -> None:
    service = EmptyControlPlaneService()
    client = _build_test_client(service)

    response = client.get("/anomalies")

    assert response.status_code == 200
    assert response.json() == []
    assert service.anomaly_calls == [
        {
            "region": None,
            "start_date": None,
            "end_date": None,
            "anomaly_only": True,
        }
    ]


def test_anomalies_endpoint_rejects_inverted_date_range_with_structured_error() -> None:
    client = _build_test_client_with_real_control_plane_service()

    response = client.get(
        "/anomalies",
        params={
            "start_date": "2026-03-29",
            "end_date": "2026-03-28",
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "error": "validation_error",
        "detail": "start_date must be less than or equal to end_date",
    }


def test_health_endpoint_echoes_request_id_header() -> None:
    client = TestClient(create_app())

    response = client.get("/health", headers={"x-request-id": "health-req-1"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "health-req-1"


def test_combine_freshness_status_uses_worse_signal() -> None:
    assert combine_freshness_status("fresh", "fresh") == "fresh"
    assert combine_freshness_status("fresh", "stale") == "stale"
    assert combine_freshness_status("unknown", "fresh") == "unknown"


def test_control_plane_service_rejects_inverted_date_range() -> None:
    service = ControlPlaneService(repository=object())  # type: ignore[arg-type]

    try:
        service.get_anomalies(
            region=None,
            start_date=date(2026, 3, 29),
            end_date=date(2026, 3, 28),
            anomaly_only=True,
        )
    except ValidationAppError as exc:
        assert str(exc) == "start_date must be less than or equal to end_date"
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("Expected an inverted date range error")
