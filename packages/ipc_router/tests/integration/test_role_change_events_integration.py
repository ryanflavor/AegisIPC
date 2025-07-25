"""Integration tests for role change events with real NATS."""

from __future__ import annotations

import asyncio

import pytest
from ipc_client_sdk.models import ServiceRegistrationRequest
from ipc_router.application.services import ServiceRegistry
from ipc_router.domain.enums import ServiceRole
from ipc_router.domain.events import RoleChangedEvent, ServiceEvent, ServiceEventType
from ipc_router.infrastructure.messaging import NATSClient
from ipc_router.infrastructure.messaging.handlers import RegistrationHandler


@pytest.mark.integration
class TestRoleChangeEventsIntegration:
    """Integration tests for role change events."""

    @pytest.mark.asyncio
    async def test_role_change_event_on_registration(self, nats_client: NATSClient) -> None:
        """Test that RoleChangedEvent is emitted on service registration."""
        # Setup registry and handlers
        registry = ServiceRegistry()
        reg_handler = RegistrationHandler(nats_client, registry)
        await reg_handler.start()

        # Track emitted events
        emitted_events: list[RoleChangedEvent] = []

        async def event_handler(event: ServiceEvent) -> None:
            if isinstance(event, RoleChangedEvent):
                emitted_events.append(event)

        registry.subscribe_to_events(ServiceEventType.INSTANCE_ROLE_CHANGED, event_handler)

        try:
            # Register service as active
            request = ServiceRegistrationRequest(
                service_name="test-service",
                instance_id="test-instance-1",
                role="active",
                metadata={"resource_id": "res_123"},
            )

            response = await nats_client.request(
                "ipc.service.register",
                request.model_dump(),
                timeout=5.0,
            )

            assert response["envelope"]["success"] is True
            assert response["data"]["role"] == "ACTIVE"

            # Wait for event to be emitted
            await asyncio.sleep(0.1)

            # Verify event was emitted
            assert len(emitted_events) == 1
            event = emitted_events[0]
            assert event.service_name == "test-service"
            assert event.instance_id == "test-instance-1"
            assert event.old_role is None  # New registration
            assert event.new_role == ServiceRole.ACTIVE
            assert event.resource_id == "res_123"
            assert event.metadata["event_type"] == "registration"

        finally:
            await reg_handler.stop()

    @pytest.mark.asyncio
    async def test_role_change_event_on_unregistration(self, nats_client: NATSClient) -> None:
        """Test that RoleChangedEvent is emitted on service unregistration."""
        # Setup registry and handlers
        registry = ServiceRegistry()
        reg_handler = RegistrationHandler(nats_client, registry)
        await reg_handler.start()

        # Track emitted events
        emitted_events: list[RoleChangedEvent] = []

        async def event_handler(event: ServiceEvent) -> None:
            if isinstance(event, RoleChangedEvent):
                emitted_events.append(event)

        registry.subscribe_to_events(ServiceEventType.INSTANCE_ROLE_CHANGED, event_handler)

        try:
            # First register a service
            request = ServiceRegistrationRequest(
                service_name="test-service",
                instance_id="test-instance-1",
                role="active",
                metadata={"resource_id": "res_456"},
            )

            await nats_client.request(
                "ipc.service.register",
                request.model_dump(),
                timeout=5.0,
            )

            # Clear events from registration
            emitted_events.clear()

            # Now unregister
            await nats_client.request(
                "ipc.service.unregister",
                {
                    "service_name": "test-service",
                    "instance_id": "test-instance-1",
                },
                timeout=5.0,
            )

            # Wait for event to be emitted
            await asyncio.sleep(0.1)

            # Verify unregistration event was emitted
            assert len(emitted_events) == 1
            event = emitted_events[0]
            assert event.service_name == "test-service"
            assert event.instance_id == "test-instance-1"
            assert event.old_role == ServiceRole.ACTIVE
            assert event.new_role is None  # Unregistration
            assert event.resource_id == "res_456"
            assert event.metadata["event_type"] == "unregistration"

        finally:
            await reg_handler.stop()

    @pytest.mark.asyncio
    async def test_multiple_role_change_events(self, nats_client: NATSClient) -> None:
        """Test multiple role change events with different roles."""
        # Setup registry and handlers
        registry = ServiceRegistry()
        reg_handler = RegistrationHandler(nats_client, registry)
        await reg_handler.start()

        # Track emitted events
        emitted_events: list[RoleChangedEvent] = []

        async def event_handler(event: ServiceEvent) -> None:
            if isinstance(event, RoleChangedEvent):
                emitted_events.append(event)

        registry.subscribe_to_events(ServiceEventType.INSTANCE_ROLE_CHANGED, event_handler)

        try:
            # Register first instance as standby
            request1 = ServiceRegistrationRequest(
                service_name="multi-service",
                instance_id="instance-1",
                role="standby",
                metadata={"resource_id": "shared_resource"},
            )

            await nats_client.request(
                "ipc.service.register",
                request1.model_dump(),
                timeout=5.0,
            )

            # Register second instance as active for different resource
            request2 = ServiceRegistrationRequest(
                service_name="multi-service",
                instance_id="instance-2",
                role="active",
                metadata={"resource_id": "unique_resource"},
            )

            await nats_client.request(
                "ipc.service.register",
                request2.model_dump(),
                timeout=5.0,
            )

            # Register third instance with no role (defaults to standby)
            request3 = ServiceRegistrationRequest(
                service_name="multi-service",
                instance_id="instance-3",
                metadata={"version": "1.0.0"},
            )

            await nats_client.request(
                "ipc.service.register",
                request3.model_dump(),
                timeout=5.0,
            )

            # Wait for events to be emitted
            await asyncio.sleep(0.1)

            # Verify all events
            assert len(emitted_events) == 3

            # First event - standby registration
            event1 = emitted_events[0]
            assert event1.instance_id == "instance-1"
            assert event1.new_role == ServiceRole.STANDBY
            assert event1.resource_id == "shared_resource"

            # Second event - active registration
            event2 = emitted_events[1]
            assert event2.instance_id == "instance-2"
            assert event2.new_role == ServiceRole.ACTIVE
            assert event2.resource_id == "unique_resource"

            # Third event - default role (standby)
            event3 = emitted_events[2]
            assert event3.instance_id == "instance-3"
            assert event3.new_role == ServiceRole.STANDBY
            assert event3.resource_id is None  # No resource_id in metadata

        finally:
            await reg_handler.stop()

    @pytest.mark.asyncio
    async def test_role_conflict_no_event_emitted(self, nats_client: NATSClient) -> None:
        """Test that no event is emitted when role conflict occurs."""
        # Setup registry and handlers
        registry = ServiceRegistry()
        reg_handler = RegistrationHandler(nats_client, registry)
        await reg_handler.start()

        # Track emitted events
        emitted_events: list[RoleChangedEvent] = []

        async def event_handler(event: ServiceEvent) -> None:
            if isinstance(event, RoleChangedEvent):
                emitted_events.append(event)

        registry.subscribe_to_events(ServiceEventType.INSTANCE_ROLE_CHANGED, event_handler)

        try:
            # Register first instance as active
            request1 = ServiceRegistrationRequest(
                service_name="conflict-service",
                instance_id="instance-1",
                role="active",
                metadata={"resource_id": "contested_resource"},
            )

            response1 = await nats_client.request(
                "ipc.service.register",
                request1.model_dump(),
                timeout=5.0,
            )
            assert response1["envelope"]["success"] is True

            # Try to register second instance as active for same resource
            request2 = ServiceRegistrationRequest(
                service_name="conflict-service",
                instance_id="instance-2",
                role="active",
                metadata={"resource_id": "contested_resource"},
            )

            response2 = await nats_client.request(
                "ipc.service.register",
                request2.model_dump(),
                timeout=5.0,
            )

            # Should fail due to conflict
            assert response2["envelope"]["success"] is False
            assert "already has an active instance" in response2["envelope"]["message"]

            # Wait to ensure no event is emitted
            await asyncio.sleep(0.1)

            # Only one event should have been emitted (for the first successful registration)
            assert len(emitted_events) == 1
            assert emitted_events[0].instance_id == "instance-1"

        finally:
            await reg_handler.stop()

    @pytest.mark.asyncio
    async def test_event_handler_subscription(self, nats_client: NATSClient) -> None:
        """Test event handler subscription mechanism."""
        # Setup registry and handlers
        registry = ServiceRegistry()
        reg_handler = RegistrationHandler(nats_client, registry)
        await reg_handler.start()

        # Track events from different handlers
        all_events: list[tuple[str, ServiceEvent]] = []
        role_events: list[tuple[str, RoleChangedEvent]] = []

        async def all_event_handler(event: ServiceEvent) -> None:
            all_events.append(("all", event))

        async def role_event_handler(event: ServiceEvent) -> None:
            if isinstance(event, RoleChangedEvent):
                role_events.append(("role", event))

        # Subscribe with different filters
        registry.subscribe_to_events(None, all_event_handler)  # All events
        registry.subscribe_to_events(ServiceEventType.INSTANCE_ROLE_CHANGED, role_event_handler)

        try:
            # Register a service
            request = ServiceRegistrationRequest(
                service_name="sub-test-service",
                instance_id="sub-test-1",
                role="active",
                metadata={"test": True},
            )

            await nats_client.request(
                "ipc.service.register",
                request.model_dump(),
                timeout=5.0,
            )

            # Wait for events
            await asyncio.sleep(0.1)

            # All-event handler should receive the role change event
            assert len(all_events) >= 1
            role_change_events = [e for _, e in all_events if isinstance(e, RoleChangedEvent)]
            assert len(role_change_events) == 1

            # Role-specific handler should also receive it
            assert len(role_events) == 1
            assert role_events[0][1].service_name == "sub-test-service"

        finally:
            await reg_handler.stop()
