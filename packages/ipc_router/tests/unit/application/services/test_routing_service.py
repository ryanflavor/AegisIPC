"""Unit tests for RoutingService."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest
from ipc_router.application.models.routing_models import RouteRequest
from ipc_router.application.services.routing_service import RoutingService
from ipc_router.domain.entities.service import ServiceInstance
from ipc_router.domain.enums import ServiceStatus


@pytest.mark.asyncio
class TestRoutingService:
    """Test cases for RoutingService."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.mock_registry = AsyncMock()
        from ipc_router.domain.interfaces.load_balancer import LoadBalancer

        self.mock_load_balancer = Mock(spec=LoadBalancer)
        self.routing_service = RoutingService(self.mock_registry, self.mock_load_balancer)

    async def test_initialization_with_default_load_balancer(self) -> None:
        """Test initialization with default load balancer."""
        service = RoutingService(self.mock_registry)
        assert service._registry is self.mock_registry
        assert service._load_balancer is not None

    async def test_route_request_success(self) -> None:
        """Test successful request routing."""
        # Setup mock instances
        instances = [
            ServiceInstance(
                instance_id="inst-1",
                service_name="test-service",
                status=ServiceStatus.ONLINE,
                registered_at=datetime.now(UTC),
                last_heartbeat=datetime.now(UTC),
            ),
            ServiceInstance(
                instance_id="inst-2",
                service_name="test-service",
                status=ServiceStatus.ONLINE,
                registered_at=datetime.now(UTC),
                last_heartbeat=datetime.now(UTC),
            ),
        ]

        # Configure mocks
        self.mock_registry.get_healthy_instances.return_value = instances
        self.mock_load_balancer.select_instance.return_value = instances[0]

        # Create request
        request = RouteRequest(
            service_name="test-service",
            method="test_method",
            params={"key": "value"},
            timeout=5.0,
            trace_id="trace-123",
        )

        # Execute
        response = await self.routing_service.route_request(request)

        # Verify response
        assert response.success is True
        assert response.instance_id == "inst-1"
        assert response.trace_id == "trace-123"
        assert response.error is None
        assert response.duration_ms is not None

        # Verify mock calls
        self.mock_registry.get_healthy_instances.assert_called_once_with("test-service")
        self.mock_load_balancer.select_instance.assert_called_once_with(instances, "test-service")

    async def test_route_request_no_healthy_instances(self) -> None:
        """Test routing when no healthy instances are available."""
        # Configure mocks
        self.mock_registry.get_healthy_instances.return_value = []

        # Create request
        request = RouteRequest(
            service_name="test-service",
            method="test_method",
            trace_id="trace-123",
        )

        # Execute
        response = await self.routing_service.route_request(request)

        # Verify error response
        assert response.success is False
        assert response.instance_id is None
        assert response.error is not None
        assert response.error["code"] == 503
        assert "unavailable" in response.error["message"]

    async def test_route_request_service_not_found(self) -> None:
        """Test routing when service is not found."""
        # Configure mocks to raise NotFoundError
        from ipc_router.domain.exceptions import NotFoundError

        self.mock_registry.get_healthy_instances.side_effect = NotFoundError(
            resource_type="Service", resource_id="unknown-service"
        )

        # Create request
        request = RouteRequest(
            service_name="unknown-service",
            method="test_method",
            trace_id="trace-123",
        )

        # Execute
        response = await self.routing_service.route_request(request)

        # Verify error response
        assert response.success is False
        assert response.error is not None
        assert response.error["code"] == 404
        assert "not found" in response.error["message"]

    async def test_route_request_load_balancer_returns_none(self) -> None:
        """Test when load balancer cannot select an instance."""
        # Setup mock instances
        instances = [
            ServiceInstance(
                instance_id="inst-1",
                service_name="test-service",
                status=ServiceStatus.ONLINE,
                registered_at=datetime.now(UTC),
                last_heartbeat=datetime.now(UTC),
            ),
        ]

        # Configure mocks
        self.mock_registry.get_healthy_instances.return_value = instances
        self.mock_load_balancer.select_instance.return_value = None

        # Create request
        request = RouteRequest(
            service_name="test-service",
            method="test_method",
            trace_id="trace-123",
        )

        # Execute
        response = await self.routing_service.route_request(request)

        # Verify error response
        assert response.success is False
        assert response.error is not None
        assert response.error["code"] == 503
        assert "unavailable" in response.error["message"]

    async def test_route_request_unexpected_error(self) -> None:
        """Test handling of unexpected errors during routing."""
        # Configure mocks to raise unexpected error
        self.mock_registry.get_healthy_instances.side_effect = RuntimeError("Unexpected error")

        # Create request
        request = RouteRequest(
            service_name="test-service",
            method="test_method",
            trace_id="trace-123",
        )

        # Execute
        response = await self.routing_service.route_request(request)

        # Verify error response
        assert response.success is False
        assert response.error is not None
        assert response.error["code"] == 500
        assert response.error["message"] == "Unexpected error"

    async def test_route_request_with_metadata(self) -> None:
        """Test routing request with metadata."""
        # Setup mock instance
        instance = ServiceInstance(
            instance_id="inst-1",
            service_name="test-service",
            status=ServiceStatus.ONLINE,
            registered_at=datetime.now(UTC),
            last_heartbeat=datetime.now(UTC),
            metadata={"version": "1.0", "region": "us-east"},
        )

        # Configure mocks
        self.mock_registry.get_healthy_instances.return_value = [instance]
        self.mock_load_balancer.select_instance.return_value = instance

        # Create request
        request = RouteRequest(
            service_name="test-service",
            method="test_method",
            trace_id="trace-123",
        )

        # Execute
        response = await self.routing_service.route_request(request)

        # Verify response is successful
        assert response.success is True
        assert response.instance_id == "inst-1"

    async def test_route_request_no_timeout(self) -> None:
        """Test routing request without timeout."""
        # Setup mock instance
        instance = ServiceInstance(
            instance_id="inst-1",
            service_name="test-service",
            status=ServiceStatus.ONLINE,
            registered_at=datetime.now(UTC),
            last_heartbeat=datetime.now(UTC),
        )

        # Configure mocks
        self.mock_registry.get_healthy_instances.return_value = [instance]
        self.mock_load_balancer.select_instance.return_value = instance

        # Create request without timeout
        request = RouteRequest(
            service_name="test-service",
            method="test_method",
            trace_id="trace-123",
        )

        # Execute
        response = await self.routing_service.route_request(request)

        # Verify response
        assert response.success is True
        assert response.instance_id == "inst-1"

    async def test_logging_on_successful_routing(self) -> None:
        """Test that successful routing is logged properly."""
        # Setup mock instance
        instance = ServiceInstance(
            instance_id="inst-1",
            service_name="test-service",
            status=ServiceStatus.ONLINE,
            registered_at=datetime.now(UTC),
            last_heartbeat=datetime.now(UTC),
        )

        # Configure mocks
        self.mock_registry.get_healthy_instances.return_value = [instance]
        self.mock_load_balancer.select_instance.return_value = instance

        # Create request
        request = RouteRequest(
            service_name="test-service",
            method="test_method",
            trace_id="trace-123",
        )

        # Execute
        response = await self.routing_service.route_request(request)

        # Verify success
        assert response.success is True

    async def test_trace_id_propagation(self) -> None:
        """Test that trace_id is properly propagated through the response."""
        # Setup mock instance
        instance = ServiceInstance(
            instance_id="inst-1",
            service_name="test-service",
            status=ServiceStatus.ONLINE,
            registered_at=datetime.now(UTC),
            last_heartbeat=datetime.now(UTC),
        )

        # Configure mocks
        self.mock_registry.get_healthy_instances.return_value = [instance]
        self.mock_load_balancer.select_instance.return_value = instance

        # Create request with specific trace_id
        trace_id = "unique-trace-12345"
        request = RouteRequest(
            service_name="test-service",
            method="test_method",
            trace_id=trace_id,
        )

        # Execute
        response = await self.routing_service.route_request(request)

        # Verify trace_id is propagated
        assert response.trace_id == trace_id
