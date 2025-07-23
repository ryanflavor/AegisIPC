"""Resource domain entity for managing resource ownership and lifecycle.

This module defines the core Resource entity that represents a managed resource
with its ownership, metadata, and lifecycle information.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class ResourceMetadata:
    """Structured metadata for a resource.

    Attributes:
        resource_type: Type of resource (e.g., "user", "session", "document")
        version: Version number for optimistic locking
        tags: List of tags for categorization and search
        attributes: Custom key-value attributes
        created_by: Identifier of the creator
        last_modified: Last modification timestamp
        ttl_seconds: Time-to-live in seconds, None for permanent resources
        priority: Priority level for load balancing decisions (0-100)
    """

    resource_type: str
    version: int
    created_by: str
    last_modified: datetime
    tags: list[str] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    ttl_seconds: int | None = None
    priority: int = 0

    def __post_init__(self) -> None:
        """Validate metadata after initialization."""
        if not 0 <= self.priority <= 100:
            raise ValueError(f"Priority must be between 0 and 100, got {self.priority}")

        if self.ttl_seconds is not None and self.ttl_seconds <= 0:
            raise ValueError(f"TTL must be positive, got {self.ttl_seconds}")

        if not self.resource_type:
            raise ValueError("Resource type cannot be empty")

        if self.version < 0:
            raise ValueError(f"Version must be non-negative, got {self.version}")

    def is_expired(self, current_time: datetime | None = None) -> bool:
        """Check if the resource has expired based on TTL.

        Args:
            current_time: Current time for comparison, defaults to UTC now

        Returns:
            True if the resource has expired, False otherwise
        """
        if self.ttl_seconds is None:
            return False

        if current_time is None:
            current_time = datetime.now(UTC)

        age_seconds = (current_time - self.last_modified).total_seconds()
        return age_seconds > self.ttl_seconds


@dataclass(eq=False)
class Resource:
    """Domain entity representing a managed resource.

    A resource is uniquely identified by its resource_id and can only be
    owned by one service instance at a time. Resources support metadata,
    TTL-based expiration, and priority-based load balancing.

    Attributes:
        resource_id: Globally unique identifier for the resource
        owner_instance_id: ID of the instance that owns this resource
        service_name: Name of the service managing this resource
        registered_at: UTC timestamp when the resource was registered
        metadata: Structured metadata about the resource
    """

    resource_id: str
    owner_instance_id: str
    service_name: str
    registered_at: datetime
    metadata: ResourceMetadata | None = None

    def __post_init__(self) -> None:
        """Validate resource fields after initialization."""
        if not self.resource_id:
            raise ValueError("Resource ID cannot be empty")

        if not self.owner_instance_id:
            raise ValueError("Owner instance ID cannot be empty")

        if not self.service_name:
            raise ValueError("Service name cannot be empty")

        # Ensure registered_at is timezone-aware
        if self.registered_at.tzinfo is None:
            raise ValueError("Registered timestamp must be timezone-aware")

    def is_owned_by(self, instance_id: str) -> bool:
        """Check if the resource is owned by a specific instance.

        Args:
            instance_id: The instance ID to check ownership against

        Returns:
            True if owned by the specified instance, False otherwise
        """
        return self.owner_instance_id == instance_id

    def is_expired(self, current_time: datetime | None = None) -> bool:
        """Check if the resource has expired.

        Args:
            current_time: Current time for comparison, defaults to UTC now

        Returns:
            True if the resource has expired, False otherwise
        """
        if self.metadata is None:
            return False
        return self.metadata.is_expired(current_time)

    def transfer_ownership(self, new_instance_id: str) -> Resource:
        """Create a new Resource with transferred ownership.

        This method creates a new Resource instance with updated ownership
        while preserving all other attributes. The original Resource is
        not modified (immutability).

        Args:
            new_instance_id: The ID of the new owner instance

        Returns:
            A new Resource instance with updated ownership
        """
        return Resource(
            resource_id=self.resource_id,
            owner_instance_id=new_instance_id,
            service_name=self.service_name,
            registered_at=self.registered_at,
            metadata=self.metadata,
        )

    def __eq__(self, other: object) -> bool:
        """Resources are equal if they have the same resource_id."""
        if not isinstance(other, Resource):
            return False
        return self.resource_id == other.resource_id

    def __hash__(self) -> int:
        """Hash based on resource_id for use in sets and dicts."""
        return hash(self.resource_id)


@dataclass
class ResourceCollection:
    """Collection of resources with bulk operation support.

    This class provides efficient operations on multiple resources,
    supporting batch registration, release, and transfer operations.
    """

    resources: dict[str, Resource] = field(default_factory=dict)

    def add(self, resource: Resource) -> None:
        """Add a resource to the collection.

        Args:
            resource: The resource to add

        Raises:
            ValueError: If a resource with the same ID already exists
        """
        if resource.resource_id in self.resources:
            raise ValueError(f"Resource {resource.resource_id} already exists in collection")

        self.resources[resource.resource_id] = resource

    def remove(self, resource_id: str) -> Resource | None:
        """Remove and return a resource from the collection.

        Args:
            resource_id: The ID of the resource to remove

        Returns:
            The removed resource, or None if not found
        """
        return self.resources.pop(resource_id, None)

    def get(self, resource_id: str) -> Resource | None:
        """Get a resource by ID.

        Args:
            resource_id: The ID of the resource to retrieve

        Returns:
            The resource if found, None otherwise
        """
        return self.resources.get(resource_id)

    def get_by_owner(self, instance_id: str) -> list[Resource]:
        """Get all resources owned by a specific instance.

        Args:
            instance_id: The owner instance ID to filter by

        Returns:
            List of resources owned by the instance
        """
        return [r for r in self.resources.values() if r.is_owned_by(instance_id)]

    def get_expired(self, current_time: datetime | None = None) -> list[Resource]:
        """Get all expired resources.

        Args:
            current_time: Current time for comparison, defaults to UTC now

        Returns:
            List of expired resources
        """
        return [r for r in self.resources.values() if r.is_expired(current_time)]

    def transfer_ownership_bulk(
        self, resource_ids: list[str], new_instance_id: str
    ) -> tuple[list[Resource], list[str]]:
        """Transfer ownership of multiple resources.

        Args:
            resource_ids: List of resource IDs to transfer
            new_instance_id: The new owner instance ID

        Returns:
            Tuple of (transferred resources, not found resource IDs)
        """
        transferred = []
        not_found = []

        for resource_id in resource_ids:
            resource = self.resources.get(resource_id)
            if resource:
                new_resource = resource.transfer_ownership(new_instance_id)
                self.resources[resource_id] = new_resource
                transferred.append(new_resource)
            else:
                not_found.append(resource_id)

        return transferred, not_found

    def size(self) -> int:
        """Get the number of resources in the collection.

        Returns:
            The number of resources
        """
        return len(self.resources)

    def clear(self) -> None:
        """Remove all resources from the collection."""
        self.resources.clear()
