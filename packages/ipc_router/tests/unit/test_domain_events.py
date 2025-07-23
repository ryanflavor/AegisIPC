"""Unit tests for domain events."""

from __future__ import annotations

from datetime import UTC, datetime

from ipc_router.domain.enums import ServiceStatus
from ipc_router.domain.events import (
    InstanceStatusChangedEvent,
    ServiceEvent,
    ServiceEventType,
)


class TestServiceEventType:
    """Test ServiceEventType enum."""

    def test_event_type_values(self) -> None:
        """Test event type enum values."""
        assert ServiceEventType.INSTANCE_REGISTERED.value == "instance_registered"
        assert ServiceEventType.INSTANCE_UNREGISTERED.value == "instance_unregistered"
        assert ServiceEventType.INSTANCE_STATUS_CHANGED.value == "instance_status_changed"
        assert ServiceEventType.INSTANCE_HEARTBEAT_UPDATED.value == "instance_heartbeat_updated"
        assert ServiceEventType.CUSTOM.value == "custom"


class TestServiceEvent:
    """Test ServiceEvent dataclass."""

    def test_service_event_creation(self) -> None:
        """Test creating a service event."""
        timestamp = datetime.now(UTC)
        event = ServiceEvent(
            event_type=ServiceEventType.INSTANCE_REGISTERED,
            service_name="test-service",
            instance_id="instance-123",
            timestamp=timestamp,
            metadata={"version": "1.0.0"},
        )

        assert event.event_type == ServiceEventType.INSTANCE_REGISTERED
        assert event.service_name == "test-service"
        assert event.instance_id == "instance-123"
        assert event.timestamp == timestamp
        assert event.metadata == {"version": "1.0.0"}

    def test_service_event_without_metadata(self) -> None:
        """Test creating a service event without metadata."""
        timestamp = datetime.now(UTC)
        event = ServiceEvent(
            event_type=ServiceEventType.INSTANCE_UNREGISTERED,
            service_name="api-service",
            instance_id="api-001",
            timestamp=timestamp,
        )

        assert event.event_type == ServiceEventType.INSTANCE_UNREGISTERED
        assert event.service_name == "api-service"
        assert event.instance_id == "api-001"
        assert event.timestamp == timestamp
        assert event.metadata is None


class TestInstanceStatusChangedEvent:
    """Test InstanceStatusChangedEvent class."""

    def test_instance_status_changed_event_creation(self) -> None:
        """Test creating an instance status changed event."""
        timestamp = datetime.now(UTC)
        event = InstanceStatusChangedEvent(
            service_name="auth-service",
            instance_id="auth-001",
            timestamp=timestamp,
            old_status=ServiceStatus.ONLINE,
            new_status=ServiceStatus.OFFLINE,
            metadata={"reason": "heartbeat_timeout"},
        )

        # Check base class attributes
        assert event.event_type == ServiceEventType.INSTANCE_STATUS_CHANGED
        assert event.service_name == "auth-service"
        assert event.instance_id == "auth-001"
        assert event.timestamp == timestamp
        assert event.metadata == {"reason": "heartbeat_timeout"}

        # Check specific attributes
        assert event.old_status == ServiceStatus.ONLINE
        assert event.new_status == ServiceStatus.OFFLINE

    def test_instance_status_changed_event_without_metadata(self) -> None:
        """Test creating an instance status changed event without metadata."""
        timestamp = datetime.now(UTC)
        event = InstanceStatusChangedEvent(
            service_name="cache-service",
            instance_id="cache-002",
            timestamp=timestamp,
            old_status=ServiceStatus.OFFLINE,
            new_status=ServiceStatus.ONLINE,
        )

        assert event.event_type == ServiceEventType.INSTANCE_STATUS_CHANGED
        assert event.service_name == "cache-service"
        assert event.instance_id == "cache-002"
        assert event.timestamp == timestamp
        assert event.metadata is None
        assert event.old_status == ServiceStatus.OFFLINE
        assert event.new_status == ServiceStatus.ONLINE

    def test_instance_status_changed_event_inheritance(self) -> None:
        """Test that InstanceStatusChangedEvent inherits from ServiceEvent."""
        event = InstanceStatusChangedEvent(
            service_name="test",
            instance_id="test-1",
            timestamp=datetime.now(UTC),
            old_status=ServiceStatus.ONLINE,
            new_status=ServiceStatus.UNHEALTHY,
        )

        # Should be instance of both classes
        assert isinstance(event, InstanceStatusChangedEvent)
        assert isinstance(event, ServiceEvent)
