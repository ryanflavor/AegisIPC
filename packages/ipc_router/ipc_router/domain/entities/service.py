"""Service and ServiceInstance domain entities."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ..enums import ServiceStatus


@dataclass
class ServiceInstance:
    """Represents a single instance of a service.

    Attributes:
        instance_id: Unique identifier for this service instance
        service_name: Name of the service this instance belongs to
        status: Current status of the instance
        registered_at: Timestamp when the instance was registered
        last_heartbeat: Timestamp of the last heartbeat received
        metadata: Optional metadata associated with the instance
    """

    instance_id: str
    service_name: str
    status: ServiceStatus
    registered_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_heartbeat: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def update_heartbeat(self) -> None:
        """Update the last heartbeat timestamp to current time."""
        self.last_heartbeat = datetime.now(UTC)

    def is_healthy(self, timeout_seconds: int = 30) -> bool:
        """Check if the instance is healthy based on heartbeat.

        Args:
            timeout_seconds: Maximum seconds since last heartbeat to consider healthy

        Returns:
            True if instance is healthy, False otherwise
        """
        time_since_heartbeat = (datetime.now(UTC) - self.last_heartbeat).total_seconds()
        return time_since_heartbeat <= timeout_seconds


@dataclass
class Service:
    """Represents a service with multiple instances.

    Attributes:
        name: Unique name of the service
        instances: Dictionary of instance_id to ServiceInstance
        created_at: Timestamp when the service was first registered
        metadata: Optional metadata associated with the service
    """

    name: str
    instances: dict[str, ServiceInstance] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_instance(self, instance: ServiceInstance) -> None:
        """Add a new instance to the service.

        Args:
            instance: ServiceInstance to add
        """
        self.instances[instance.instance_id] = instance

    def remove_instance(self, instance_id: str) -> ServiceInstance | None:
        """Remove an instance from the service.

        Args:
            instance_id: ID of the instance to remove

        Returns:
            The removed ServiceInstance if found, None otherwise
        """
        return self.instances.pop(instance_id, None)

    def get_instance(self, instance_id: str) -> ServiceInstance | None:
        """Get a specific instance by ID.

        Args:
            instance_id: ID of the instance to retrieve

        Returns:
            ServiceInstance if found, None otherwise
        """
        return self.instances.get(instance_id)

    def get_healthy_instances(self, timeout_seconds: int = 30) -> list[ServiceInstance]:
        """Get all healthy instances of this service.

        Args:
            timeout_seconds: Maximum seconds since last heartbeat to consider healthy

        Returns:
            List of healthy ServiceInstance objects
        """
        return [
            instance for instance in self.instances.values() if instance.is_healthy(timeout_seconds)
        ]

    @property
    def instance_count(self) -> int:
        """Get the total number of instances."""
        return len(self.instances)

    @property
    def healthy_instance_count(self) -> int:
        """Get the number of healthy instances."""
        return len(self.get_healthy_instances())
