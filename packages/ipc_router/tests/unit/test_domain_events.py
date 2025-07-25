"""Unit tests for domain events."""

from __future__ import annotations

from datetime import UTC, datetime

from ipc_router.domain.enums import ServiceRole, ServiceStatus
from ipc_router.domain.events import (
    InstanceStatusChangedEvent,
    RoleChangedEvent,
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
        assert ServiceEventType.INSTANCE_ROLE_CHANGED.value == "instance_role_changed"
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


class TestRoleChangedEvent:
    """Test RoleChangedEvent class."""

    def test_role_changed_event_creation(self) -> None:
        """Test creating a role changed event."""
        timestamp = datetime.now(UTC)
        event = RoleChangedEvent(
            service_name="api-service",
            instance_id="api-001",
            timestamp=timestamp,
            old_role=ServiceRole.STANDBY,
            new_role=ServiceRole.ACTIVE,
            resource_id="res_123",
            metadata={"promoted_by": "health_checker"},
        )

        # Check base class attributes
        assert event.event_type == ServiceEventType.INSTANCE_ROLE_CHANGED
        assert event.service_name == "api-service"
        assert event.instance_id == "api-001"
        assert event.timestamp == timestamp
        assert event.metadata == {"promoted_by": "health_checker"}

        # Check specific attributes
        assert event.old_role == ServiceRole.STANDBY
        assert event.new_role == ServiceRole.ACTIVE
        assert event.resource_id == "res_123"

    def test_role_changed_event_new_registration(self) -> None:
        """Test role changed event for new registration (no old role)."""
        timestamp = datetime.now(UTC)
        event = RoleChangedEvent(
            service_name="worker-service",
            instance_id="worker-001",
            timestamp=timestamp,
            old_role=None,
            new_role=ServiceRole.ACTIVE,
            resource_id="task_queue",
        )

        assert event.event_type == ServiceEventType.INSTANCE_ROLE_CHANGED
        assert event.old_role is None
        assert event.new_role == ServiceRole.ACTIVE
        assert event.resource_id == "task_queue"
        assert event.metadata is None

    def test_role_changed_event_unregistration(self) -> None:
        """Test role changed event for unregistration (no new role)."""
        timestamp = datetime.now(UTC)
        event = RoleChangedEvent(
            service_name="db-service",
            instance_id="db-primary",
            timestamp=timestamp,
            old_role=ServiceRole.ACTIVE,
            new_role=None,
            metadata={"reason": "graceful_shutdown"},
        )

        assert event.event_type == ServiceEventType.INSTANCE_ROLE_CHANGED
        assert event.old_role == ServiceRole.ACTIVE
        assert event.new_role is None
        assert event.resource_id is None

    def test_role_changed_event_without_resource(self) -> None:
        """Test role changed event without resource ID."""
        timestamp = datetime.now(UTC)
        event = RoleChangedEvent(
            service_name="cache-service",
            instance_id="cache-002",
            timestamp=timestamp,
            old_role=ServiceRole.STANDBY,
            new_role=ServiceRole.ACTIVE,
        )

        assert event.service_name == "cache-service"
        assert event.instance_id == "cache-002"
        assert event.old_role == ServiceRole.STANDBY
        assert event.new_role == ServiceRole.ACTIVE
        assert event.resource_id is None

    def test_role_changed_event_inheritance(self) -> None:
        """Test that RoleChangedEvent inherits from ServiceEvent."""
        event = RoleChangedEvent(
            service_name="test",
            instance_id="test-1",
            timestamp=datetime.now(UTC),
            old_role=ServiceRole.ACTIVE,
            new_role=ServiceRole.STANDBY,
        )

        # Should be instance of both classes
        assert isinstance(event, RoleChangedEvent)
        assert isinstance(event, ServiceEvent)
