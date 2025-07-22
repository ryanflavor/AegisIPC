"""Integration tests for the routing system."""

from __future__ import annotations

import asyncio

import pytest
from ipc_client_sdk.models import ServiceRegistrationRequest
from ipc_router.application.models.routing_models import RouteRequest
from ipc_router.application.services import HealthChecker, RoutingService, ServiceRegistry
from ipc_router.domain.enums import ServiceStatus
from ipc_router.domain.strategies.round_robin import RoundRobinLoadBalancer


@pytest.mark.asyncio
class TestRoutingIntegration:
    """Integration tests for routing functionality."""

    async def test_basic_routing_flow(self):
        """Test basic routing flow with multiple instances."""
        # Setup services
        registry = ServiceRegistry()
        load_balancer = RoundRobinLoadBalancer()
        routing_service = RoutingService(registry, load_balancer)

        # Register multiple instances of a service
        service_name = "test-service"
        instance_ids = ["inst-1", "inst-2", "inst-3"]

        for instance_id in instance_ids:
            request = ServiceRegistrationRequest(
                service_name=service_name,
                instance_id=instance_id,
                metadata={"version": "1.0"},
            )
            await registry.register_service(request)

        # Create routing requests
        routed_instances = []
        for i in range(6):
            route_request = RouteRequest(
                service_name=service_name,
                method="test_method",
                params={"data": f"request-{i}"},
                timeout=5.0,
                trace_id=f"trace-{i}",
            )

            response = await routing_service.route_request(route_request)

            assert response.success
            assert response.instance_id in instance_ids
            routed_instances.append(response.instance_id)

        # Verify round-robin distribution
        assert routed_instances == ["inst-1", "inst-2", "inst-3"] * 2

    async def test_routing_with_unhealthy_instances(self):
        """Test routing skips unhealthy instances."""
        registry = ServiceRegistry()
        routing_service = RoutingService(registry)

        service_name = "health-test-service"

        # Register instances
        for i in range(1, 4):
            request = ServiceRegistrationRequest(
                service_name=service_name,
                instance_id=f"inst-{i}",
            )
            await registry.register_service(request)

        # Mark one instance as unhealthy
        await registry.update_instance_status(service_name, "inst-2", ServiceStatus.UNHEALTHY)

        # Route requests
        routed_instances = []
        for _ in range(4):
            route_request = RouteRequest(
                service_name=service_name,
                method="test",
                trace_id="test-trace",
            )

            response = await routing_service.route_request(route_request)
            assert response.success
            routed_instances.append(response.instance_id)

        # Should only route to healthy instances
        assert "inst-2" not in routed_instances
        assert set(routed_instances) == {"inst-1", "inst-3"}

    async def test_routing_no_instances_available(self):
        """Test routing when no instances are available."""
        registry = ServiceRegistry()
        routing_service = RoutingService(registry)

        # Try to route to non-existent service
        route_request = RouteRequest(
            service_name="non-existent-service",
            method="test",
            trace_id="test-trace",
        )

        response = await routing_service.route_request(route_request)

        assert not response.success
        assert response.error["code"] == 404
        assert "not found" in response.error["message"]

    async def test_routing_all_instances_unhealthy(self):
        """Test routing when all instances are unhealthy."""
        registry = ServiceRegistry()
        routing_service = RoutingService(registry)

        service_name = "unhealthy-service"

        # Register instances
        for i in range(1, 3):
            request = ServiceRegistrationRequest(
                service_name=service_name,
                instance_id=f"inst-{i}",
            )
            await registry.register_service(request)

        # Mark all as unhealthy
        for i in range(1, 3):
            await registry.update_instance_status(
                service_name, f"inst-{i}", ServiceStatus.UNHEALTHY
            )

        # Try to route
        route_request = RouteRequest(
            service_name=service_name,
            method="test",
            trace_id="test-trace",
        )

        response = await routing_service.route_request(route_request)

        assert not response.success
        assert response.error["code"] == 503
        assert "No healthy instances" in response.error["message"]

    async def test_health_check_integration(self):
        """Test health checker marks stale instances as unhealthy."""
        registry = ServiceRegistry()
        routing_service = RoutingService(registry)
        health_checker = HealthChecker(
            registry,
            check_interval=0.1,  # 100ms for testing
            heartbeat_timeout=0.2,  # 200ms timeout
        )

        service_name = "health-check-service"

        # Register instances
        for i in range(1, 3):
            request = ServiceRegistrationRequest(
                service_name=service_name,
                instance_id=f"inst-{i}",
            )
            await registry.register_service(request)

        # Start health checker
        await health_checker.start()

        try:
            # Initially both should be routable
            route_request = RouteRequest(
                service_name=service_name,
                method="test",
                trace_id="test-1",
            )
            response = await routing_service.route_request(route_request)
            assert response.success

            # Wait for health check timeout
            await asyncio.sleep(0.5)

            # Now both should be marked unhealthy
            response = await routing_service.route_request(route_request)
            assert not response.success
            assert response.error["code"] == 503

            # Send heartbeat for one instance
            await registry.update_heartbeat(service_name, "inst-1")

            # After next check cycle, inst-1 should be healthy
            await asyncio.sleep(0.2)

            response = await routing_service.route_request(route_request)
            assert response.success
            assert response.instance_id == "inst-1"

        finally:
            await health_checker.stop()

    async def test_concurrent_routing_requests(self):
        """Test concurrent routing requests are handled correctly."""
        registry = ServiceRegistry()
        routing_service = RoutingService(registry)

        service_name = "concurrent-service"
        num_instances = 5

        # Register instances
        for i in range(1, num_instances + 1):
            request = ServiceRegistrationRequest(
                service_name=service_name,
                instance_id=f"inst-{i}",
            )
            await registry.register_service(request)

        # Create many concurrent requests
        async def make_request(request_id: int):
            route_request = RouteRequest(
                service_name=service_name,
                method="concurrent_test",
                params={"request_id": request_id},
                trace_id=f"trace-{request_id}",
            )
            response = await routing_service.route_request(route_request)
            return response.instance_id if response.success else None

        # Launch concurrent requests
        tasks = [make_request(i) for i in range(100)]
        results = await asyncio.gather(*tasks)

        # All should succeed
        assert all(r is not None for r in results)

        # Count distribution
        distribution = {}
        for instance_id in results:
            distribution[instance_id] = distribution.get(instance_id, 0) + 1

        # Should be evenly distributed (20 requests per instance)
        assert len(distribution) == num_instances
        for count in distribution.values():
            assert count == 20

    async def test_service_event_notifications(self):
        """Test service registry event notifications."""
        registry = ServiceRegistry()
        events_received = []

        # Subscribe to events
        async def event_handler(event):
            events_received.append(event)

        registry.subscribe_to_events(None, event_handler)

        service_name = "event-test-service"
        instance_id = "inst-1"

        # Register instance
        request = ServiceRegistrationRequest(
            service_name=service_name,
            instance_id=instance_id,
        )
        await registry.register_service(request)

        # Update status
        await registry.update_instance_status(service_name, instance_id, ServiceStatus.UNHEALTHY)

        # Allow async tasks to complete
        await asyncio.sleep(0.1)

        # Should have received status change event
        assert len(events_received) == 1
        event = events_received[0]
        assert event.service_name == service_name
        assert event.instance_id == instance_id
        assert event.old_status == ServiceStatus.ONLINE
        assert event.new_status == ServiceStatus.UNHEALTHY
