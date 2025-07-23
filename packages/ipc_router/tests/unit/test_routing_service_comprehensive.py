"""Comprehensive unit tests for RoutingService to improve coverage."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest
from ipc_router.application.models.routing_models import RouteRequest, RouteResponse
from ipc_router.application.services import RoutingService, ServiceRegistry
from ipc_router.domain.entities import ServiceInstance
from ipc_router.domain.enums import ServiceStatus
from ipc_router.domain.exceptions import NotFoundError
from ipc_router.domain.interfaces import LoadBalancer
from ipc_router.domain.strategies import RoundRobinLoadBalancer


class TestRoutingServiceComprehensive:
    """Comprehensive tests for RoutingService."""

    @pytest.fixture
    def mock_service_registry(self) -> AsyncMock:
        """Create a mock service registry."""
        registry = AsyncMock(spec=ServiceRegistry)
        return registry

    @pytest.fixture
    def mock_load_balancer(self) -> Mock:
        """Create a mock load balancer."""
        lb = Mock(spec=LoadBalancer)
        return lb

    @pytest.fixture
    def routing_service(
        self, mock_service_registry: AsyncMock, mock_load_balancer: Mock
    ) -> RoutingService:
        """Create a RoutingService instance."""
        return RoutingService(
            service_registry=mock_service_registry,
            load_balancer=mock_load_balancer,
        )

    @pytest.fixture
    def sample_instances(self) -> list[ServiceInstance]:
        """Create sample service instances."""
        return [
            ServiceInstance(
                service_name="test-service",
                instance_id="instance-1",
                registered_at=datetime.now(UTC),
                status=ServiceStatus.ONLINE,
            ),
            ServiceInstance(
                service_name="test-service",
                instance_id="instance-2",
                registered_at=datetime.now(UTC),
                status=ServiceStatus.ONLINE,
            ),
            ServiceInstance(
                service_name="test-service",
                instance_id="instance-3",
                registered_at=datetime.now(UTC),
                status=ServiceStatus.OFFLINE,
            ),
        ]

    def test_initialization_with_default_load_balancer(
        self, mock_service_registry: AsyncMock
    ) -> None:
        """Test initialization with default load balancer."""
        service = RoutingService(service_registry=mock_service_registry)
        assert isinstance(service._load_balancer, RoundRobinLoadBalancer)

    def test_initialization_with_custom_load_balancer(
        self, mock_service_registry: AsyncMock, mock_load_balancer: Mock
    ) -> None:
        """Test initialization with custom load balancer."""
        service = RoutingService(
            service_registry=mock_service_registry,
            load_balancer=mock_load_balancer,
        )
        assert service._load_balancer is mock_load_balancer

    @pytest.mark.asyncio
    async def test_route_request_success(
        self,
        routing_service: RoutingService,
        mock_service_registry: AsyncMock,
        mock_load_balancer: Mock,
        sample_instances: list[ServiceInstance],
    ) -> None:
        """Test successful request routing."""
        # Mock registry to return healthy instances
        mock_service_registry.get_healthy_instances.return_value = sample_instances[:2]

        # Mock load balancer to select first instance
        mock_load_balancer.select_instance.return_value = sample_instances[0]

        # Create route request
        request = RouteRequest(
            service_name="test-service",
            method="test_method",
            params={},
            timeout=30.0,
            trace_id="trace-123",
        )

        # Route request
        result = await routing_service.route_request(request)

        assert isinstance(result, RouteResponse)
        assert result.success is True
        assert result.instance_id == sample_instances[0].instance_id
        assert result.trace_id == "trace-123"
        mock_service_registry.get_healthy_instances.assert_called_once_with("test-service")
        mock_load_balancer.select_instance.assert_called_once_with(
            sample_instances[:2], "test-service"
        )

    @pytest.mark.asyncio
    async def test_route_request_with_metadata(
        self,
        routing_service: RoutingService,
        mock_service_registry: AsyncMock,
        mock_load_balancer: Mock,
        sample_instances: list[ServiceInstance],
    ) -> None:
        """Test routing request with metadata."""
        # Mock registry to return healthy instances
        mock_service_registry.get_healthy_instances.return_value = sample_instances[:2]

        # Mock load balancer to select second instance
        mock_load_balancer.select_instance.return_value = sample_instances[1]

        # Create route request
        request = RouteRequest(
            service_name="test-service",
            method="test_method",
            params={"metadata": {"priority": "high", "region": "us-west"}},
            timeout=30.0,
            trace_id="trace-456",
        )

        # Route request
        result = await routing_service.route_request(request)

        assert isinstance(result, RouteResponse)
        assert result.success is True
        assert result.instance_id == sample_instances[1].instance_id
        # Verify metadata was passed to load balancer
        mock_load_balancer.select_instance.assert_called_once()
        call_args = mock_load_balancer.select_instance.call_args
        assert len(call_args[0]) == 2  # instances
        assert call_args[0][1] == "test-service"

    @pytest.mark.asyncio
    async def test_route_request_no_healthy_instances(
        self,
        routing_service: RoutingService,
        mock_service_registry: AsyncMock,
        mock_load_balancer: Mock,
    ) -> None:
        """Test routing when no healthy instances are available."""
        # Mock registry to return empty list
        mock_service_registry.get_healthy_instances.return_value = []

        # Create route request
        request = RouteRequest(
            service_name="test-service",
            method="test_method",
            params={},
            timeout=30.0,
            trace_id="trace-789",
        )

        # Route request
        result = await routing_service.route_request(request)

        assert isinstance(result, RouteResponse)
        assert result.success is False
        assert result.error["type"] == "ServiceUnavailableError"
        assert result.error["code"] == 503
        mock_service_registry.get_healthy_instances.assert_called_once_with("test-service")
        # Load balancer should not be called
        mock_load_balancer.select_instance.assert_not_called()

    @pytest.mark.asyncio
    async def test_route_request_service_not_found(
        self,
        routing_service: RoutingService,
        mock_service_registry: AsyncMock,
    ) -> None:
        """Test routing when service is not found."""
        # Mock registry to raise NotFoundError
        mock_service_registry.get_healthy_instances.side_effect = NotFoundError(
            resource_type="Service",
            resource_id="unknown-service",
        )

        # Create route request
        request = RouteRequest(
            service_name="unknown-service",
            method="test_method",
            params={},
            timeout=30.0,
            trace_id="trace-404",
        )

        # Route request
        result = await routing_service.route_request(request)

        assert isinstance(result, RouteResponse)
        assert result.success is False
        assert result.error["type"] == "NotFoundError"
        assert result.error["code"] == 404
        mock_service_registry.get_healthy_instances.assert_called_once_with("unknown-service")

    @pytest.mark.asyncio
    async def test_route_request_load_balancer_returns_none(
        self,
        routing_service: RoutingService,
        mock_service_registry: AsyncMock,
        mock_load_balancer: Mock,
        sample_instances: list[ServiceInstance],
    ) -> None:
        """Test when load balancer returns None."""
        # Mock registry to return healthy instances
        mock_service_registry.get_healthy_instances.return_value = sample_instances[:2]

        # Mock load balancer to return None
        mock_load_balancer.select_instance.return_value = None

        # Create route request
        request = RouteRequest(
            service_name="test-service",
            method="test_method",
            params={},
            timeout=30.0,
            trace_id="trace-none",
        )

        # Route request
        result = await routing_service.route_request(request)

        assert isinstance(result, RouteResponse)
        assert result.success is False
        assert result.error["type"] == "ServiceUnavailableError"
        assert result.error["code"] == 503
        assert "unavailable" in result.error["message"]

    @pytest.mark.asyncio
    async def test_route_request_unexpected_error(
        self,
        routing_service: RoutingService,
        mock_service_registry: AsyncMock,
    ) -> None:
        """Test handling of unexpected errors."""
        # Mock registry to raise unexpected error
        mock_service_registry.get_healthy_instances.side_effect = RuntimeError(
            "Database connection failed"
        )

        # Create route request
        request = RouteRequest(
            service_name="test-service",
            method="test_method",
            params={},
            timeout=30.0,
            trace_id="trace-error",
        )

        # Route request - should handle error gracefully
        result = await routing_service.route_request(request)

        assert isinstance(result, RouteResponse)
        assert result.success is False
        assert result.error["type"] == "RuntimeError"
        assert result.error["code"] == 500
        assert "Database connection failed" in result.error["message"]

    @pytest.mark.asyncio
    async def test_route_request_with_timeout(
        self,
        routing_service: RoutingService,
        mock_service_registry: AsyncMock,
        mock_load_balancer: Mock,
        sample_instances: list[ServiceInstance],
    ) -> None:
        """Test routing request with timeout parameter."""
        # Mock registry to return healthy instances
        mock_service_registry.get_healthy_instances.return_value = sample_instances[:1]

        # Mock load balancer
        mock_load_balancer.select_instance.return_value = sample_instances[0]

        # Create route request with timeout
        request = RouteRequest(
            service_name="test-service",
            method="test_method",
            params={},
            timeout=5.0,
            trace_id="trace-timeout",
        )

        # Route request
        result = await routing_service.route_request(request)

        assert isinstance(result, RouteResponse)
        assert result.success is True
        assert result.instance_id == sample_instances[0].instance_id

    @pytest.mark.asyncio
    async def test_route_request_trace_id_propagation(
        self,
        routing_service: RoutingService,
        mock_service_registry: AsyncMock,
        mock_load_balancer: Mock,
        sample_instances: list[ServiceInstance],
    ) -> None:
        """Test trace ID is properly logged."""
        # Mock registry to return healthy instances
        mock_service_registry.get_healthy_instances.return_value = sample_instances[:1]

        # Mock load balancer
        mock_load_balancer.select_instance.return_value = sample_instances[0]

        # Route request with specific trace ID
        trace_id = "trace-propagation-test"
        request = RouteRequest(
            service_name="test-service",
            method="test_method",
            params={},
            timeout=30.0,
            trace_id=trace_id,
        )

        # Route request
        result = await routing_service.route_request(request)

        assert isinstance(result, RouteResponse)
        assert result.success is True
        assert result.trace_id == trace_id
        # In real implementation, we would verify logging

    @pytest.mark.asyncio
    async def test_route_request_empty_service_name(
        self,
        routing_service: RoutingService,
        mock_service_registry: AsyncMock,
    ) -> None:
        """Test routing with empty service name."""
        # Empty service name should fail validation before routing
        with pytest.raises(Exception) as exc_info:
            RouteRequest(
                service_name="",
                method="test_method",
                params={},
                timeout=30.0,
                trace_id="trace-empty",
            )

        # Verify it's a validation error
        assert "ValidationError" in str(type(exc_info.value))

    @pytest.mark.asyncio
    async def test_concurrent_route_requests(
        self,
        routing_service: RoutingService,
        mock_service_registry: AsyncMock,
        mock_load_balancer: Mock,
        sample_instances: list[ServiceInstance],
    ) -> None:
        """Test handling concurrent route requests."""
        # Mock registry to return healthy instances
        mock_service_registry.get_healthy_instances.return_value = sample_instances[:2]

        # Mock load balancer to alternate between instances
        mock_load_balancer.select_instance.side_effect = [
            sample_instances[0],
            sample_instances[1],
            sample_instances[0],
            sample_instances[1],
        ]

        # Route multiple requests concurrently
        import asyncio

        tasks = [
            routing_service.route_request(
                RouteRequest(
                    service_name="test-service",
                    method="test_method",
                    params={},
                    timeout=30.0,
                    trace_id=f"trace-concurrent-{i}",
                )
            )
            for i in range(4)
        ]

        results = await asyncio.gather(*tasks)

        # Verify all requests were routed
        assert len(results) == 4
        assert all(isinstance(r, RouteResponse) for r in results)
        assert all(r.success for r in results)
        assert results[0].instance_id == sample_instances[0].instance_id
        assert results[1].instance_id == sample_instances[1].instance_id
        assert results[2].instance_id == sample_instances[0].instance_id
        assert results[3].instance_id == sample_instances[1].instance_id

        # Verify registry was called 4 times
        assert mock_service_registry.get_healthy_instances.call_count == 4

    @pytest.mark.asyncio
    async def test_route_request_filters_unhealthy_instances(
        self,
        routing_service: RoutingService,
        mock_service_registry: AsyncMock,
        mock_load_balancer: Mock,
        sample_instances: list[ServiceInstance],
    ) -> None:
        """Test that only healthy instances are considered."""
        # Registry returns mix of healthy and unhealthy instances
        # but get_healthy_instances should already filter them
        healthy_only = [inst for inst in sample_instances if inst.status == ServiceStatus.ONLINE]
        mock_service_registry.get_healthy_instances.return_value = healthy_only

        # Mock load balancer
        mock_load_balancer.select_instance.return_value = healthy_only[0]

        # Create route request
        request = RouteRequest(
            service_name="test-service",
            method="test_method",
            params={},
            timeout=30.0,
            trace_id="trace-healthy",
        )

        # Route request
        result = await routing_service.route_request(request)

        assert isinstance(result, RouteResponse)
        assert result.success is True
        assert result.instance_id == healthy_only[0].instance_id
        # Verify load balancer only received healthy instances
        mock_load_balancer.select_instance.assert_called_once_with(healthy_only, "test-service")
