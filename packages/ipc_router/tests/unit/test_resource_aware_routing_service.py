"""Comprehensive unit tests for ResourceAwareRoutingService."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from ipc_client_sdk.models import ServiceInfo, ServiceInstanceInfo
from ipc_router.application.models.routing_models import RouteRequest
from ipc_router.application.services import ResourceAwareRoutingService, ResourceRegistry
from ipc_router.domain.entities import ServiceInstance
from ipc_router.domain.enums import ServiceStatus
from ipc_router.domain.exceptions import NotFoundError
from ipc_router.domain.interfaces.load_balancer import LoadBalancer


class TestResourceAwareRoutingService:
    """Comprehensive test suite for ResourceAwareRoutingService."""

    @pytest.fixture
    def mock_resource_registry(self) -> MagicMock:
        """Create a mock ResourceRegistry."""
        mock = MagicMock(spec=ResourceRegistry)
        mock.get_service = AsyncMock()
        mock.get_resource_owner = AsyncMock()
        mock.release_resource = AsyncMock()
        mock.list_services = AsyncMock()
        return mock

    @pytest.fixture
    def mock_load_balancer(self) -> MagicMock:
        """Create a mock LoadBalancer."""
        mock = MagicMock(spec=LoadBalancer)
        mock.select_instance = MagicMock()  # Not async in the interface
        return mock

    @pytest.fixture
    def routing_service(
        self, mock_resource_registry: MagicMock, mock_load_balancer: MagicMock
    ) -> ResourceAwareRoutingService:
        """Create a ResourceAwareRoutingService instance."""
        return ResourceAwareRoutingService(
            resource_registry=mock_resource_registry,
            load_balancer=mock_load_balancer,
        )

    @pytest.fixture
    def route_request(self) -> RouteRequest:
        """Create a basic route request."""
        return RouteRequest(
            service_name="test-service",
            method="test_method",
            params={"key": "value"},
            timeout=30.0,
            trace_id="trace-123",
        )

    @pytest.fixture
    def route_request_with_resource(self) -> RouteRequest:
        """Create a route request with resource ID."""
        return RouteRequest(
            service_name="test-service",
            resource_id="resource-456",
            method="test_method",
            params={"key": "value"},
            timeout=30.0,
            trace_id="trace-123",
        )

    @pytest.fixture
    def service_info(self) -> ServiceInfo:
        """Create a mock service info with healthy instances."""
        instances = [
            ServiceInstanceInfo(
                instance_id="instance-1",
                status="ONLINE",
                registered_at="2025-01-01T00:00:00Z",
                last_heartbeat="2025-01-01T00:01:00Z",
                metadata={},
            ),
            ServiceInstanceInfo(
                instance_id="instance-2",
                status="ONLINE",
                registered_at="2025-01-01T00:00:00Z",
                last_heartbeat="2025-01-01T00:01:00Z",
                metadata={},
            ),
        ]
        return ServiceInfo(
            name="test-service",
            instances=instances,
            created_at="2025-01-01T00:00:00Z",
            metadata={},
        )

    @pytest.mark.asyncio
    async def test_route_request_without_resource_id(
        self,
        routing_service: ResourceAwareRoutingService,
        mock_resource_registry: MagicMock,
        mock_load_balancer: MagicMock,
        route_request: RouteRequest,
        service_info: ServiceInfo,
    ) -> None:
        """Test routing without resource ID falls back to standard routing."""
        # Setup mocks
        mock_resource_registry.get_service.return_value = service_info

        # Create a mock service instance to return from load balancer
        selected_instance = ServiceInstance(
            service_name="test-service",
            instance_id="instance-1",
            registered_at="2025-01-01T00:00:00Z",
            status=ServiceStatus.ONLINE,
        )
        mock_load_balancer.select_instance.return_value = selected_instance

        # Route request
        response = await routing_service.route_request(route_request)

        # Verify response
        assert response.success is True
        assert response.instance_id == "instance-1"
        assert response.error is None

        # Verify load balancer was used
        mock_load_balancer.select_instance.assert_called_once()
        # Verify resource owner lookup was not called
        mock_resource_registry.get_resource_owner.assert_not_called()

    @pytest.mark.asyncio
    async def test_route_request_with_resource_id_success(
        self,
        routing_service: ResourceAwareRoutingService,
        mock_resource_registry: MagicMock,
        route_request_with_resource: RouteRequest,
        service_info: ServiceInfo,
    ) -> None:
        """Test successful routing to resource owner."""
        # Setup mocks
        mock_resource_registry.get_resource_owner.return_value = "instance-2"
        mock_resource_registry.get_service.return_value = service_info

        # Route request
        response = await routing_service.route_request(route_request_with_resource)

        # Verify response
        assert response.success is True
        assert response.instance_id == "instance-2"
        assert response.error is None

        # Verify resource owner was looked up
        mock_resource_registry.get_resource_owner.assert_called_once_with("resource-456")
        # Verify service info was fetched to check instance health
        mock_resource_registry.get_service.assert_called_once_with("test-service")

    @pytest.mark.asyncio
    async def test_route_request_resource_not_found(
        self,
        routing_service: ResourceAwareRoutingService,
        mock_resource_registry: MagicMock,
        route_request_with_resource: RouteRequest,
    ) -> None:
        """Test routing when resource is not found."""
        # Setup mocks - resource doesn't exist
        mock_resource_registry.get_resource_owner.return_value = None

        # Route request
        response = await routing_service.route_request(route_request_with_resource)

        # Verify response
        assert response.success is False
        assert response.error is not None
        assert response.error["type"] == "ResourceNotFoundError"
        assert response.error["code"] == 404
        assert "resource-456" in response.error["message"]

    @pytest.mark.asyncio
    async def test_route_request_resource_owner_unhealthy(
        self,
        routing_service: ResourceAwareRoutingService,
        mock_resource_registry: MagicMock,
        route_request_with_resource: RouteRequest,
    ) -> None:
        """Test routing when resource owner instance is unhealthy."""
        # Setup mocks - owner is offline
        mock_resource_registry.get_resource_owner.return_value = "instance-2"

        # Service info with offline instance
        instances = [
            ServiceInstanceInfo(
                instance_id="instance-1",
                status="ONLINE",
                registered_at="2025-01-01T00:00:00Z",
                last_heartbeat="2025-01-01T00:01:00Z",
                metadata={},
            ),
            ServiceInstanceInfo(
                instance_id="instance-2",
                status="OFFLINE",  # Unhealthy
                registered_at="2025-01-01T00:00:00Z",
                last_heartbeat="2025-01-01T00:00:00Z",
                metadata={},
            ),
        ]
        service_info = ServiceInfo(
            name="test-service",
            instances=instances,
            created_at="2025-01-01T00:00:00Z",
            metadata={},
        )
        mock_resource_registry.get_service.return_value = service_info

        # Route request
        response = await routing_service.route_request(route_request_with_resource)

        # Verify response
        assert response.success is False
        assert response.error is not None
        assert response.error["type"] == "ServiceUnavailableError"
        assert response.error["code"] == 503
        assert "instance-2" in response.error["message"]
        assert "not healthy" in response.error["message"]

    @pytest.mark.asyncio
    async def test_route_request_resource_orphaned(
        self,
        routing_service: ResourceAwareRoutingService,
        mock_resource_registry: MagicMock,
        route_request_with_resource: RouteRequest,
    ) -> None:
        """Test routing when resource exists but service doesn't."""
        # Setup mocks - resource exists but service doesn't
        mock_resource_registry.get_resource_owner.return_value = "instance-2"
        mock_resource_registry.get_service.side_effect = NotFoundError(
            resource_type="Service", resource_id="test-service"
        )
        mock_resource_registry.release_resource.return_value = True

        # Route request
        response = await routing_service.route_request(route_request_with_resource)

        # Verify response
        assert response.success is False
        assert response.error is not None
        assert response.error["type"] == "ServiceNotFoundError"
        assert response.error["code"] == 404
        assert "orphaned" in response.error["message"]

        # Verify cleanup was attempted
        mock_resource_registry.release_resource.assert_called_once_with(
            "resource-456", "instance-2"
        )

    @pytest.mark.asyncio
    async def test_route_request_resource_orphaned_cleanup_fails(
        self,
        routing_service: ResourceAwareRoutingService,
        mock_resource_registry: MagicMock,
        route_request_with_resource: RouteRequest,
    ) -> None:
        """Test routing when resource cleanup fails."""
        # Setup mocks - resource exists but service doesn't, cleanup fails
        mock_resource_registry.get_resource_owner.return_value = "instance-2"
        mock_resource_registry.get_service.side_effect = NotFoundError(
            resource_type="Service", resource_id="test-service"
        )
        mock_resource_registry.release_resource.side_effect = Exception("Cleanup failed")

        # Route request
        response = await routing_service.route_request(route_request_with_resource)

        # Verify response (should still return service not found)
        assert response.success is False
        assert response.error is not None
        assert response.error["type"] == "ServiceNotFoundError"
        assert response.error["code"] == 404

    @pytest.mark.asyncio
    async def test_route_request_unexpected_error(
        self,
        routing_service: ResourceAwareRoutingService,
        mock_resource_registry: MagicMock,
        route_request_with_resource: RouteRequest,
    ) -> None:
        """Test handling of unexpected errors during routing."""
        # Setup mocks - unexpected error
        mock_resource_registry.get_resource_owner.side_effect = RuntimeError("Unexpected!")

        # Route request
        response = await routing_service.route_request(route_request_with_resource)

        # Verify response
        assert response.success is False
        assert response.error is not None
        assert response.error["type"] == "RuntimeError"
        assert response.error["code"] == 500
        assert "Unexpected!" in response.error["message"]

    @pytest.mark.asyncio
    async def test_get_routing_stats(
        self,
        routing_service: ResourceAwareRoutingService,
    ) -> None:
        """Test getting routing statistics."""
        stats = await routing_service.get_routing_stats()

        assert stats["resource_routing_enabled"] is True
        assert "load_balancer" in stats

    @pytest.mark.asyncio
    async def test_routing_performance(
        self,
        routing_service: ResourceAwareRoutingService,
        mock_resource_registry: MagicMock,
        route_request_with_resource: RouteRequest,
        service_info: ServiceInfo,
    ) -> None:
        """Test that routing completes within reasonable time."""
        # Setup mocks
        mock_resource_registry.get_resource_owner.return_value = "instance-1"
        mock_resource_registry.get_service.return_value = service_info

        # Route request and measure time
        start_time = time.time()
        response = await routing_service.route_request(route_request_with_resource)
        duration = time.time() - start_time

        # Verify response
        assert response.success is True
        assert response.duration_ms > 0
        assert response.duration_ms < 100  # Should complete within 100ms
        assert duration < 0.1  # Actual duration should be under 100ms

    @pytest.mark.asyncio
    async def test_default_load_balancer_creation(
        self,
        mock_resource_registry: MagicMock,
    ) -> None:
        """Test that default load balancer is created when none provided."""
        # Create service without load balancer
        service = ResourceAwareRoutingService(resource_registry=mock_resource_registry)

        # Verify default load balancer was created
        assert service._load_balancer is not None
        # Verify default load balancer was created
        from ipc_router.domain.strategies.round_robin import RoundRobinLoadBalancer

        assert isinstance(service._load_balancer, RoundRobinLoadBalancer)

    @pytest.mark.asyncio
    async def test_concurrent_resource_routing(
        self,
        routing_service: ResourceAwareRoutingService,
        mock_resource_registry: MagicMock,
        service_info: ServiceInfo,
    ) -> None:
        """Test concurrent resource-based routing requests."""
        import asyncio

        # Setup mocks
        mock_resource_registry.get_service.return_value = service_info

        # Different resources owned by different instances
        resource_owners = {
            "resource-1": "instance-1",
            "resource-2": "instance-2",
            "resource-3": "instance-1",
            "resource-4": "instance-2",
        }

        async def get_owner(resource_id: str) -> str | None:
            return resource_owners.get(resource_id)

        mock_resource_registry.get_resource_owner.side_effect = get_owner

        # Create multiple requests
        requests = []
        for i in range(1, 5):
            req = RouteRequest(
                service_name="test-service",
                resource_id=f"resource-{i}",
                method="test_method",
                params={},
                timeout=30.0,
                trace_id=f"trace-{i}",
            )
            requests.append(req)

        # Route all requests concurrently
        responses = await asyncio.gather(*[routing_service.route_request(req) for req in requests])

        # Verify all responses
        assert len(responses) == 4
        assert all(r.success for r in responses)

        # Verify correct routing
        assert responses[0].instance_id == "instance-1"  # resource-1
        assert responses[1].instance_id == "instance-2"  # resource-2
        assert responses[2].instance_id == "instance-1"  # resource-3
        assert responses[3].instance_id == "instance-2"  # resource-4

    @pytest.mark.asyncio
    async def test_resource_routing_with_metadata(
        self,
        routing_service: ResourceAwareRoutingService,
        mock_resource_registry: MagicMock,
        service_info: ServiceInfo,
    ) -> None:
        """Test resource routing preserves request metadata."""
        # Setup mocks
        mock_resource_registry.get_resource_owner.return_value = "instance-1"
        mock_resource_registry.get_service.return_value = service_info

        # Create request with metadata
        request = RouteRequest(
            service_name="test-service",
            resource_id="resource-789",
            method="update_resource",
            params={"data": "value", "metadata": {"user": "test-user"}},
            timeout=60.0,
            trace_id="trace-metadata",
        )

        # Route request
        response = await routing_service.route_request(request)

        # Verify response preserves trace ID
        assert response.success is True
        assert response.trace_id == "trace-metadata"
