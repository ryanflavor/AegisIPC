"""Integration tests for service discovery and health checks with real NATS."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from ipc_client_sdk.models import ServiceRegistrationRequest
from ipc_router.application.services import HealthChecker, ServiceRegistry
from ipc_router.domain.enums import ServiceStatus
from ipc_router.infrastructure.messaging import NATSClient
from ipc_router.infrastructure.messaging.handlers import HeartbeatHandler, RegistrationHandler


@pytest.mark.integration
class TestServiceDiscoveryIntegration:
    """Integration tests for service discovery with NATS."""

    @pytest.mark.asyncio
    async def test_service_registration_and_discovery(self, nats_client: NATSClient) -> None:
        """Test service registration and discovery through NATS."""
        # Setup registry and handlers
        registry = ServiceRegistry()
        reg_handler = RegistrationHandler(nats_client, registry)
        await reg_handler.start()

        try:
            # Register multiple services
            services = [
                ("api-gateway", "gateway-1", {"version": "1.0", "region": "us-east-1"}),
                ("api-gateway", "gateway-2", {"version": "1.0", "region": "us-west-1"}),
                ("user-service", "user-1", {"version": "2.0", "features": ["auth", "profile"]}),
                ("user-service", "user-2", {"version": "2.0", "features": ["auth", "profile"]}),
                ("payment-service", "payment-1", {"version": "1.5", "provider": "stripe"}),
            ]

            # Register all services
            for service_name, instance_id, metadata in services:
                request = ServiceRegistrationRequest(
                    service_name=service_name,
                    instance_id=instance_id,
                    metadata=metadata,
                )

                response = await nats_client.request(
                    "ipc.service.register",
                    request.model_dump(),
                    timeout=5.0,
                )

                assert response["envelope"]["success"] is True

            # Verify service discovery
            api_gateway = await registry.get_service("api-gateway")
            assert len(api_gateway.instances) == 2
            assert all(i.status == ServiceStatus.ONLINE.value for i in api_gateway.instances)

            user_service = await registry.get_service("user-service")
            assert len(user_service.instances) == 2

            payment_service = await registry.get_service("payment-service")
            assert len(payment_service.instances) == 1

            # Test get_healthy_instances
            healthy_gateways = await registry.get_healthy_instances("api-gateway")
            assert len(healthy_gateways) == 2

            # Test instance metadata
            gateway1 = next(i for i in api_gateway.instances if i.instance_id == "gateway-1")
            assert gateway1.metadata["region"] == "us-east-1"

        finally:
            await reg_handler.stop()

    @pytest.mark.asyncio
    async def test_heartbeat_handling_through_nats(self, nats_client: NATSClient) -> None:
        """Test heartbeat handling through NATS."""
        # Setup registry and handlers
        registry = ServiceRegistry()
        reg_handler = RegistrationHandler(nats_client, registry)
        heartbeat_handler = HeartbeatHandler(nats_client, registry)

        await reg_handler.start()
        await heartbeat_handler.start()

        try:
            # Register a service
            service_name = "heartbeat-test-service"
            instance_id = "heartbeat-instance-1"

            request = ServiceRegistrationRequest(
                service_name=service_name,
                instance_id=instance_id,
                metadata={"test": True},
            )

            await nats_client.request(
                "ipc.service.register",
                request.model_dump(),
                timeout=5.0,
            )

            # Get initial heartbeat time
            service_info = await registry.get_service(service_name)
            instance = service_info.instances[0]
            initial_heartbeat = instance.last_heartbeat

            # Wait a bit
            await asyncio.sleep(0.5)

            # Send heartbeat via NATS
            heartbeat_data = {
                "service_name": service_name,
                "instance_id": instance_id,
                "timestamp": datetime.now(UTC).isoformat(),
            }

            response = await nats_client.request(
                "ipc.service.heartbeat",
                heartbeat_data,
                timeout=5.0,
            )

            assert response["envelope"]["success"] is True

            # Verify heartbeat was updated
            service_info = await registry.get_service(service_name)
            instance = service_info.instances[0]
            assert instance.last_heartbeat > initial_heartbeat

            # Test heartbeat for non-existent service
            bad_heartbeat = {
                "service_name": "non-existent",
                "instance_id": "fake-instance",
            }

            response = await nats_client.request(
                "ipc.service.heartbeat",
                bad_heartbeat,
                timeout=5.0,
            )

            assert response["envelope"]["success"] is False
            assert response["envelope"]["error_code"] == "NOT_FOUND"

        finally:
            await heartbeat_handler.stop()
            await reg_handler.stop()

    @pytest.mark.asyncio
    async def test_health_checker_marks_stale_instances(self, nats_client: NATSClient) -> None:
        """Test health checker marks stale instances as unhealthy."""
        # Setup services
        registry = ServiceRegistry()
        reg_handler = RegistrationHandler(nats_client, registry)
        health_checker = HealthChecker(
            registry,
            check_interval=0.5,  # 500ms for faster testing
            heartbeat_timeout=1.0,  # 1 second timeout
        )

        await reg_handler.start()
        await health_checker.start()

        try:
            # Register multiple instances
            service_name = "health-check-test"
            instances = ["inst-1", "inst-2", "inst-3"]

            for instance_id in instances:
                request = ServiceRegistrationRequest(
                    service_name=service_name,
                    instance_id=instance_id,
                )

                await nats_client.request(
                    "ipc.service.register",
                    request.model_dump(),
                    timeout=5.0,
                )

            # Initially all should be online
            service_info = await registry.get_service(service_name)
            assert all(i.status == ServiceStatus.ONLINE.value for i in service_info.instances)

            # Send heartbeat only for inst-1
            await registry.update_heartbeat(service_name, "inst-1")

            # Wait for health check to mark others as unhealthy
            await asyncio.sleep(2.0)

            # Check status
            service_info = await registry.get_service(service_name)
            inst1 = next(i for i in service_info.instances if i.instance_id == "inst-1")
            inst2 = next(i for i in service_info.instances if i.instance_id == "inst-2")
            inst3 = next(i for i in service_info.instances if i.instance_id == "inst-3")

            assert inst1.status == ServiceStatus.ONLINE.value
            assert inst2.status == ServiceStatus.UNHEALTHY.value
            assert inst3.status == ServiceStatus.UNHEALTHY.value

            # Verify get_healthy_instances only returns inst-1
            healthy = await registry.get_healthy_instances(service_name)
            assert len(healthy) == 1
            assert healthy[0].instance_id == "inst-1"

        finally:
            await health_checker.stop()
            await reg_handler.stop()

    @pytest.mark.asyncio
    async def test_service_status_transitions(self, nats_client: NATSClient) -> None:
        """Test service status transitions and event notifications."""
        # Setup services
        registry = ServiceRegistry()
        reg_handler = RegistrationHandler(nats_client, registry)

        events_received = []

        # Subscribe to status change events
        async def event_handler(event):
            events_received.append(
                {
                    "service": event.service_name,
                    "instance": event.instance_id,
                    "old_status": event.old_status,
                    "new_status": event.new_status,
                    "timestamp": event.timestamp,
                }
            )

        registry.subscribe_to_events(None, event_handler)

        await reg_handler.start()

        try:
            # Register service
            service_name = "status-test-service"
            instance_id = "status-instance-1"

            request = ServiceRegistrationRequest(
                service_name=service_name,
                instance_id=instance_id,
            )

            await nats_client.request(
                "ipc.service.register",
                request.model_dump(),
                timeout=5.0,
            )

            # Transition: ONLINE -> UNHEALTHY
            await registry.update_instance_status(
                service_name, instance_id, ServiceStatus.UNHEALTHY
            )

            # Transition: UNHEALTHY -> OFFLINE
            await registry.update_instance_status(service_name, instance_id, ServiceStatus.OFFLINE)

            # Allow async events to process
            await asyncio.sleep(0.1)

            # Should have received 2 status change events
            assert len(events_received) == 2

            # Verify first transition
            event1 = events_received[0]
            assert event1["old_status"] == ServiceStatus.ONLINE
            assert event1["new_status"] == ServiceStatus.UNHEALTHY

            # Verify second transition
            event2 = events_received[1]
            assert event2["old_status"] == ServiceStatus.UNHEALTHY
            assert event2["new_status"] == ServiceStatus.OFFLINE

        finally:
            await reg_handler.stop()

    @pytest.mark.asyncio
    async def test_concurrent_registrations_and_heartbeats(self, nats_client: NATSClient) -> None:
        """Test handling of concurrent registrations and heartbeats."""
        # Setup services
        registry = ServiceRegistry()
        reg_handler = RegistrationHandler(nats_client, registry)
        heartbeat_handler = HeartbeatHandler(nats_client, registry)

        await reg_handler.start()
        await heartbeat_handler.start()

        try:
            # Register many services concurrently
            service_base = "concurrent-service"
            num_services = 10
            num_instances_per_service = 5

            async def register_instance(service_idx: int, instance_idx: int):
                request = ServiceRegistrationRequest(
                    service_name=f"{service_base}-{service_idx}",
                    instance_id=f"inst-{service_idx}-{instance_idx}",
                    metadata={"service": service_idx, "instance": instance_idx},
                )

                response = await nats_client.request(
                    "ipc.service.register",
                    request.model_dump(),
                    timeout=5.0,
                )

                return response["envelope"]["success"]

            # Register all instances concurrently
            tasks = []
            for s in range(num_services):
                for i in range(num_instances_per_service):
                    tasks.append(register_instance(s, i))

            results = await asyncio.gather(*tasks)
            assert all(results)

            # Verify all registered
            for s in range(num_services):
                service_info = await registry.get_service(f"{service_base}-{s}")
                assert len(service_info.instances) == num_instances_per_service

            # Send concurrent heartbeats
            async def send_heartbeat(service_idx: int, instance_idx: int):
                heartbeat_data = {
                    "service_name": f"{service_base}-{service_idx}",
                    "instance_id": f"inst-{service_idx}-{instance_idx}",
                }

                response = await nats_client.request(
                    "ipc.service.heartbeat",
                    heartbeat_data,
                    timeout=5.0,
                )

                return response["envelope"]["success"]

            # Send heartbeats for all instances
            heartbeat_tasks = []
            for s in range(num_services):
                for i in range(num_instances_per_service):
                    heartbeat_tasks.append(send_heartbeat(s, i))

            heartbeat_results = await asyncio.gather(*heartbeat_tasks)
            assert all(heartbeat_results)

        finally:
            await heartbeat_handler.stop()
            await reg_handler.stop()

    @pytest.mark.asyncio
    async def test_service_deregistration(self, nats_client: NATSClient) -> None:
        """Test service deregistration functionality."""
        # Setup services
        registry = ServiceRegistry()
        reg_handler = RegistrationHandler(nats_client, registry)

        await reg_handler.start()

        try:
            # Register services
            service_name = "deregister-test"
            instances = ["inst-1", "inst-2", "inst-3"]

            for instance_id in instances:
                request = ServiceRegistrationRequest(
                    service_name=service_name,
                    instance_id=instance_id,
                )

                await nats_client.request(
                    "ipc.service.register",
                    request.model_dump(),
                    timeout=5.0,
                )

            # Verify all registered
            service_info = await registry.get_service(service_name)
            assert len(service_info.instances) == 3

            # Mark one as offline (simulate deregistration)
            await registry.update_instance_status(service_name, "inst-2", ServiceStatus.OFFLINE)

            # Get only healthy/online instances
            healthy = await registry.get_healthy_instances(service_name)
            assert len(healthy) == 2
            assert all(i.instance_id != "inst-2" for i in healthy)

            # Mark all as offline
            for instance_id in ["inst-1", "inst-3"]:
                await registry.update_instance_status(
                    service_name, instance_id, ServiceStatus.OFFLINE
                )

            # No healthy instances should remain
            healthy = await registry.get_healthy_instances(service_name)
            assert len(healthy) == 0

        finally:
            await reg_handler.stop()

    @pytest.mark.asyncio
    async def test_health_recovery_mechanism(self, nats_client: NATSClient) -> None:
        """Test instance health recovery when heartbeats resume."""
        # Setup services
        registry = ServiceRegistry()
        reg_handler = RegistrationHandler(nats_client, registry)
        heartbeat_handler = HeartbeatHandler(nats_client, registry)
        health_checker = HealthChecker(
            registry,
            check_interval=0.5,
            heartbeat_timeout=1.0,
        )

        await reg_handler.start()
        await heartbeat_handler.start()
        await health_checker.start()

        try:
            # Register service
            service_name = "recovery-test"
            instance_id = "recovery-instance"

            request = ServiceRegistrationRequest(
                service_name=service_name,
                instance_id=instance_id,
            )

            await nats_client.request(
                "ipc.service.register",
                request.model_dump(),
                timeout=5.0,
            )

            # Wait for it to become unhealthy
            await asyncio.sleep(2.0)

            # Verify it's unhealthy
            service_info = await registry.get_service(service_name)
            assert service_info.instances[0].status == ServiceStatus.UNHEALTHY.value

            # Send heartbeat to recover
            heartbeat_data = {
                "service_name": service_name,
                "instance_id": instance_id,
            }

            await nats_client.request(
                "ipc.service.heartbeat",
                heartbeat_data,
                timeout=5.0,
            )

            # For now, manual recovery is needed
            # In a full implementation, health checker could auto-recover
            # This demonstrates the foundation for such functionality

        finally:
            await health_checker.stop()
            await heartbeat_handler.stop()
            await reg_handler.stop()
