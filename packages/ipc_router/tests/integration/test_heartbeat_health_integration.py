"""Integration tests for heartbeat and health check functionality."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from ipc_client_sdk import ServiceClient, ServiceClientConfig
from ipc_router.application.models import HeartbeatRequest
from ipc_router.application.services import ServiceRegistry
from ipc_router.application.services.health_checker import HealthChecker
from ipc_router.domain.enums import ServiceStatus
from ipc_router.infrastructure.messaging import NATSClient
from ipc_router.infrastructure.messaging.handlers import HeartbeatHandler
from testcontainers.compose import DockerCompose


@pytest.mark.integration
class TestHeartbeatHealthIntegration:
    """Integration tests for heartbeat and health monitoring."""

    @pytest.fixture
    async def docker_compose(self):
        """Start docker compose with NATS."""
        with DockerCompose("../../docker", compose_file_name="docker-compose.test.yml") as compose:
            compose.wait_for("nats://localhost:4222")
            yield compose

    @pytest.fixture
    async def nats_client(self, docker_compose):
        """Create NATS client."""
        client = NATSClient(servers=["nats://localhost:4222"])
        await client.connect()
        yield client
        await client.disconnect()

    @pytest.fixture
    async def service_registry(self):
        """Create service registry."""
        return ServiceRegistry()

    @pytest.fixture
    async def heartbeat_handler(self, nats_client, service_registry):
        """Create and start heartbeat handler."""
        handler = HeartbeatHandler(nats_client, service_registry)
        await handler.start()
        yield handler
        await handler.stop()

    @pytest.fixture
    async def health_checker(self, service_registry):
        """Create health checker with short intervals for testing."""
        checker = HealthChecker(
            service_registry,
            check_interval=0.5,  # Check every 500ms
            heartbeat_timeout=2.0,  # 2 second timeout
        )
        await checker.start()
        yield checker
        await checker.stop()

    @pytest.mark.asyncio
    async def test_automatic_heartbeat_after_registration(
        self, docker_compose, heartbeat_handler, service_registry
    ):
        """Test that services automatically send heartbeats after registration."""
        # Create client with automatic heartbeat enabled
        config = ServiceClientConfig(
            nats_servers="nats://localhost:4222",
            heartbeat_enabled=True,
            heartbeat_interval=0.5,  # 500ms interval
        )

        async with ServiceClient(config=config) as client:
            # Register service
            response = await client.register("test-service")
            assert response.success is True

            # Wait for a few heartbeats
            await asyncio.sleep(2.0)

            # Check that heartbeats were received
            service = await service_registry.get_service("test-service")
            instances = list(service.instances.values())
            assert len(instances) == 1

            instance = instances[0]
            assert instance.last_heartbeat is not None

            # Heartbeat should be recent (within last second)
            time_since_heartbeat = (
                datetime.now(UTC) - instance.last_heartbeat.replace(tzinfo=UTC)
            ).total_seconds()
            assert time_since_heartbeat < 1.0

    @pytest.mark.asyncio
    async def test_health_status_updates_on_timeout(
        self, docker_compose, heartbeat_handler, service_registry, health_checker
    ):
        """Test that instances are marked unhealthy when heartbeats stop."""
        # Create client and register
        config = ServiceClientConfig(
            nats_servers="nats://localhost:4222",
            heartbeat_enabled=True,
            heartbeat_interval=0.5,
        )

        async with ServiceClient(config=config) as client:
            # Register service
            await client.register("timeout-service")

            # Verify initial health
            await asyncio.sleep(1.0)
            healthy_instances = await service_registry.get_healthy_instances("timeout-service")
            assert len(healthy_instances) == 1
            assert healthy_instances[0].status == ServiceStatus.ONLINE

            # Stop heartbeats by cancelling the task
            if "timeout-service" in client._heartbeat_tasks:
                client._heartbeat_tasks["timeout-service"].cancel()

            # Wait for health checker to mark as unhealthy (>2s timeout)
            await asyncio.sleep(3.0)

            # Check health status
            service = await service_registry.get_service("timeout-service")
            instances = list(service.instances.values())
            assert len(instances) == 1
            assert instances[0].status == ServiceStatus.UNHEALTHY

            # Verify unhealthy instances are filtered
            healthy_instances = await service_registry.get_healthy_instances("timeout-service")
            assert len(healthy_instances) == 0

    @pytest.mark.asyncio
    async def test_instance_failover_on_unhealthy(
        self, docker_compose, heartbeat_handler, service_registry, health_checker
    ):
        """Test that routing excludes unhealthy instances."""
        # Register multiple instances
        config = ServiceClientConfig(
            nats_servers="nats://localhost:4222",
            heartbeat_enabled=True,
            heartbeat_interval=0.5,
        )

        # Create 3 instances
        clients = []
        for i in range(3):
            client = ServiceClient(
                config=config,
                instance_id=f"instance-{i}",
            )
            await client.connect()
            await client.register("multi-instance-service")
            clients.append(client)

        # Wait for all to be healthy
        await asyncio.sleep(1.0)
        healthy_instances = await service_registry.get_healthy_instances("multi-instance-service")
        assert len(healthy_instances) == 3

        # Stop heartbeat for instance-1
        if "multi-instance-service" in clients[1]._heartbeat_tasks:
            clients[1]._heartbeat_tasks["multi-instance-service"].cancel()

        # Wait for health check to mark it unhealthy
        await asyncio.sleep(3.0)

        # Verify only 2 instances are healthy
        healthy_instances = await service_registry.get_healthy_instances("multi-instance-service")
        assert len(healthy_instances) == 2

        # Verify unhealthy instance is excluded
        healthy_ids = {inst.instance_id for inst in healthy_instances}
        assert "instance-1" not in healthy_ids
        assert "instance-0" in healthy_ids
        assert "instance-2" in healthy_ids

        # Cleanup
        for client in clients:
            await client.disconnect()

    @pytest.mark.asyncio
    async def test_heartbeat_message_validation(
        self, docker_compose, nats_client, service_registry
    ):
        """Test that heartbeat handler validates messages correctly."""
        handler = HeartbeatHandler(nats_client, service_registry)
        await handler.start()

        try:
            # Send invalid heartbeat (missing required fields)
            invalid_heartbeat = {"timestamp": datetime.now(UTC).isoformat()}

            response = await nats_client.request(
                "ipc.service.heartbeat",
                invalid_heartbeat,
                timeout=2.0,
            )

            assert response is not None
            assert response["envelope"]["success"] is False
            assert response["envelope"]["error_code"] == "VALIDATION_ERROR"

            # Send valid heartbeat (should use HeartbeatRequest model)
            valid_heartbeat = HeartbeatRequest(
                service_name="valid-service",
                instance_id="valid-instance",
                status="healthy",
                metadata={"version": "1.0"},
            )

            # First register the service
            await service_registry.register_instance(
                "valid-service",
                "valid-instance",
                metadata={"version": "1.0"},
            )

            # Send heartbeat
            response = await nats_client.request(
                "ipc.service.heartbeat",
                valid_heartbeat.model_dump(),
                timeout=2.0,
            )

            assert response is not None
            assert response["envelope"]["success"] is True

        finally:
            await handler.stop()

    @pytest.mark.asyncio
    async def test_concurrent_heartbeats_performance(
        self, docker_compose, heartbeat_handler, service_registry
    ):
        """Test system performance with many concurrent heartbeats."""
        # Create multiple clients
        num_services = 10
        num_instances_per_service = 5

        clients = []
        config = ServiceClientConfig(
            nats_servers="nats://localhost:4222",
            heartbeat_enabled=True,
            heartbeat_interval=1.0,  # 1 second interval
        )

        # Register all instances
        for service_idx in range(num_services):
            for instance_idx in range(num_instances_per_service):
                client = ServiceClient(
                    config=config,
                    instance_id=f"service{service_idx}-instance{instance_idx}",
                )
                await client.connect()
                await client.register(f"service-{service_idx}")
                clients.append(client)

        # Let heartbeats run for a few seconds
        await asyncio.sleep(3.0)

        # Verify all instances are healthy
        for service_idx in range(num_services):
            healthy = await service_registry.get_healthy_instances(f"service-{service_idx}")
            assert len(healthy) == num_instances_per_service

        # Measure heartbeat processing time
        start_time = datetime.now(UTC)

        # Send burst of heartbeats
        tasks = []
        for client in clients:
            for service_name in client._registered_services:
                tasks.append(client.heartbeat(service_name))

        await asyncio.gather(*tasks)

        # All heartbeats should complete quickly
        elapsed = (datetime.now(UTC) - start_time).total_seconds()
        assert elapsed < 1.0  # Should handle 50 heartbeats in under 1 second

        # Cleanup
        for client in clients:
            await client.disconnect()

    @pytest.mark.asyncio
    async def test_heartbeat_recovery_after_network_issue(
        self, docker_compose, heartbeat_handler, service_registry, health_checker
    ):
        """Test that instances recover when heartbeats resume."""
        config = ServiceClientConfig(
            nats_servers="nats://localhost:4222",
            heartbeat_enabled=True,
            heartbeat_interval=0.5,
        )

        async with ServiceClient(config=config) as client:
            # Register and verify healthy
            await client.register("recovery-service")
            await asyncio.sleep(1.0)

            healthy = await service_registry.get_healthy_instances("recovery-service")
            assert len(healthy) == 1

            # Simulate network issue - stop heartbeats
            if "recovery-service" in client._heartbeat_tasks:
                client._heartbeat_tasks["recovery-service"].cancel()

            # Wait for unhealthy status
            await asyncio.sleep(3.0)
            healthy = await service_registry.get_healthy_instances("recovery-service")
            assert len(healthy) == 0

            # Resume heartbeats manually
            await client.heartbeat("recovery-service")

            # Status should update to healthy immediately
            service = await service_registry.get_service("recovery-service")
            instances = list(service.instances.values())
            assert instances[0].status == ServiceStatus.ONLINE

            # Verify it's included in healthy instances again
            healthy = await service_registry.get_healthy_instances("recovery-service")
            assert len(healthy) == 1
