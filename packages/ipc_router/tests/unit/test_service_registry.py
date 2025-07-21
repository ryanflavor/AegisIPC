"""Unit tests for ServiceRegistry application service."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from ipc_client_sdk.models import (
    ServiceRegistrationRequest,
)
from ipc_router.application.services import ServiceRegistry
from ipc_router.domain.exceptions import DuplicateServiceInstanceError, NotFoundError


@pytest.fixture
def service_registry() -> ServiceRegistry:
    """Create a ServiceRegistry instance for testing."""
    return ServiceRegistry()


@pytest.fixture
def registration_request() -> ServiceRegistrationRequest:
    """Create a sample registration request."""
    return ServiceRegistrationRequest(
        service_name="test-service",
        instance_id="test_instance_01",
        metadata={"version": "1.0.0"},
    )


class TestServiceRegistry:
    """Tests for ServiceRegistry application service."""

    def test_initialization(self, service_registry: ServiceRegistry) -> None:
        """Test ServiceRegistry initialization."""
        assert service_registry._services == {}
        assert service_registry._lock is not None

    @pytest.mark.asyncio
    async def test_register_service_success(
        self,
        service_registry: ServiceRegistry,
        registration_request: ServiceRegistrationRequest,
    ) -> None:
        """Test successful service registration."""
        response = await service_registry.register_service(registration_request)

        assert response.success is True
        assert response.service_name == "test-service"
        assert response.instance_id == "test_instance_01"
        assert response.message == "Service instance registered successfully"
        assert isinstance(response.registered_at, datetime)

        # Verify service was created
        assert "test-service" in service_registry._services
        service = service_registry._services["test-service"]
        assert service.name == "test-service"
        assert service.instance_count == 1

    @pytest.mark.asyncio
    async def test_register_service_duplicate_instance(
        self,
        service_registry: ServiceRegistry,
        registration_request: ServiceRegistrationRequest,
    ) -> None:
        """Test registering duplicate instance raises error."""
        # Register first time
        await service_registry.register_service(registration_request)

        # Try to register again with same instance ID
        with pytest.raises(DuplicateServiceInstanceError) as exc_info:
            await service_registry.register_service(registration_request)

        assert "test-service" in str(exc_info.value)
        assert "test_instance_01" in str(exc_info.value)
        assert exc_info.value.details.get("conflicting_resource") == "test-service/test_instance_01"

    @pytest.mark.asyncio
    async def test_register_multiple_instances_same_service(
        self,
        service_registry: ServiceRegistry,
    ) -> None:
        """Test registering multiple instances for the same service."""
        # Register first instance
        request1 = ServiceRegistrationRequest(
            service_name="test-service",
            instance_id="instance_01",
            metadata={"zone": "us-east-1"},
        )
        response1 = await service_registry.register_service(request1)
        assert response1.success is True

        # Register second instance
        request2 = ServiceRegistrationRequest(
            service_name="test-service",
            instance_id="instance_02",
            metadata={"zone": "us-west-1"},
        )
        response2 = await service_registry.register_service(request2)
        assert response2.success is True

        # Verify both instances exist
        service = service_registry._services["test-service"]
        assert service.instance_count == 2
        assert service.get_instance("instance_01") is not None
        assert service.get_instance("instance_02") is not None

    @pytest.mark.asyncio
    async def test_get_service_success(
        self,
        service_registry: ServiceRegistry,
        registration_request: ServiceRegistrationRequest,
    ) -> None:
        """Test getting service information."""
        # Register a service
        await service_registry.register_service(registration_request)

        # Get service info
        service_info = await service_registry.get_service("test-service")

        assert service_info.name == "test-service"
        assert len(service_info.instances) == 1
        assert service_info.instances[0].instance_id == "test_instance_01"
        assert service_info.instances[0].status == "ONLINE"

    @pytest.mark.asyncio
    async def test_get_service_not_found(
        self,
        service_registry: ServiceRegistry,
    ) -> None:
        """Test getting non-existent service raises NotFoundError."""
        with pytest.raises(NotFoundError) as exc_info:
            await service_registry.get_service("non-existent")

        assert exc_info.value.details["resource_type"] == "Service"
        assert exc_info.value.details["resource_id"] == "non-existent"

    @pytest.mark.asyncio
    async def test_list_services_empty(
        self,
        service_registry: ServiceRegistry,
    ) -> None:
        """Test listing services when registry is empty."""
        response = await service_registry.list_services()

        assert response.services == []
        assert response.total_count == 0

    @pytest.mark.asyncio
    async def test_list_services_multiple(
        self,
        service_registry: ServiceRegistry,
    ) -> None:
        """Test listing multiple services."""
        # Register services
        services = [
            ("service-1", "instance-1-1"),
            ("service-1", "instance-1-2"),
            ("service-2", "instance-2-1"),
            ("service-3", "instance-3-1"),
        ]

        for service_name, instance_id in services:
            request = ServiceRegistrationRequest(
                service_name=service_name,
                instance_id=instance_id,
            )
            await service_registry.register_service(request)

        # List services
        response = await service_registry.list_services()

        assert response.total_count == 3
        assert len(response.services) == 3

        # Check service names
        service_names = {s.name for s in response.services}
        assert service_names == {"service-1", "service-2", "service-3"}

        # Check instance counts
        service_1 = next(s for s in response.services if s.name == "service-1")
        assert len(service_1.instances) == 2

    @pytest.mark.asyncio
    async def test_update_heartbeat_success(
        self,
        service_registry: ServiceRegistry,
        registration_request: ServiceRegistrationRequest,
    ) -> None:
        """Test updating heartbeat for existing instance."""
        # Register service
        await service_registry.register_service(registration_request)

        # Get original heartbeat
        service = service_registry._services["test-service"]
        instance = service.get_instance("test_instance_01")
        original_heartbeat = instance.last_heartbeat

        # Mock time to ensure heartbeat changes
        future_time = datetime.now(UTC) + timedelta(seconds=5)
        with patch("ipc_router.domain.entities.service.datetime") as mock_datetime:
            mock_datetime.now.return_value = future_time

            # Update heartbeat
            await service_registry.update_heartbeat("test-service", "test_instance_01")

        # Verify heartbeat was updated
        assert instance.last_heartbeat == future_time
        assert instance.last_heartbeat > original_heartbeat

    @pytest.mark.asyncio
    async def test_update_heartbeat_service_not_found(
        self,
        service_registry: ServiceRegistry,
    ) -> None:
        """Test updating heartbeat for non-existent service."""
        with pytest.raises(NotFoundError) as exc_info:
            await service_registry.update_heartbeat("non-existent", "instance")

        assert exc_info.value.details["resource_type"] == "Service"
        assert exc_info.value.details["resource_id"] == "non-existent"

    @pytest.mark.asyncio
    async def test_update_heartbeat_instance_not_found(
        self,
        service_registry: ServiceRegistry,
        registration_request: ServiceRegistrationRequest,
    ) -> None:
        """Test updating heartbeat for non-existent instance."""
        # Register service
        await service_registry.register_service(registration_request)

        with pytest.raises(NotFoundError) as exc_info:
            await service_registry.update_heartbeat("test-service", "non-existent")

        assert exc_info.value.details["resource_type"] == "ServiceInstance"
        assert exc_info.value.details["resource_id"] == "test-service/non-existent"

    @pytest.mark.asyncio
    async def test_unregister_instance_success(
        self,
        service_registry: ServiceRegistry,
        registration_request: ServiceRegistrationRequest,
    ) -> None:
        """Test unregistering an instance."""
        # Register service
        await service_registry.register_service(registration_request)

        # Unregister instance
        await service_registry.unregister_instance("test-service", "test_instance_01")

        # Verify service was removed (no more instances)
        assert "test-service" not in service_registry._services

    @pytest.mark.asyncio
    async def test_unregister_instance_service_remains(
        self,
        service_registry: ServiceRegistry,
    ) -> None:
        """Test service remains after unregistering one of multiple instances."""
        # Register two instances
        for i in range(2):
            request = ServiceRegistrationRequest(
                service_name="test-service",
                instance_id=f"instance_{i}",
            )
            await service_registry.register_service(request)

        # Unregister one instance
        await service_registry.unregister_instance("test-service", "instance_0")

        # Verify service still exists with one instance
        assert "test-service" in service_registry._services
        service = service_registry._services["test-service"]
        assert service.instance_count == 1
        assert service.get_instance("instance_1") is not None

    @pytest.mark.asyncio
    async def test_unregister_instance_service_not_found(
        self,
        service_registry: ServiceRegistry,
    ) -> None:
        """Test unregistering instance for non-existent service."""
        with pytest.raises(NotFoundError) as exc_info:
            await service_registry.unregister_instance("non-existent", "instance")

        assert exc_info.value.details["resource_type"] == "Service"
        assert exc_info.value.details["resource_id"] == "non-existent"

    @pytest.mark.asyncio
    async def test_unregister_instance_not_found(
        self,
        service_registry: ServiceRegistry,
        registration_request: ServiceRegistrationRequest,
    ) -> None:
        """Test unregistering non-existent instance."""
        # Register service
        await service_registry.register_service(registration_request)

        with pytest.raises(NotFoundError) as exc_info:
            await service_registry.unregister_instance("test-service", "non-existent")

        assert exc_info.value.details["resource_type"] == "ServiceInstance"
        assert exc_info.value.details["resource_id"] == "test-service/non-existent"

    @pytest.mark.asyncio
    async def test_check_health_empty_registry(
        self,
        service_registry: ServiceRegistry,
    ) -> None:
        """Test health check with empty registry."""
        health_status = await service_registry.check_health()

        assert health_status["total_services"] == 0
        assert health_status["total_instances"] == 0
        assert health_status["healthy_instances"] == 0
        assert health_status["unhealthy_services"] == []
        assert health_status["health_percentage"] == 0

    @pytest.mark.asyncio
    async def test_check_health_all_healthy(
        self,
        service_registry: ServiceRegistry,
    ) -> None:
        """Test health check with all healthy instances."""
        # Register services
        for i in range(2):
            request = ServiceRegistrationRequest(
                service_name=f"service-{i}",
                instance_id=f"instance-{i}",
            )
            await service_registry.register_service(request)

        health_status = await service_registry.check_health()

        assert health_status["total_services"] == 2
        assert health_status["total_instances"] == 2
        assert health_status["healthy_instances"] == 2
        assert health_status["unhealthy_services"] == []
        assert health_status["health_percentage"] == 100.0

    @pytest.mark.asyncio
    async def test_check_health_with_unhealthy_instances(
        self,
        service_registry: ServiceRegistry,
    ) -> None:
        """Test health check with some unhealthy instances."""
        # Register services
        now = datetime.now(UTC)

        # Healthy service
        request1 = ServiceRegistrationRequest(
            service_name="healthy-service",
            instance_id="healthy-instance",
        )
        await service_registry.register_service(request1)

        # Service with unhealthy instance
        request2 = ServiceRegistrationRequest(
            service_name="mixed-service",
            instance_id="healthy-instance",
        )
        await service_registry.register_service(request2)

        request3 = ServiceRegistrationRequest(
            service_name="mixed-service",
            instance_id="unhealthy-instance",
        )
        await service_registry.register_service(request3)

        # Make one instance unhealthy by setting old heartbeat
        service = service_registry._services["mixed-service"]
        unhealthy_instance = service.get_instance("unhealthy-instance")
        unhealthy_instance.last_heartbeat = now - timedelta(seconds=60)

        health_status = await service_registry.check_health(timeout_seconds=30)

        assert health_status["total_services"] == 2
        assert health_status["total_instances"] == 3
        assert health_status["healthy_instances"] == 2
        assert len(health_status["unhealthy_services"]) == 1

        unhealthy_service = health_status["unhealthy_services"][0]
        assert unhealthy_service["service_name"] == "mixed-service"
        assert unhealthy_service["total_instances"] == 2
        assert unhealthy_service["healthy_instances"] == 1
        assert health_status["health_percentage"] == pytest.approx(66.67, rel=0.01)

    @pytest.mark.asyncio
    async def test_concurrent_registration(
        self,
        service_registry: ServiceRegistry,
    ) -> None:
        """Test concurrent registration of multiple instances."""
        import asyncio

        async def register_instance(instance_id: str) -> None:
            request = ServiceRegistrationRequest(
                service_name="concurrent-service",
                instance_id=instance_id,
            )
            await service_registry.register_service(request)

        # Register 10 instances concurrently
        tasks = [register_instance(f"instance_{i}") for i in range(10)]
        await asyncio.gather(*tasks)

        # Verify all instances were registered
        assert "concurrent-service" in service_registry._services
        service = service_registry._services["concurrent-service"]
        assert service.instance_count == 10

    @pytest.mark.asyncio
    async def test_logging_calls(
        self,
        service_registry: ServiceRegistry,
        registration_request: ServiceRegistrationRequest,
    ) -> None:
        """Test that appropriate logging calls are made."""
        with patch("ipc_router.application.services.service_registry.logger") as mock_logger:
            # Test registration logging
            await service_registry.register_service(registration_request)

            # Should log service creation and registration
            assert mock_logger.info.call_count >= 2

            # Test list services logging
            await service_registry.list_services()
            assert mock_logger.debug.called

            # Test health check logging
            await service_registry.check_health()
            assert mock_logger.info.called
