"""Integration tests for NATS messaging infrastructure."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import msgpack
import pytest
from ipc_client_sdk.models import (
    ServiceRegistrationRequest,
    ServiceRegistrationResponse,
)
from ipc_router.application.services import ServiceRegistry
from ipc_router.infrastructure.messaging import NATSClient
from ipc_router.infrastructure.messaging.handlers import RegistrationHandler


@pytest.mark.integration
class TestNATSIntegration:
    """Integration tests for NATS messaging."""

    @pytest.mark.asyncio
    async def test_nats_connection(self, nats_client: NATSClient) -> None:
        """Test basic NATS connection."""
        assert nats_client.is_connected is True

        # Test publish/subscribe
        received = []

        async def handler(msg: Any) -> None:
            received.append(msgpack.unpackb(msg.data))

        await nats_client.subscribe("test.subject", handler)
        await nats_client.publish("test.subject", {"test": "data"})

        # Wait for message
        await asyncio.sleep(0.1)

        assert len(received) == 1
        assert received[0] == {"test": "data"}

    @pytest.mark.asyncio
    async def test_request_response_pattern(self, nats_client: NATSClient) -> None:
        """Test NATS request/response pattern."""

        # Set up responder
        async def responder(msg: Any) -> None:
            data = msgpack.unpackb(msg.data)
            response = {"echo": data["message"], "timestamp": datetime.now(UTC).isoformat()}
            await nats_client.publish(msg.reply, response)

        await nats_client.subscribe("test.echo", responder)

        # Send request
        response = await nats_client.request("test.echo", {"message": "Hello NATS"}, timeout=2.0)

        assert response is not None
        assert response["echo"] == "Hello NATS"
        assert "timestamp" in response

    @pytest.mark.asyncio
    async def test_service_registration_handler(
        self,
        nats_client: NATSClient,
        service_subject: str,
    ) -> None:
        """Test service registration through NATS."""
        # Create and start registration handler
        registry = ServiceRegistry()
        handler = RegistrationHandler(nats_client, registry)
        await handler.start()

        # Create registration request
        request = ServiceRegistrationRequest(
            service_name="test-service",
            instance_id="test_instance_01",
            metadata={"version": "1.0.0", "region": "us-east-1"},
        )

        # Send registration request
        response_data = await nats_client.request(
            service_subject, request.model_dump(), timeout=5.0
        )

        assert response_data is not None
        assert "envelope" in response_data

        envelope = response_data["envelope"]
        assert envelope["success"] is True

        # Parse response
        response = ServiceRegistrationResponse(**response_data["data"])
        assert response.success is True
        assert response.service_name == "test-service"
        assert response.instance_id == "test_instance_01"
        assert response.message == "Service instance registered successfully"

        # Verify service was registered
        service_info = await registry.get_service("test-service")
        assert service_info.name == "test-service"
        assert len(service_info.instances) == 1
        assert service_info.instances[0].instance_id == "test_instance_01"

        await handler.stop()

    @pytest.mark.asyncio
    async def test_duplicate_registration_error(
        self,
        nats_client: NATSClient,
        service_subject: str,
    ) -> None:
        """Test duplicate registration error handling."""
        # Create and start registration handler
        registry = ServiceRegistry()
        handler = RegistrationHandler(nats_client, registry)
        await handler.start()

        # Create registration request
        request = ServiceRegistrationRequest(
            service_name="duplicate-service", instance_id="duplicate_instance", metadata={}
        )

        # First registration should succeed
        response1 = await nats_client.request(service_subject, request.model_dump(), timeout=5.0)

        assert response1["envelope"]["success"] is True

        # Second registration should fail
        response2 = await nats_client.request(service_subject, request.model_dump(), timeout=5.0)

        assert response2["envelope"]["success"] is False
        assert response2["envelope"]["error_code"] == "CONFLICT"
        assert "already registered" in response2["envelope"]["message"]

        await handler.stop()

    @pytest.mark.asyncio
    async def test_multiple_handlers_load_balancing(
        self,
        nats_client: NATSClient,
        service_subject: str,
    ) -> None:
        """Test load balancing across multiple handlers."""
        # Create multiple handlers with same queue group
        registry1 = ServiceRegistry()
        registry2 = ServiceRegistry()

        handler1 = RegistrationHandler(nats_client, registry1)
        handler2 = RegistrationHandler(nats_client, registry2)

        await handler1.start()
        await handler2.start()

        # Send multiple registration requests
        services = []
        for i in range(10):
            request = ServiceRegistrationRequest(
                service_name=f"service-{i}", instance_id=f"instance-{i}", metadata={}
            )

            response = await nats_client.request(service_subject, request.model_dump(), timeout=5.0)

            assert response["envelope"]["success"] is True
            services.append(f"service-{i}")

        # Check distribution across registries
        registry1_count = len(registry1._services)
        registry2_count = len(registry2._services)

        # Both should have processed some requests
        assert registry1_count > 0
        assert registry2_count > 0
        assert registry1_count + registry2_count == 10

        await handler1.stop()
        await handler2.stop()

    @pytest.mark.asyncio
    async def test_invalid_request_handling(
        self,
        nats_client: NATSClient,
        service_subject: str,
    ) -> None:
        """Test handling of invalid requests."""
        # Create and start registration handler
        registry = ServiceRegistry()
        handler = RegistrationHandler(nats_client, registry)
        await handler.start()

        # Send invalid request (missing required fields)
        invalid_request = {"service_name": "test"}  # Missing instance_id

        response = await nats_client.request(service_subject, invalid_request, timeout=5.0)

        assert response["envelope"]["success"] is False
        assert response["envelope"]["error_code"] == "VALIDATION_ERROR"
        assert "Field required" in response["envelope"]["message"]

        await handler.stop()

    @pytest.mark.asyncio
    async def test_timeout_handling(
        self,
        nats_client: NATSClient,
    ) -> None:
        """Test request timeout handling."""
        # Request to non-existent subject should timeout
        with pytest.raises(asyncio.TimeoutError):
            await nats_client.request("non.existent.subject", {"test": "data"}, timeout=1.0)

    @pytest.mark.asyncio
    async def test_connection_resilience(
        self,
        nats_client: NATSClient,
    ) -> None:
        """Test NATS client reconnection handling."""
        # This test would require stopping/starting NATS server
        # For now, just verify client connection state
        assert nats_client.is_connected is True

        # Test that client can still publish after being connected for a while
        await asyncio.sleep(1)

        response = await nats_client.request("test.ping", {"ping": "test"}, timeout=1.0)

        # No response expected, but should not raise connection error
        assert response is None  # Timeout is expected

    @pytest.mark.asyncio
    async def test_concurrent_requests(
        self,
        nats_client: NATSClient,
        service_subject: str,
    ) -> None:
        """Test handling of concurrent registration requests."""
        # Create and start registration handler
        registry = ServiceRegistry()
        handler = RegistrationHandler(nats_client, registry)
        await handler.start()

        # Create multiple concurrent requests
        async def register_service(index: int) -> Any:
            request = ServiceRegistrationRequest(
                service_name=f"concurrent-service-{index}",
                instance_id=f"concurrent-instance-{index}",
                metadata={"index": index},
            )

            response = await nats_client.request(service_subject, request.model_dump(), timeout=5.0)

            return response["envelope"]["success"]

        # Send 20 concurrent requests
        tasks = [register_service(i) for i in range(20)]
        results = await asyncio.gather(*tasks)

        # All should succeed
        assert all(results)
        assert len(registry._services) == 20

        await handler.stop()

    @pytest.mark.asyncio
    async def test_message_size_handling(
        self,
        nats_client: NATSClient,
        service_subject: str,
    ) -> None:
        """Test handling of large messages."""
        # Create and start registration handler
        registry = ServiceRegistry()
        handler = RegistrationHandler(nats_client, registry)
        await handler.start()

        # Create request with large metadata
        large_metadata = {
            f"key_{i}": f"value_{i}" * 100
            for i in range(100)  # 600 bytes per entry  # 60KB total
        }

        request = ServiceRegistrationRequest(
            service_name="large-metadata-service",
            instance_id="large_instance_01",
            metadata=large_metadata,
        )

        response = await nats_client.request(service_subject, request.model_dump(), timeout=5.0)

        assert response["envelope"]["success"] is True

        # Verify metadata was stored correctly
        service_info = await registry.get_service("large-metadata-service")
        assert len(service_info.instances[0].metadata) == 100

        await handler.stop()
