"""Resource registry application service extending ServiceRegistry.

This module provides resource management capabilities on top of the
existing service registry functionality.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from ipc_router.domain.entities import Resource, ResourceMetadata
from ipc_router.domain.exceptions import (
    ResourceConflictError,
    ResourceLimitExceededError,
    ResourceNotFoundError,
)
from ipc_router.domain.interfaces import ResourceManager
from ipc_router.domain.services.resource_validator import ResourceValidator
from ipc_router.infrastructure.logging import get_logger

from .service_registry import ServiceRegistry

logger = get_logger(__name__)


class ResourceRegistry(ServiceRegistry, ResourceManager):
    """Extended service registry with resource management capabilities.

    This class extends the base ServiceRegistry to add resource registration,
    ownership tracking, and resource-based routing support.
    """

    def __init__(self, max_resources_per_instance: int = 1000) -> None:
        """Initialize the resource registry.

        Args:
            max_resources_per_instance: Maximum resources allowed per instance
        """
        super().__init__()
        self._resources: dict[str, Resource] = {}
        self._resource_lock = asyncio.Lock()
        self._resource_validator = ResourceValidator(max_resources_per_instance)
        self._max_resources_per_instance = max_resources_per_instance
        logger.info(
            "ResourceRegistry initialized",
            extra={"max_resources_per_instance": max_resources_per_instance},
        )

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
            ResourceLimitExceededError: If instance exceeds resource limit
        """
        # Validate resource ID format
        self._resource_validator.validate_resource_id(resource_id)

        async with self._resource_lock:
            # Check if resource already exists
            existing_resource = self._resources.get(resource_id)

            # Validate ownership can be taken
            if not self._resource_validator.can_force_ownership(
                existing_resource, owner_instance_id, force
            ):
                if existing_resource is not None:
                    raise ResourceConflictError(
                        resource_id=resource_id, current_owner=existing_resource.owner_instance_id
                    )
                # Should not reach here since can_force_ownership returns True for None resource
                raise ResourceConflictError(resource_id=resource_id, current_owner="unknown")

            # Check resource limit
            if existing_resource is None or not existing_resource.is_owned_by(owner_instance_id):
                current_count = self._get_resource_count_by_instance_no_lock(owner_instance_id)
                self._resource_validator.validate_resource_limit(owner_instance_id, current_count)

            # Create or update resource
            resource = Resource(
                resource_id=resource_id,
                owner_instance_id=owner_instance_id,
                service_name=service_name,
                registered_at=datetime.now(UTC),
                metadata=metadata,
            )

            self._resources[resource_id] = resource

            logger.info(
                "Resource registered",
                extra={
                    "resource_id": resource_id,
                    "owner_instance_id": owner_instance_id,
                    "service_name": service_name,
                    "resource_type": metadata.resource_type,
                    "forced": force and existing_resource is not None,
                },
            )

            return resource

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
        async with self._resource_lock:
            resource = self._resources.get(resource_id)
            if resource is None:
                return False

            # Validate ownership
            self._resource_validator.validate_ownership(resource, instance_id, "release")

            # Remove resource
            del self._resources[resource_id]

            logger.info(
                "Resource released",
                extra={
                    "resource_id": resource_id,
                    "instance_id": instance_id,
                    "service_name": resource.service_name,
                },
            )

            return True

    async def get_resource(self, resource_id: str) -> Resource | None:
        """Retrieve a resource by its ID.

        Args:
            resource_id: ID of the resource to retrieve

        Returns:
            The Resource if found, None otherwise
        """
        async with self._resource_lock:
            return self._resources.get(resource_id)

    async def get_resource_owner(self, resource_id: str) -> str | None:
        """Get the owner instance ID for a resource.

        Args:
            resource_id: ID of the resource

        Returns:
            The owner instance ID if found, None otherwise
        """
        resource = await self.get_resource(resource_id)
        return resource.owner_instance_id if resource else None

    async def list_resources_by_instance(self, instance_id: str) -> list[Resource]:
        """List all resources owned by a specific instance.

        Args:
            instance_id: ID of the instance

        Returns:
            List of resources owned by the instance
        """
        async with self._resource_lock:
            return [
                resource
                for resource in self._resources.values()
                if resource.is_owned_by(instance_id)
            ]

    def _get_resource_count_by_instance_no_lock(self, instance_id: str) -> int:
        """Get resource count without acquiring lock (for internal use).

        Args:
            instance_id: ID of the instance

        Returns:
            Number of resources owned by the instance
        """
        # Direct count without lock - only use when already holding the lock
        return sum(1 for r in self._resources.values() if r.is_owned_by(instance_id))

    async def get_resource_count_by_instance(self, instance_id: str) -> int:
        """Get the number of resources owned by an instance.

        Args:
            instance_id: ID of the instance

        Returns:
            Number of resources owned by the instance
        """
        resources = await self.list_resources_by_instance(instance_id)
        return len(resources)

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
        async with self._resource_lock:
            resources = [r for r in self._resources.values() if r.service_name == service_name]

            # Apply filters
            if resource_type:
                resources = [r for r in resources if r.metadata.resource_type == resource_type]

            if tags:
                tag_set = set(tags)
                resources = [r for r in resources if any(tag in r.metadata.tags for tag in tag_set)]

            return resources

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
        async with self._resource_lock:
            resource = self._resources.get(resource_id)
            if resource is None:
                raise ResourceNotFoundError(resource_id=resource_id)

            # Validate transfer
            self._resource_validator.validate_transfer(resource, from_instance_id, to_instance_id)

            # Check target instance resource limit
            target_count = self._get_resource_count_by_instance_no_lock(to_instance_id)
            self._resource_validator.validate_resource_limit(to_instance_id, target_count)

            # Transfer ownership
            new_resource = resource.transfer_ownership(to_instance_id)
            self._resources[resource_id] = new_resource

            logger.info(
                "Resource transferred",
                extra={
                    "resource_id": resource_id,
                    "from_instance": from_instance_id,
                    "to_instance": to_instance_id,
                    "service_name": resource.service_name,
                },
            )

            return new_resource

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
        registered: list[Resource] = []
        failed: list[tuple[str, str]] = []

        # Check resource limit upfront
        current_count = await self.get_resource_count_by_instance(owner_instance_id)
        try:
            self._resource_validator.validate_resource_limit(
                owner_instance_id, current_count, len(resources)
            )
        except ResourceLimitExceededError as e:
            if not continue_on_error:
                raise
            # Limit the batch to what can fit
            max_allowed = self._max_resources_per_instance - current_count
            if max_allowed <= 0:
                return [], [(r[0], str(e)) for r in resources]
            # Track the resources that exceed the limit
            exceeded_resources = resources[max_allowed:]
            failed.extend([(r[0], f"Resource limit exceeded: {e!s}") for r in exceeded_resources])
            resources = resources[:max_allowed]

        # Process resources
        for resource_id, metadata in resources:
            try:
                resource = await self.register_resource(
                    resource_id=resource_id,
                    owner_instance_id=owner_instance_id,
                    service_name=service_name,
                    metadata=metadata,
                    force=False,
                )
                registered.append(resource)
            except Exception as e:
                failed.append((resource_id, str(e)))
                if not continue_on_error:
                    # Rollback registered resources
                    import contextlib

                    for r in registered:
                        with contextlib.suppress(Exception):
                            await self.release_resource(r.resource_id, owner_instance_id)
                    raise

        logger.info(
            "Bulk resource registration completed",
            extra={
                "owner_instance_id": owner_instance_id,
                "service_name": service_name,
                "requested": len(resources),
                "registered": len(registered),
                "failed": len(failed),
                "continue_on_error": continue_on_error,
            },
        )

        return registered, failed

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
        released: list[str] = []
        failed: list[str] = []

        for resource_id in resource_ids:
            try:
                if await self.release_resource(resource_id, instance_id):
                    released.append(resource_id)
                else:
                    failed.append(resource_id)
            except Exception:
                failed.append(resource_id)

        logger.info(
            "Bulk resource release completed",
            extra={
                "instance_id": instance_id,
                "requested": len(resource_ids),
                "released": len(released),
                "failed": len(failed),
            },
        )

        return released, failed

    async def release_all_instance_resources(self, instance_id: str) -> int:
        """Release all resources owned by an instance.

        This is typically called when an instance goes offline.

        Args:
            instance_id: ID of the instance

        Returns:
            Number of resources released
        """
        resources = await self.list_resources_by_instance(instance_id)
        resource_ids = [r.resource_id for r in resources]

        if not resource_ids:
            return 0

        released, _ = await self.bulk_release_resources(resource_ids, instance_id)

        logger.info(
            "Released all instance resources",
            extra={"instance_id": instance_id, "released_count": len(released)},
        )

        return len(released)

    async def cleanup_expired_resources(self, current_time: datetime | None = None) -> int:
        """Remove all expired resources based on their TTL.

        Args:
            current_time: Time to use for expiration check, defaults to now

        Returns:
            Number of resources cleaned up
        """
        if current_time is None:
            current_time = datetime.now(UTC)

        async with self._resource_lock:
            expired_ids = [
                resource_id
                for resource_id, resource in self._resources.items()
                if resource.is_expired(current_time)
            ]

            for resource_id in expired_ids:
                del self._resources[resource_id]

            if expired_ids:
                logger.info(
                    "Cleaned up expired resources",
                    extra={
                        "expired_count": len(expired_ids),
                        "check_time": current_time.isoformat(),
                    },
                )

            return len(expired_ids)

    async def check_resource_health(self, resource_id: str) -> bool:
        """Check if a resource and its owner are healthy.

        Args:
            resource_id: ID of the resource to check

        Returns:
            True if both resource and owner are healthy, False otherwise
        """
        resource = await self.get_resource(resource_id)
        if resource is None:
            return False

        # Check if resource is expired
        # For now, just check if resource exists and is not expired
        # In production, this would check the actual instance health
        return not resource.is_expired()

    async def unregister_instance(self, service_name: str, instance_id: str) -> None:
        """Override to also release instance resources when unregistering.

        Args:
            service_name: Name of the service
            instance_id: ID of the instance to unregister
        """
        # Release all resources owned by this instance
        await self.release_all_instance_resources(instance_id)

        # Call parent implementation
        await super().unregister_instance(service_name, instance_id)
