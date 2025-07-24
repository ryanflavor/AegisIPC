"""Unit tests for instance-level failover functionality."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from ipc_router.application.models import RouteRequest
from ipc_router.application.services import RoutingService, ServiceRegistry
from ipc_router.domain.entities import ServiceInstance
from ipc_router.domain.enums import ServiceStatus
from ipc_router.domain.interfaces import LoadBalancer


class TestInstanceFailover:
    """Test instance-level retry and failover functionality."""

    @pytest.fixture
    def mock_registry(self) -> AsyncMock:
        """Create mock service registry."""
        registry = AsyncMock(spec=ServiceRegistry)
        return registry

    @pytest.fixture
    def mock_load_balancer(self) -> MagicMock:
        """Create mock load balancer."""
        balancer = MagicMock(spec=LoadBalancer)
        return balancer

    @pytest.fixture
    def routing_service(
        self, mock_registry: AsyncMock, mock_load_balancer: MagicMock
    ) -> RoutingService:
        """Create routing service with mocks."""
        mock_message_store = AsyncMock()
        return RoutingService(
            service_registry=mock_registry,
            load_balancer=mock_load_balancer,
            message_store=mock_message_store,
        )

    @pytest.fixture
    def healthy_instances(self) -> list[ServiceInstance]:
        """Create test healthy instances."""
        return [
            ServiceInstance(
                instance_id="instance-1",
                service_name="test-service",
                status=ServiceStatus.ONLINE,
                registered_at=datetime.now(UTC),
                last_heartbeat=datetime.now(UTC),
                metadata={"host": "host1", "port": 8001},
            ),
            ServiceInstance(
                instance_id="instance-2",
                service_name="test-service",
                status=ServiceStatus.ONLINE,
                registered_at=datetime.now(UTC),
                last_heartbeat=datetime.now(UTC),
                metadata={"host": "host2", "port": 8002},
            ),
            ServiceInstance(
                instance_id="instance-3",
                service_name="test-service",
                status=ServiceStatus.ONLINE,
                registered_at=datetime.now(UTC),
                last_heartbeat=datetime.now(UTC),
                metadata={"host": "host3", "port": 8003},
            ),
        ]

    @pytest.mark.asyncio
    async def test_excluded_instances_filtered(
        self,
        routing_service: RoutingService,
        mock_registry: AsyncMock,
        mock_load_balancer: MagicMock,
        healthy_instances: list[ServiceInstance],
    ) -> None:
        """Test that excluded instances are filtered from selection."""
        # Setup registry to return all healthy instances
        mock_registry.get_healthy_instances.return_value = healthy_instances

        # Create request with excluded instances
        request = RouteRequest(
            service_name="test-service",
            method="test_method",
            params={},
            trace_id="test-trace",
            excluded_instances=["instance-1", "instance-3"],  # Exclude 2 instances
        )

        # Setup load balancer to return instance-2
        mock_load_balancer.select_instance.return_value = healthy_instances[1]

        # Route request
        await routing_service.route_request(request)

        # Verify only non-excluded instances were passed to load balancer
        mock_load_balancer.select_instance.assert_called_once()
        available_instances = mock_load_balancer.select_instance.call_args[0][0]
        assert len(available_instances) == 1
        assert available_instances[0].instance_id == "instance-2"

    @pytest.mark.asyncio
    async def test_no_available_instances_after_exclusion(
        self,
        routing_service: RoutingService,
        mock_registry: AsyncMock,
        healthy_instances: list[ServiceInstance],
    ) -> None:
        """Test error when all instances are excluded."""
        # Setup registry to return healthy instances
        mock_registry.get_healthy_instances.return_value = healthy_instances

        # Create request excluding all instances
        request = RouteRequest(
            service_name="test-service",
            method="test_method",
            params={},
            trace_id="test-trace",
            excluded_instances=["instance-1", "instance-2", "instance-3"],
        )

        # Should return error response
        response = await routing_service.route_request(request)

        # Verify error response
        assert response.success is False
        assert response.error["type"] == "ServiceUnavailableError"
        assert "unavailable" in response.error["message"]
        assert response.error["code"] == 503

    @pytest.mark.asyncio
    async def test_partial_exclusion_still_routes(
        self,
        routing_service: RoutingService,
        mock_registry: AsyncMock,
        mock_load_balancer: MagicMock,
        healthy_instances: list[ServiceInstance],
    ) -> None:
        """Test that routing works with partial instance exclusion."""
        # Setup registry
        mock_registry.get_healthy_instances.return_value = healthy_instances

        # Exclude only one instance
        request = RouteRequest(
            service_name="test-service",
            method="test_method",
            params={},
            trace_id="test-trace",
            excluded_instances=["instance-2"],
        )

        # Setup load balancer
        mock_load_balancer.select_instance.return_value = healthy_instances[0]

        # Route request
        await routing_service.route_request(request)

        # Verify correct instances were available
        available_instances = mock_load_balancer.select_instance.call_args[0][0]
        assert len(available_instances) == 2
        instance_ids = {inst.instance_id for inst in available_instances}
        assert instance_ids == {"instance-1", "instance-3"}

    @pytest.mark.asyncio
    async def test_empty_excluded_instances_uses_all(
        self,
        routing_service: RoutingService,
        mock_registry: AsyncMock,
        mock_load_balancer: MagicMock,
        healthy_instances: list[ServiceInstance],
    ) -> None:
        """Test that empty excluded_instances uses all healthy instances."""
        # Setup registry
        mock_registry.get_healthy_instances.return_value = healthy_instances

        # Request with empty excluded_instances
        request = RouteRequest(
            service_name="test-service",
            method="test_method",
            params={},
            trace_id="test-trace",
            excluded_instances=[],  # Empty list
        )

        # Setup load balancer
        mock_load_balancer.select_instance.return_value = healthy_instances[0]

        # Route request
        await routing_service.route_request(request)

        # All instances should be available
        available_instances = mock_load_balancer.select_instance.call_args[0][0]
        assert len(available_instances) == 3

    @pytest.mark.asyncio
    async def test_excluded_unhealthy_instances_ignored(
        self,
        routing_service: RoutingService,
        mock_registry: AsyncMock,
        mock_load_balancer: MagicMock,
    ) -> None:
        """Test that excluding already unhealthy instances doesn't affect routing."""
        # Create mix of healthy and unhealthy instances
        instances = [
            ServiceInstance(
                instance_id="healthy-1",
                service_name="test-service",
                status=ServiceStatus.ONLINE,
                registered_at=datetime.now(UTC),
                last_heartbeat=datetime.now(UTC),
                metadata={"host": "host1", "port": 8001},
            ),
            ServiceInstance(
                instance_id="healthy-2",
                service_name="test-service",
                status=ServiceStatus.ONLINE,
                registered_at=datetime.now(UTC),
                last_heartbeat=datetime.now(UTC),
                metadata={"host": "host2", "port": 8002},
            ),
        ]

        # Registry returns only healthy instances
        mock_registry.get_healthy_instances.return_value = instances

        # Exclude a non-existent/unhealthy instance
        request = RouteRequest(
            service_name="test-service",
            method="test_method",
            params={},
            trace_id="test-trace",
            excluded_instances=["unhealthy-1", "non-existent"],
        )

        # Setup load balancer
        mock_load_balancer.select_instance.return_value = instances[0]

        # Route request
        await routing_service.route_request(request)

        # All healthy instances should still be available
        available_instances = mock_load_balancer.select_instance.call_args[0][0]
        assert len(available_instances) == 2

    @pytest.mark.asyncio
    async def test_route_response_includes_instance_id(
        self,
        routing_service: RoutingService,
        mock_registry: AsyncMock,
        mock_load_balancer: MagicMock,
        healthy_instances: list[ServiceInstance],
    ) -> None:
        """Test that route request correctly selects an instance."""
        # Setup registry
        mock_registry.get_healthy_instances.return_value = healthy_instances

        # Setup load balancer to select instance-2
        selected_instance = healthy_instances[1]
        mock_load_balancer.select_instance.return_value = selected_instance

        # Create request
        request = RouteRequest(
            service_name="test-service",
            method="test_method",
            params={},
            trace_id="test-trace",
        )

        # Route request
        response = await routing_service.route_request(request)

        # Verify the selected instance was used
        assert response.instance_id == selected_instance.instance_id
        assert response.instance_id == "instance-2"

    @pytest.mark.asyncio
    async def test_concurrent_requests_with_exclusions(
        self,
        routing_service: RoutingService,
        mock_registry: AsyncMock,
        mock_load_balancer: MagicMock,
        healthy_instances: list[ServiceInstance],
    ) -> None:
        """Test that concurrent requests with different exclusions work correctly."""
        # Setup registry
        mock_registry.get_healthy_instances.return_value = healthy_instances

        # Create multiple requests with different exclusions
        requests = [
            RouteRequest(
                service_name="test-service",
                method="method1",
                params={},
                trace_id="trace-1",
                excluded_instances=["instance-1"],
            ),
            RouteRequest(
                service_name="test-service",
                method="method2",
                params={},
                trace_id="trace-2",
                excluded_instances=["instance-2"],
            ),
            RouteRequest(
                service_name="test-service",
                method="method3",
                params={},
                trace_id="trace-3",
                excluded_instances=["instance-3"],
            ),
        ]

        # Setup load balancer to return different instances
        mock_load_balancer.select_instance.side_effect = [
            healthy_instances[1],  # instance-2 for request 1
            healthy_instances[0],  # instance-1 for request 2
            healthy_instances[0],  # instance-1 for request 3
        ]

        # Route all requests concurrently
        await asyncio.gather(*[routing_service.route_request(req) for req in requests])

        # Verify each request had correct exclusions
        assert mock_load_balancer.select_instance.call_count == 3

        # Check first call excluded instance-1
        call1_instances = mock_load_balancer.select_instance.call_args_list[0][0][0]
        call1_ids = {inst.instance_id for inst in call1_instances}
        assert "instance-1" not in call1_ids
        assert {"instance-2", "instance-3"} == call1_ids

        # Check second call excluded instance-2
        call2_instances = mock_load_balancer.select_instance.call_args_list[1][0][0]
        call2_ids = {inst.instance_id for inst in call2_instances}
        assert "instance-2" not in call2_ids
        assert {"instance-1", "instance-3"} == call2_ids

        # Check third call excluded instance-3
        call3_instances = mock_load_balancer.select_instance.call_args_list[2][0][0]
        call3_ids = {inst.instance_id for inst in call3_instances}
        assert "instance-3" not in call3_ids
        assert {"instance-1", "instance-2"} == call3_ids
