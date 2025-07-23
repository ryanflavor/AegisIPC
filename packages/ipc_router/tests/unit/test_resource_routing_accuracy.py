"""Unit tests for resource routing accuracy."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from ipc_router.application.models import RouteRequest
from ipc_router.application.services import (
    ResourceAwareRoutingService,
    ResourceRegistry,
    ServiceRegistry,
)
from ipc_router.domain.entities import ResourceMetadata, ServiceInstance
from ipc_router.domain.exceptions import (
    ResourceNotFoundError,
    ServiceUnavailableError,
)


class TestResourceRoutingAccuracy:
    """Test accurate routing of requests based on resource ownership."""

    @pytest.fixture
    def service_registry(self) -> MagicMock:
        """Create a mock service registry."""
        mock = MagicMock(spec=ServiceRegistry)
        mock.get_healthy_instances = AsyncMock()
        mock.get_instance = AsyncMock()
        return mock

    @pytest.fixture
    def resource_registry(self) -> MagicMock:
        """Create a mock resource registry."""
        mock = MagicMock(spec=ResourceRegistry)
        mock.get_resource_owner = AsyncMock()
        return mock

    @pytest.fixture
    def logger(self) -> MagicMock:
        """Create a mock logger."""
        return MagicMock()

    @pytest.fixture
    def routing_service(
        self,
        service_registry: MagicMock,
        resource_registry: MagicMock,
        logger: MagicMock,
    ) -> ResourceAwareRoutingService:
        """Create a ResourceAwareRoutingService instance."""
        service = ResourceAwareRoutingService(
            service_registry=service_registry,
            resource_registry=resource_registry,
        )
        # Replace logger with mock
        service._logger = logger
        return service

    @pytest.fixture
    def sample_instances(self) -> list[ServiceInstance]:
        """Create sample service instances."""
        return [
            ServiceInstance(
                service_name="test-service",
                instance_id=f"instance-{i}",
                registered_at=datetime.now(UTC),
            )
            for i in range(3)
        ]

    @pytest.mark.asyncio
    async def test_route_with_resource_id_success(
        self,
        routing_service: ResourceAwareRoutingService,
        service_registry: MagicMock,
        resource_registry: MagicMock,
        sample_instances: list[ServiceInstance],
    ) -> None:
        """Test successful routing with resource ID."""
        # Setup mocks
        resource_registry.get_resource_owner.return_value = "instance-1"
        service_registry.get_instance.return_value = sample_instances[1]

        # Create request with resource ID
        request = RouteRequest(
            service_name="test-service",
            resource_id="resource-123",
            method="process",
            params={},
            timeout=5.0,
            trace_id="trace-123",
        )

        # Route request
        instance = await routing_service.select_instance(request)

        # Verify correct instance selected
        assert instance.instance_id == "instance-1"

        # Verify resource ownership was checked
        resource_registry.get_resource_owner.assert_called_once_with("resource-123")

        # Verify instance was retrieved
        service_registry.get_instance.assert_called_once_with("test-service", "instance-1")

    @pytest.mark.asyncio
    async def test_route_without_resource_id_round_robin(
        self,
        routing_service: ResourceAwareRoutingService,
        service_registry: MagicMock,
        resource_registry: MagicMock,
        sample_instances: list[ServiceInstance],
    ) -> None:
        """Test routing without resource ID uses round-robin."""
        # Setup mocks
        service_registry.get_healthy_instances.return_value = sample_instances

        # Create requests without resource ID
        requests = [
            RouteRequest(
                service_name="test-service",
                resource_id=None,
                method="process",
                params={},
                timeout=5.0,
                trace_id=f"trace-{i}",
            )
            for i in range(6)
        ]

        # Route requests and track instance distribution
        instance_counts: dict[str, int] = {}
        for request in requests:
            instance = await routing_service.select_instance(request)
            instance_id = instance.instance_id
            instance_counts[instance_id] = instance_counts.get(instance_id, 0) + 1

        # Verify round-robin distribution
        assert len(instance_counts) == 3  # All instances used
        assert all(count == 2 for count in instance_counts.values())  # Even distribution

        # Verify resource registry was not used
        resource_registry.get_resource_owner.assert_not_called()

    @pytest.mark.asyncio
    async def test_route_resource_not_found(
        self,
        routing_service: ResourceAwareRoutingService,
        resource_registry: MagicMock,
    ) -> None:
        """Test routing when resource is not found."""
        # Setup mocks
        resource_registry.get_resource_owner.return_value = None

        # Create request with non-existent resource
        request = RouteRequest(
            service_name="test-service",
            resource_id="non-existent",
            method="process",
            params={},
            timeout=5.0,
            trace_id="trace-123",
        )

        # Route should fail
        with pytest.raises(ResourceNotFoundError) as exc_info:
            await routing_service.select_instance(request)

        assert "Resource non-existent not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_route_resource_owner_offline(
        self,
        routing_service: ResourceAwareRoutingService,
        service_registry: MagicMock,
        resource_registry: MagicMock,
    ) -> None:
        """Test routing when resource owner is offline."""
        # Setup mocks
        resource_registry.get_resource_owner.return_value = "instance-dead"
        service_registry.get_instance.return_value = None  # Instance not found

        # Create request
        request = RouteRequest(
            service_name="test-service",
            resource_id="resource-123",
            method="process",
            params={},
            timeout=5.0,
            trace_id="trace-123",
        )

        # Route should fail
        with pytest.raises(ServiceUnavailableError) as exc_info:
            await routing_service.select_instance(request)

        assert "Instance instance-dead not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_route_multiple_resources_same_instance(
        self,
        routing_service: ResourceAwareRoutingService,
        service_registry: MagicMock,
        resource_registry: MagicMock,
        sample_instances: list[ServiceInstance],
    ) -> None:
        """Test routing multiple resources owned by same instance."""
        # Setup mocks - all resources owned by instance-2
        resource_registry.get_resource_owner.side_effect = [
            "instance-2",  # resource-1
            "instance-2",  # resource-2
            "instance-2",  # resource-3
        ]
        service_registry.get_instance.return_value = sample_instances[2]

        # Route multiple requests
        resource_ids = ["resource-1", "resource-2", "resource-3"]
        instances = []

        for resource_id in resource_ids:
            request = RouteRequest(
                service_name="test-service",
                resource_id=resource_id,
                method="process",
                params={},
                timeout=5.0,
                trace_id=f"trace-{resource_id}",
            )
            instance = await routing_service.select_instance(request)
            instances.append(instance)

        # All should route to same instance
        assert all(inst.instance_id == "instance-2" for inst in instances)
        assert resource_registry.get_resource_owner.call_count == 3

    @pytest.mark.asyncio
    async def test_route_different_resources_different_instances(
        self,
        routing_service: ResourceAwareRoutingService,
        service_registry: MagicMock,
        resource_registry: MagicMock,
        sample_instances: list[ServiceInstance],
    ) -> None:
        """Test routing resources owned by different instances."""
        # Setup mocks - resources owned by different instances
        resource_owners = {
            "resource-1": "instance-0",
            "resource-2": "instance-1",
            "resource-3": "instance-2",
        }

        async def mock_get_owner(resource_id: str) -> str | None:
            return resource_owners.get(resource_id)

        resource_registry.get_resource_owner.side_effect = mock_get_owner

        async def mock_get_instance(service_name: str, instance_id: str) -> ServiceInstance | None:
            for inst in sample_instances:
                if inst.instance_id == instance_id:
                    return inst
            return None

        service_registry.get_instance.side_effect = mock_get_instance

        # Route requests for different resources
        routed_instances = {}

        for resource_id, _ in resource_owners.items():
            request = RouteRequest(
                service_name="test-service",
                resource_id=resource_id,
                method="process",
                params={},
                timeout=5.0,
                trace_id=f"trace-{resource_id}",
            )
            instance = await routing_service.select_instance(request)
            routed_instances[resource_id] = instance.instance_id

        # Verify correct routing
        assert routed_instances == resource_owners

    @pytest.mark.asyncio
    async def test_route_caching_behavior(
        self,
        routing_service: ResourceAwareRoutingService,
        service_registry: MagicMock,
        resource_registry: MagicMock,
        sample_instances: list[ServiceInstance],
    ) -> None:
        """Test that routing doesn't cache resource ownership."""
        # First request
        resource_registry.get_resource_owner.return_value = "instance-1"
        service_registry.get_instance.return_value = sample_instances[1]

        request1 = RouteRequest(
            service_name="test-service",
            resource_id="resource-123",
            method="process",
            params={},
            timeout=5.0,
            trace_id="trace-1",
        )

        instance1 = await routing_service.select_instance(request1)
        assert instance1.instance_id == "instance-1"

        # Simulate resource transfer
        resource_registry.get_resource_owner.return_value = "instance-2"
        service_registry.get_instance.return_value = sample_instances[2]

        # Second request for same resource
        request2 = RouteRequest(
            service_name="test-service",
            resource_id="resource-123",
            method="process",
            params={},
            timeout=5.0,
            trace_id="trace-2",
        )

        instance2 = await routing_service.select_instance(request2)
        assert instance2.instance_id == "instance-2"

        # Verify ownership was checked both times (no caching)
        assert resource_registry.get_resource_owner.call_count == 2

    @pytest.mark.asyncio
    async def test_route_with_unhealthy_owner(
        self,
        routing_service: ResourceAwareRoutingService,
        service_registry: MagicMock,
        resource_registry: MagicMock,
        sample_instances: list[ServiceInstance],
    ) -> None:
        """Test routing when resource owner is unhealthy."""
        # Setup mocks
        resource_registry.get_resource_owner.return_value = "instance-1"

        # Create unhealthy instance
        unhealthy_instance = ServiceInstance(
            service_name="test-service",
            instance_id="instance-1",
            registered_at=datetime.now(UTC),
        )
        unhealthy_instance.mark_unhealthy()

        service_registry.get_instance.return_value = unhealthy_instance

        # Create request
        request = RouteRequest(
            service_name="test-service",
            resource_id="resource-123",
            method="process",
            params={},
            timeout=5.0,
            trace_id="trace-123",
        )

        # Route should fail
        with pytest.raises(ServiceUnavailableError) as exc_info:
            await routing_service.select_instance(request)

        assert "Instance instance-1 is not healthy" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_logging_resource_routing(
        self,
        routing_service: ResourceAwareRoutingService,
        service_registry: MagicMock,
        resource_registry: MagicMock,
        logger: MagicMock,
        sample_instances: list[ServiceInstance],
    ) -> None:
        """Test that resource routing is properly logged."""
        # Setup mocks
        resource_registry.get_resource_owner.return_value = "instance-1"
        service_registry.get_instance.return_value = sample_instances[1]

        # Create request
        request = RouteRequest(
            service_name="test-service",
            resource_id="resource-123",
            method="process",
            params={},
            timeout=5.0,
            trace_id="trace-123",
        )

        # Route request
        await routing_service.select_instance(request)

        # Verify logging
        logger.info.assert_called()
        log_calls = logger.info.call_args_list

        # Should log resource routing decision
        assert any("Routing to resource owner" in str(call) for call in log_calls)

        # Should include resource ID and instance ID in logs
        assert any("resource-123" in str(call) and "instance-1" in str(call) for call in log_calls)

    @pytest.mark.asyncio
    async def test_metrics_for_resource_routing(
        self,
        routing_service: ResourceAwareRoutingService,
        service_registry: MagicMock,
        resource_registry: MagicMock,
        sample_instances: list[ServiceInstance],
    ) -> None:
        """Test metrics tracking for resource-based routing."""
        # Setup for successful routing
        resource_registry.get_resource_owner.return_value = "instance-1"
        service_registry.get_instance.return_value = sample_instances[1]

        request = RouteRequest(
            service_name="test-service",
            resource_id="resource-123",
            method="process",
            params={},
            timeout=5.0,
            trace_id="trace-123",
        )

        # Successful routing
        instance = await routing_service.select_instance(request)
        assert instance.instance_id == "instance-1"

        # Setup for resource not found
        resource_registry.get_resource_owner.return_value = None

        request2 = RouteRequest(
            service_name="test-service",
            resource_id="non-existent",
            method="process",
            params={},
            timeout=5.0,
            trace_id="trace-456",
        )

        # Failed routing
        with pytest.raises(ResourceNotFoundError):
            await routing_service.select_instance(request2)

        # In a real implementation, we would verify metrics were updated
        # For now, just verify the operations completed as expected
        assert resource_registry.get_resource_owner.call_count == 2


class TestResourceRoutingEdgeCases:
    """Test edge cases in resource routing."""

    @pytest.fixture
    def real_registry(self) -> ResourceRegistry:
        """Create a real ResourceRegistry for integration-style tests."""
        return ResourceRegistry()

    @pytest.fixture
    def real_service_registry(self) -> ServiceRegistry:
        """Create a real ServiceRegistry."""
        return ServiceRegistry()

    @pytest.fixture
    def routing_service(
        self, real_service_registry: ServiceRegistry, real_registry: ResourceRegistry
    ) -> ResourceAwareRoutingService:
        """Create routing service with real registries."""
        return ResourceAwareRoutingService(
            service_registry=real_service_registry,
            resource_registry=real_registry,
        )

    @pytest.mark.asyncio
    async def test_route_after_resource_transfer(
        self,
        routing_service: ResourceAwareRoutingService,
        real_service_registry: ServiceRegistry,
        real_registry: ResourceRegistry,
    ) -> None:
        """Test routing correctly updates after resource transfer."""
        # Register instances
        for i in range(2):
            instance = ServiceInstance(
                service_name="test-service",
                instance_id=f"instance-{i}",
                registered_at=datetime.now(UTC),
            )
            await real_service_registry.register_instance(instance)

        # Register resource with instance-0
        await real_registry.register_resource(
            service_name="test-service",
            instance_id="instance-0",
            resource_id="transfer-test",
            metadata=ResourceMetadata(
                resource_type="test",
                version=1,
                created_by="test",
                last_modified=datetime.now(UTC),
            ),
        )

        # Route should go to instance-0
        request1 = RouteRequest(
            service_name="test-service",
            resource_id="transfer-test",
            method="process",
            params={},
            timeout=5.0,
            trace_id="trace-1",
        )

        instance1 = await routing_service.select_instance(request1)
        assert instance1.instance_id == "instance-0"

        # Transfer resource to instance-1
        await real_registry.transfer_resource(
            resource_id="transfer-test",
            from_instance_id="instance-0",
            to_instance_id="instance-1",
        )

        # Route should now go to instance-1
        request2 = RouteRequest(
            service_name="test-service",
            resource_id="transfer-test",
            method="process",
            params={},
            timeout=5.0,
            trace_id="trace-2",
        )

        instance2 = await routing_service.select_instance(request2)
        assert instance2.instance_id == "instance-1"

    @pytest.mark.asyncio
    async def test_concurrent_routing_consistency(
        self,
        routing_service: ResourceAwareRoutingService,
        real_service_registry: ServiceRegistry,
        real_registry: ResourceRegistry,
    ) -> None:
        """Test routing consistency under concurrent requests."""
        # Register instances
        instances = []
        for i in range(3):
            instance = ServiceInstance(
                service_name="test-service",
                instance_id=f"instance-{i}",
                registered_at=datetime.now(UTC),
            )
            await real_service_registry.register_instance(instance)
            instances.append(instance)

        # Register resources distributed across instances
        for i in range(10):
            await real_registry.register_resource(
                service_name="test-service",
                instance_id=f"instance-{i % 3}",
                resource_id=f"resource-{i}",
                metadata=ResourceMetadata(
                    resource_type="test",
                    version=1,
                    created_by="test",
                    last_modified=datetime.now(UTC),
                ),
            )

        # Concurrent routing requests
        async def route_request(resource_id: str) -> str:
            request = RouteRequest(
                service_name="test-service",
                resource_id=resource_id,
                method="process",
                params={},
                timeout=5.0,
                trace_id=f"trace-{resource_id}",
            )
            instance = await routing_service.select_instance(request)
            assert instance is not None
            instance_id = instance.instance_id
            assert isinstance(instance_id, str)
            return instance_id

        # Route all resources concurrently
        tasks = [route_request(f"resource-{i}") for i in range(10)]
        results = await asyncio.gather(*tasks)

        # Verify correct routing
        for i, instance_id in enumerate(results):
            expected_instance = f"instance-{i % 3}"
            assert instance_id == expected_instance
