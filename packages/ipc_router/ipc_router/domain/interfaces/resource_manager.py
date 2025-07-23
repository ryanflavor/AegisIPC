"""Abstract interface for resource management operations.

This module defines the ResourceManager interface that provides
operations for registering, releasing, and querying resources.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from ipc_router.domain.entities.resource import Resource, ResourceMetadata


class ResourceManager(ABC):
    """Abstract interface for managing resources across service instances.

    This interface defines the contract for resource management operations
    including registration, release, querying, and ownership transfer.
    All implementations must ensure thread-safety and atomicity.
    """

    @abstractmethod
    async def register_resource(
        self,
        resource_id: str,
        owner_instance_id: str,
        service_name: str,
        metadata: ResourceMetadata,
        force: bool = False,
    ) -> Resource:
        """Register a new resource with the specified owner.

        Args:
            resource_id: Unique identifier for the resource
            owner_instance_id: ID of the instance claiming ownership
            service_name: Name of the service managing the resource
            metadata: Resource metadata including type, tags, etc.
            force: If True, forcefully take ownership even if already owned

        Returns:
            The registered Resource instance

        Raises:
            ResourceConflictError: If resource is already owned and force=False
            ValidationError: If any parameters are invalid
        """
        pass

    @abstractmethod
    async def release_resource(self, resource_id: str, instance_id: str) -> bool:
        """Release a resource owned by the specified instance.

        Args:
            resource_id: ID of the resource to release
            instance_id: ID of the instance releasing the resource

        Returns:
            True if the resource was released, False if not found

        Raises:
            ResourceOwnershipError: If instance doesn't own the resource
        """
        pass

    @abstractmethod
    async def get_resource(self, resource_id: str) -> Resource | None:
        """Retrieve a resource by its ID.

        Args:
            resource_id: ID of the resource to retrieve

        Returns:
            The Resource if found, None otherwise
        """
        pass

    @abstractmethod
    async def get_resource_owner(self, resource_id: str) -> str | None:
        """Get the owner instance ID for a resource.

        Args:
            resource_id: ID of the resource

        Returns:
            The owner instance ID if found, None otherwise
        """
        pass

    @abstractmethod
    async def list_resources_by_instance(self, instance_id: str) -> list[Resource]:
        """List all resources owned by a specific instance.

        Args:
            instance_id: ID of the instance

        Returns:
            List of resources owned by the instance
        """
        pass

    @abstractmethod
    async def list_resources_by_service(
        self, service_name: str, resource_type: str | None = None, tags: list[str] | None = None
    ) -> list[Resource]:
        """List resources for a service with optional filtering.

        Args:
            service_name: Name of the service
            resource_type: Optional filter by resource type
            tags: Optional filter by tags (any match)

        Returns:
            List of matching resources
        """
        pass

    @abstractmethod
    async def transfer_resource(
        self, resource_id: str, from_instance_id: str, to_instance_id: str
    ) -> Resource:
        """Transfer resource ownership between instances.

        Args:
            resource_id: ID of the resource to transfer
            from_instance_id: Current owner instance ID
            to_instance_id: New owner instance ID

        Returns:
            The updated Resource with new ownership

        Raises:
            ResourceNotFoundError: If resource doesn't exist
            ResourceOwnershipError: If from_instance doesn't own the resource
        """
        pass

    @abstractmethod
    async def bulk_register_resources(
        self,
        resources: list[tuple[str, ResourceMetadata]],
        owner_instance_id: str,
        service_name: str,
        continue_on_error: bool = False,
    ) -> tuple[list[Resource], list[tuple[str, str]]]:
        """Register multiple resources in a single operation.

        Args:
            resources: List of (resource_id, metadata) tuples
            owner_instance_id: ID of the instance claiming ownership
            service_name: Name of the service managing the resources
            continue_on_error: If True, continue on conflicts; if False, rollback all

        Returns:
            Tuple of (successfully registered resources, failed registrations)
            Failed registrations are tuples of (resource_id, error_message)
        """
        pass

    @abstractmethod
    async def bulk_release_resources(
        self, resource_ids: list[str], instance_id: str
    ) -> tuple[list[str], list[str]]:
        """Release multiple resources owned by an instance.

        Args:
            resource_ids: List of resource IDs to release
            instance_id: ID of the instance releasing resources

        Returns:
            Tuple of (successfully released IDs, failed IDs)
        """
        pass

    @abstractmethod
    async def release_all_instance_resources(self, instance_id: str) -> int:
        """Release all resources owned by an instance.

        This is typically called when an instance goes offline.

        Args:
            instance_id: ID of the instance

        Returns:
            Number of resources released
        """
        pass

    @abstractmethod
    async def cleanup_expired_resources(self, current_time: datetime | None = None) -> int:
        """Remove all expired resources based on their TTL.

        Args:
            current_time: Time to use for expiration check, defaults to now

        Returns:
            Number of resources cleaned up
        """
        pass

    @abstractmethod
    async def get_resource_count_by_instance(self, instance_id: str) -> int:
        """Get the count of resources owned by an instance.

        Args:
            instance_id: ID of the instance

        Returns:
            Number of resources owned
        """
        pass

    @abstractmethod
    async def check_resource_health(self, resource_id: str) -> bool:
        """Check if a resource and its owner are healthy.

        Args:
            resource_id: ID of the resource to check

        Returns:
            True if both resource and owner are healthy, False otherwise
        """
        pass
