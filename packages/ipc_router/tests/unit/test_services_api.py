"""Unit tests for REST API endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

# Skip tests if FastAPI is not installed
fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from ipc_client_sdk.models import (  # noqa: E402
    ServiceInfo,
    ServiceInstanceInfo,
    ServiceListResponse,
)
from ipc_router.api.admin import create_admin_router  # noqa: E402
from ipc_router.application.services import ServiceRegistry  # noqa: E402
from ipc_router.domain.exceptions import NotFoundError  # noqa: E402


@pytest.fixture
def mock_service_registry() -> AsyncMock:
    """Create a mock service registry."""
    return AsyncMock(spec=ServiceRegistry)


@pytest.fixture
def test_app(mock_service_registry: AsyncMock) -> FastAPI:
    """Create a FastAPI test application."""
    app = FastAPI()
    admin_router = create_admin_router(mock_service_registry)
    app.include_router(admin_router)
    return app


@pytest.fixture
def test_client(test_app: FastAPI) -> TestClient:
    """Create a test client."""
    return TestClient(test_app)


class TestServicesAPI:
    """Tests for service management REST API."""

    def test_list_services_empty(
        self,
        test_client: TestClient,
        mock_service_registry: AsyncMock,
    ) -> None:
        """Test listing services when registry is empty."""
        # Setup mock
        mock_service_registry.list_services.return_value = ServiceListResponse(
            services=[],
            total_count=0,
        )

        # Make request
        response = test_client.get("/api/v1/admin/services")

        # Verify
        assert response.status_code == 200
        data = response.json()
        assert data["services"] == []
        assert data["total_count"] == 0
        mock_service_registry.list_services.assert_called_once()

    def test_list_services_with_data(
        self,
        test_client: TestClient,
        mock_service_registry: AsyncMock,
    ) -> None:
        """Test listing services with multiple services."""
        # Setup mock data
        now = datetime.now(UTC)
        services = [
            ServiceInfo(
                name="service-1",
                instances=[
                    ServiceInstanceInfo(
                        instance_id="instance-1-1",
                        status="ONLINE",
                        registered_at=now,
                        last_heartbeat=now,
                    ),
                    ServiceInstanceInfo(
                        instance_id="instance-1-2",
                        status="OFFLINE",
                        registered_at=now,
                        last_heartbeat=now,
                    ),
                ],
                created_at=now,
                metadata={"version": "1.0.0"},
            ),
            ServiceInfo(
                name="service-2",
                instances=[
                    ServiceInstanceInfo(
                        instance_id="instance-2-1",
                        status="ONLINE",
                        registered_at=now,
                        last_heartbeat=now,
                    ),
                ],
                created_at=now,
                metadata={},
            ),
        ]

        mock_service_registry.list_services.return_value = ServiceListResponse(
            services=services,
            total_count=2,
        )

        # Make request
        response = test_client.get("/api/v1/admin/services")

        # Verify
        assert response.status_code == 200
        data = response.json()
        assert data["total_count"] == 2
        assert len(data["services"]) == 2
        assert data["services"][0]["name"] == "service-1"
        assert len(data["services"][0]["instances"]) == 2
        assert data["services"][1]["name"] == "service-2"
        assert len(data["services"][1]["instances"]) == 1

    def test_list_services_error(
        self,
        test_client: TestClient,
        mock_service_registry: AsyncMock,
    ) -> None:
        """Test error handling when listing services fails."""
        # Setup mock to raise exception
        mock_service_registry.list_services.side_effect = Exception("Database error")

        # Make request
        response = test_client.get("/api/v1/admin/services")

        # Verify
        assert response.status_code == 500
        data = response.json()
        assert data["detail"] == "Failed to retrieve services"

    def test_get_service_success(
        self,
        test_client: TestClient,
        mock_service_registry: AsyncMock,
    ) -> None:
        """Test getting a specific service."""
        # Setup mock data
        now = datetime.now(UTC)
        service_info = ServiceInfo(
            name="test-service",
            instances=[
                ServiceInstanceInfo(
                    instance_id="instance-1",
                    status="ONLINE",
                    registered_at=now,
                    last_heartbeat=now,
                    metadata={"zone": "us-east-1"},
                ),
            ],
            created_at=now,
            metadata={"owner": "team-a"},
        )

        mock_service_registry.get_service.return_value = service_info

        # Make request
        response = test_client.get("/api/v1/admin/services/test-service")

        # Verify
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "test-service"
        assert len(data["instances"]) == 1
        assert data["instances"][0]["instance_id"] == "instance-1"
        assert data["instances"][0]["status"] == "ONLINE"
        assert data["metadata"]["owner"] == "team-a"
        mock_service_registry.get_service.assert_called_once_with("test-service")

    def test_get_service_not_found(
        self,
        test_client: TestClient,
        mock_service_registry: AsyncMock,
    ) -> None:
        """Test getting a non-existent service."""
        # Setup mock to raise NotFoundError
        mock_service_registry.get_service.side_effect = NotFoundError(
            resource_type="Service",
            resource_id="non-existent",
        )

        # Make request
        response = test_client.get("/api/v1/admin/services/non-existent")

        # Verify
        assert response.status_code == 404
        data = response.json()
        assert data["detail"] == "Service 'non-existent' not found"

    def test_get_service_error(
        self,
        test_client: TestClient,
        mock_service_registry: AsyncMock,
    ) -> None:
        """Test error handling when getting service fails."""
        # Setup mock to raise exception
        mock_service_registry.get_service.side_effect = Exception("Database error")

        # Make request
        response = test_client.get("/api/v1/admin/services/test-service")

        # Verify
        assert response.status_code == 500
        data = response.json()
        assert data["detail"] == "Failed to retrieve service information"

    def test_check_health_all_healthy(
        self,
        test_client: TestClient,
        mock_service_registry: AsyncMock,
    ) -> None:
        """Test health check with all services healthy."""
        # Setup mock
        mock_service_registry.check_health.return_value = {
            "total_services": 3,
            "total_instances": 10,
            "healthy_instances": 10,
            "unhealthy_services": [],
            "health_percentage": 100.0,
        }

        # Make request
        response = test_client.get("/api/v1/admin/health")

        # Verify
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["total_services"] == 3
        assert data["total_instances"] == 10
        assert data["healthy_instances"] == 10
        assert data["health_percentage"] == 100.0

    def test_check_health_partially_healthy(
        self,
        test_client: TestClient,
        mock_service_registry: AsyncMock,
    ) -> None:
        """Test health check with some unhealthy services."""
        # Setup mock
        mock_service_registry.check_health.return_value = {
            "total_services": 3,
            "total_instances": 10,
            "healthy_instances": 8,
            "unhealthy_services": [
                {
                    "service_name": "service-1",
                    "total_instances": 3,
                    "healthy_instances": 1,
                }
            ],
            "health_percentage": 80.0,
        }

        # Make request
        response = test_client.get("/api/v1/admin/health")

        # Verify
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"  # 80% is still considered healthy
        assert data["health_percentage"] == 80.0
        assert len(data["unhealthy_services"]) == 1

    def test_check_health_unhealthy(
        self,
        test_client: TestClient,
        mock_service_registry: AsyncMock,
    ) -> None:
        """Test health check with system unhealthy."""
        # Setup mock
        mock_service_registry.check_health.return_value = {
            "total_services": 3,
            "total_instances": 10,
            "healthy_instances": 5,
            "unhealthy_services": [
                {
                    "service_name": "service-1",
                    "total_instances": 5,
                    "healthy_instances": 0,
                },
                {
                    "service_name": "service-2",
                    "total_instances": 3,
                    "healthy_instances": 2,
                },
            ],
            "health_percentage": 50.0,
        }

        # Make request
        response = test_client.get("/api/v1/admin/health")

        # Verify
        assert response.status_code == 503  # Service Unavailable
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["health_percentage"] == 50.0
        assert len(data["unhealthy_services"]) == 2

    def test_check_health_error(
        self,
        test_client: TestClient,
        mock_service_registry: AsyncMock,
    ) -> None:
        """Test health check error handling."""
        # Setup mock to raise exception
        mock_service_registry.check_health.side_effect = Exception("Check failed")

        # Make request
        response = test_client.get("/api/v1/admin/health")

        # Verify
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "error"
        assert data["error"] == "Check failed"

    def test_api_documentation(
        self,
        test_client: TestClient,
    ) -> None:
        """Test that API documentation is available."""
        # FastAPI automatically generates OpenAPI docs
        response = test_client.get("/openapi.json")

        # Verify
        assert response.status_code == 200
        data = response.json()

        # Check that our endpoints are documented
        paths = data.get("paths", {})
        assert "/api/v1/admin/services" in paths
        assert "/api/v1/admin/services/{service_name}" in paths
        assert "/api/v1/admin/health" in paths

        # Check operations
        services_path = paths["/api/v1/admin/services"]
        assert "get" in services_path
        assert services_path["get"]["summary"] == "List all registered services"

        service_detail_path = paths["/api/v1/admin/services/{service_name}"]
        assert "get" in service_detail_path
        assert service_detail_path["get"]["summary"] == "Get service details"

    def test_service_name_with_special_characters(
        self,
        test_client: TestClient,
        mock_service_registry: AsyncMock,
    ) -> None:
        """Test getting service with special characters in name."""
        # Setup mock data
        now = datetime.now(UTC)
        service_info = ServiceInfo(
            name="test-service.v2",
            instances=[],
            created_at=now,
            metadata={},
        )

        mock_service_registry.get_service.return_value = service_info

        # Make request with URL-encoded name
        response = test_client.get("/api/v1/admin/services/test-service.v2")

        # Verify
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "test-service.v2"
        mock_service_registry.get_service.assert_called_once_with("test-service.v2")

    def test_get_service_roles(
        self,
        test_client: TestClient,
        mock_service_registry: AsyncMock,
    ) -> None:
        """Test getting service role information."""
        # Setup mock data with mixed roles
        now = datetime.now(UTC)
        service_info = ServiceInfo(
            name="test-service",
            instances=[
                ServiceInstanceInfo(
                    instance_id="instance-1",
                    status="ONLINE",
                    role="ACTIVE",
                    registered_at=now,
                    last_heartbeat=now,
                ),
                ServiceInstanceInfo(
                    instance_id="instance-2",
                    status="ONLINE",
                    role="STANDBY",
                    registered_at=now,
                    last_heartbeat=now,
                ),
                ServiceInstanceInfo(
                    instance_id="instance-3",
                    status="ONLINE",
                    role="STANDBY",
                    registered_at=now,
                    last_heartbeat=now,
                ),
                ServiceInstanceInfo(
                    instance_id="instance-4",
                    status="ONLINE",
                    role=None,  # Should default to standby
                    registered_at=now,
                    last_heartbeat=now,
                ),
            ],
            created_at=now,
            metadata={},
        )

        mock_service_registry.get_service.return_value = service_info

        # Make request
        response = test_client.get("/api/v1/admin/services/test-service/roles")

        # Verify
        assert response.status_code == 200
        data = response.json()
        assert data["service_name"] == "test-service"
        assert "roles" in data

        roles = data["roles"]
        assert roles["service_name"] == "test-service"
        assert len(roles["active_instances"]) == 1
        assert "instance-1" in roles["active_instances"]
        assert len(roles["standby_instances"]) == 3
        assert "instance-2" in roles["standby_instances"]
        assert "instance-3" in roles["standby_instances"]
        assert "instance-4" in roles["standby_instances"]  # None defaults to standby

        mock_service_registry.get_service.assert_called_once_with("test-service")

    def test_get_service_roles_not_found(
        self,
        test_client: TestClient,
        mock_service_registry: AsyncMock,
    ) -> None:
        """Test getting role information for non-existent service."""
        # Setup mock to raise NotFoundError
        mock_service_registry.get_service.side_effect = NotFoundError(
            resource_type="Service",
            resource_id="non-existent",
        )

        # Make request
        response = test_client.get("/api/v1/admin/services/non-existent/roles")

        # Verify
        assert response.status_code == 404
        data = response.json()
        assert data["detail"] == "Service 'non-existent' not found"

    def test_get_service_roles_empty_service(
        self,
        test_client: TestClient,
        mock_service_registry: AsyncMock,
    ) -> None:
        """Test getting role information for service with no instances."""
        # Setup mock data with no instances
        now = datetime.now(UTC)
        service_info = ServiceInfo(
            name="empty-service",
            instances=[],
            created_at=now,
            metadata={},
        )

        mock_service_registry.get_service.return_value = service_info

        # Make request
        response = test_client.get("/api/v1/admin/services/empty-service/roles")

        # Verify
        assert response.status_code == 200
        data = response.json()
        assert data["service_name"] == "empty-service"

        roles = data["roles"]
        assert len(roles["active_instances"]) == 0
        assert len(roles["standby_instances"]) == 0
