"""Domain events for service registry changes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from .enums import ServiceRole, ServiceStatus


class ServiceEventType(Enum):
    """Types of service registry events."""

    INSTANCE_REGISTERED = "instance_registered"
    INSTANCE_UNREGISTERED = "instance_unregistered"
    INSTANCE_STATUS_CHANGED = "instance_status_changed"
    INSTANCE_HEARTBEAT_UPDATED = "instance_heartbeat_updated"
    INSTANCE_ROLE_CHANGED = "instance_role_changed"
    CUSTOM = "custom"


@dataclass
class ServiceEvent:
    """Base class for service registry events."""

    event_type: ServiceEventType
    service_name: str
    instance_id: str
    timestamp: datetime
    metadata: dict[str, Any] | None = None


class InstanceStatusChangedEvent(ServiceEvent):
    """Event fired when instance status changes."""

    old_status: ServiceStatus
    new_status: ServiceStatus

    def __init__(
        self,
        service_name: str,
        instance_id: str,
        timestamp: datetime,
        old_status: ServiceStatus,
        new_status: ServiceStatus,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Initialize instance status changed event."""
        super().__init__(
            event_type=ServiceEventType.INSTANCE_STATUS_CHANGED,
            service_name=service_name,
            instance_id=instance_id,
            timestamp=timestamp,
            metadata=metadata,
        )
        self.old_status = old_status
        self.new_status = new_status


class RoleChangedEvent(ServiceEvent):
    """Event fired when instance role changes."""

    old_role: ServiceRole | None
    new_role: ServiceRole | None
    resource_id: str | None = None

    def __init__(
        self,
        service_name: str,
        instance_id: str,
        timestamp: datetime,
        old_role: ServiceRole | None,
        new_role: ServiceRole | None,
        resource_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Initialize role changed event.

        Args:
            service_name: Name of the service
            instance_id: Instance ID
            timestamp: Event timestamp
            old_role: Previous role (None for new registrations)
            new_role: New role (None for unregistrations)
            resource_id: Optional resource ID for resource-specific role changes
            metadata: Additional event metadata
        """
        super().__init__(
            event_type=ServiceEventType.INSTANCE_ROLE_CHANGED,
            service_name=service_name,
            instance_id=instance_id,
            timestamp=timestamp,
            metadata=metadata,
        )
        self.old_role = old_role
        self.new_role = new_role
        self.resource_id = resource_id


ServiceEventHandler = Callable[[ServiceEvent], Awaitable[None]]
