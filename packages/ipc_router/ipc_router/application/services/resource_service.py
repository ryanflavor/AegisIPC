"""Resource service for high-level resource management operations.

This module provides business logic for resource operations including
registration, release, query, and event notifications.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from ipc_router.domain.entities import Resource, ResourceMetadata
from ipc_router.domain.events import ServiceEvent, ServiceEventType
from ipc_router.domain.exceptions import (
    NotFoundError,
    ResourceConflictError,
    ResourceNotFoundError,
    ValidationError,
)
from ipc_router.infrastructure.logging import get_logger

from .resource_registry import ResourceRegistry

logger = get_logger(__name__)


class ResourceEvent(ServiceEvent):
    """Event for resource-related operations."""

    def __init__(
        self,
        event_type: ServiceEventType,
        resource_id: str,
        service_name: str,
        instance_id: str,
        metadata: dict[str, Any],
        timestamp: datetime | None = None,
    ) -> None:
        """Initialize a resource event.

        Args:
            event_type: Type of the event
            resource_id: ID of the affected resource
            service_name: Service managing the resource
            instance_id: Instance owning the resource
            metadata: Additional event metadata
            timestamp: Event timestamp, defaults to now
        """
        super().__init__(
            service_name=service_name,
            instance_id=instance_id,
            event_type=event_type,
            timestamp=timestamp or datetime.now(UTC),
            metadata={"resource_id": resource_id, **metadata},
        )
        self.resource_id = resource_id


class ResourceService:
    """Application service for resource management operations.

    This service provides high-level business operations for resources,
    including registration, release, queries, and event notifications.
    """

    def __init__(self, registry: ResourceRegistry) -> None:
        """Initialize the resource service.

        Args:
            registry: The resource registry to use
        """
        self._registry = registry
        self._event_handlers: list[tuple[str, Any]] = []
        logger.info("ResourceService initialized")

    async def register_resource(
        self,
        service_name: str,
        instance_id: str,
        resource_id: str,
        metadata: ResourceMetadata,
        force: bool = False,
        notify: bool = True,
    ) -> Resource:
        """Register a resource with business logic and event notification.

        Args:
            service_name: Name of the service
            instance_id: ID of the instance claiming ownership
            resource_id: ID of the resource
            metadata: Resource metadata
            force: Whether to force ownership takeover
            notify: Whether to emit events

        Returns:
            The registered resource

        Raises:
            ResourceConflictError: If resource is already owned
            ValidationError: If service/instance doesn't exist
        """
        # Validate service and instance exist
        try:
            service_info = await self._registry.get_service(service_name)
            instance_found = any(inst.instance_id == instance_id for inst in service_info.instances)
            if not instance_found:
                raise ValidationError(
                    f"Instance '{instance_id}' not found in service '{service_name}'",
                    field="instance_id",
                )
        except NotFoundError as e:
            raise ValidationError(
                f"Service '{service_name}' not found", field="service_name"
            ) from e

        # Check for existing resource
        existing = await self._registry.get_resource(resource_id)

        # Register the resource
        try:
            resource = await self._registry.register_resource(
                resource_id=resource_id,
                owner_instance_id=instance_id,
                service_name=service_name,
                metadata=metadata,
                force=force,
            )
        except ResourceConflictError as e:
            logger.warning(
                "Resource registration conflict",
                extra={
                    "resource_id": resource_id,
                    "requesting_instance": instance_id,
                    "current_owner": e.details.get("current_owner"),
                    "force": force,
                },
            )
            raise

        # Emit event if requested
        if notify:
            event_type = (
                ServiceEventType.INSTANCE_STATUS_CHANGED
                if existing and existing.is_owned_by(instance_id)
                else ServiceEventType.INSTANCE_REGISTERED
            )

            await self._emit_resource_event(
                event_type=event_type,
                resource=resource,
                metadata={
                    "action": "registered",
                    "forced": bool(existing and not existing.is_owned_by(instance_id)),
                    "previous_owner": existing.owner_instance_id if existing else None,
                },
            )

        return resource

    async def release_resource(
        self, resource_id: str, instance_id: str, notify: bool = True
    ) -> bool:
        """Release a resource with business logic and event notification.

        Args:
            resource_id: ID of the resource to release
            instance_id: ID of the instance releasing
            notify: Whether to emit events

        Returns:
            True if released, False if not found

        Raises:
            ResourceOwnershipError: If instance doesn't own the resource
        """
        # Get resource before release for event data
        resource = await self._registry.get_resource(resource_id)
        if resource is None:
            return False

        # Release the resource
        released = await self._registry.release_resource(resource_id, instance_id)

        # Emit event if requested and successful
        if released and notify:
            await self._emit_resource_event(
                event_type=ServiceEventType.INSTANCE_UNREGISTERED,
                resource=resource,
                metadata={"action": "released"},
            )

        return released

    async def query_resources(
        self,
        service_name: str | None = None,
        instance_id: str | None = None,
        resource_type: str | None = None,
        tags: list[str] | None = None,
        include_expired: bool = False,
    ) -> list[Resource]:
        """Query resources with flexible filtering.

        Args:
            service_name: Filter by service name
            instance_id: Filter by owner instance
            resource_type: Filter by resource type
            tags: Filter by tags (any match)
            include_expired: Whether to include expired resources

        Returns:
            List of matching resources
        """
        resources: list[Resource] = []

        # Get resources based on primary filter
        if instance_id:
            resources = await self._registry.list_resources_by_instance(instance_id)
        elif service_name:
            resources = await self._registry.list_resources_by_service(
                service_name, resource_type, tags
            )
        else:
            # Get all resources (implement if needed)
            logger.warning("Query without service or instance filter not yet implemented")
            return []

        # Apply additional filters
        if service_name and instance_id:
            # Both filters specified, need intersection
            resources = [r for r in resources if r.service_name == service_name]

        if not include_expired:
            # Filter out expired resources
            resources = [r for r in resources if not r.is_expired()]

        logger.debug(
            "Resource query completed",
            extra={
                "service_name": service_name,
                "instance_id": instance_id,
                "resource_type": resource_type,
                "tags": tags,
                "result_count": len(resources),
                "include_expired": include_expired,
            },
        )

        return resources

    async def transfer_resource(
        self,
        resource_id: str,
        from_instance_id: str,
        to_instance_id: str,
        reason: str,
        notify: bool = True,
    ) -> Resource:
        """Transfer resource ownership with audit trail.

        Args:
            resource_id: ID of the resource
            from_instance_id: Current owner
            to_instance_id: New owner
            reason: Reason for transfer
            notify: Whether to emit events

        Returns:
            The updated resource

        Raises:
            ResourceNotFoundError: If resource doesn't exist
            ResourceOwnershipError: If from_instance doesn't own it
            ValidationError: If to_instance doesn't exist
        """
        # Get original resource
        original = await self._registry.get_resource(resource_id)
        if original is None:
            raise ResourceNotFoundError(resource_id=resource_id)

        # Validate target instance exists
        try:
            service_info = await self._registry.get_service(original.service_name)
            target_found = any(
                inst.instance_id == to_instance_id for inst in service_info.instances
            )
            if not target_found:
                raise ValidationError(
                    f"Target instance '{to_instance_id}' not found", field="to_instance_id"
                )
        except NotFoundError as e:
            raise ValidationError(
                f"Service '{original.service_name}' not found", field="service_name"
            ) from e

        # Perform transfer
        resource = await self._registry.transfer_resource(
            resource_id=resource_id,
            from_instance_id=from_instance_id,
            to_instance_id=to_instance_id,
        )

        # Emit event if requested
        if notify:
            await self._emit_resource_event(
                event_type=ServiceEventType.INSTANCE_STATUS_CHANGED,
                resource=resource,
                metadata={
                    "action": "transferred",
                    "from_instance": from_instance_id,
                    "to_instance": to_instance_id,
                    "reason": reason,
                },
            )

        logger.info(
            "Resource transferred",
            extra={
                "resource_id": resource_id,
                "from": from_instance_id,
                "to": to_instance_id,
                "reason": reason,
            },
        )

        return resource

    async def check_resource_health(self, resource_id: str) -> dict[str, Any]:
        """Check comprehensive health status of a resource.

        Args:
            resource_id: ID of the resource to check

        Returns:
            Dictionary with health status details
        """
        resource = await self._registry.get_resource(resource_id)
        if resource is None:
            return {"healthy": False, "exists": False, "resource_id": resource_id}

        # Check basic health
        basic_health = await self._registry.check_resource_health(resource_id)

        # Check expiration
        is_expired = resource.is_expired()
        time_until_expiry = None
        if resource.metadata.ttl_seconds and not is_expired:
            age = (datetime.now(UTC) - resource.metadata.last_modified).total_seconds()
            time_until_expiry = resource.metadata.ttl_seconds - age

        # Get owner instance status
        instance_status = None
        try:
            service_info = await self._registry.get_service(resource.service_name)
            for inst in service_info.instances:
                if inst.instance_id == resource.owner_instance_id:
                    instance_status = inst.status
                    break
        except Exception:
            pass

        return {
            "healthy": basic_health,
            "exists": True,
            "resource_id": resource_id,
            "owner_instance_id": resource.owner_instance_id,
            "service_name": resource.service_name,
            "instance_status": instance_status,
            "is_expired": is_expired,
            "time_until_expiry_seconds": time_until_expiry,
            "resource_type": resource.metadata.resource_type,
            "priority": resource.metadata.priority,
            "tags": resource.metadata.tags,
        }

    async def cleanup_expired_resources(self, notify: bool = True) -> int:
        """Clean up expired resources with notifications.

        Args:
            notify: Whether to emit events for cleaned resources

        Returns:
            Number of resources cleaned up
        """
        # Get expired resources before cleanup
        if notify:
            all_resources = await self.query_resources(include_expired=True)
            expired = [r for r in all_resources if r.is_expired()]

        # Perform cleanup
        count = await self._registry.cleanup_expired_resources()

        # Emit events if requested
        if notify and expired:
            for resource in expired:
                await self._emit_resource_event(
                    event_type=ServiceEventType.INSTANCE_UNREGISTERED,
                    resource=resource,
                    metadata={"action": "expired", "ttl_seconds": resource.metadata.ttl_seconds},
                )

        if count > 0:
            logger.info("Expired resources cleaned up", extra={"cleaned_count": count})

        return count

    def subscribe_to_resource_events(self, event_filter: str, handler: Any) -> None:
        """Subscribe to resource-related events.

        Args:
            event_filter: Filter for events (e.g., "registered", "released", "*")
            handler: Async callback function
        """
        self._event_handlers.append((event_filter, handler))
        logger.debug(
            "Resource event handler subscribed",
            extra={
                "filter": event_filter,
                "handler": handler.__name__ if hasattr(handler, "__name__") else str(handler),
            },
        )

    def unsubscribe_from_resource_events(self, handler: Any) -> None:
        """Unsubscribe from resource events.

        Args:
            handler: The handler to remove
        """
        self._event_handlers = [(f, h) for f, h in self._event_handlers if h != handler]

    async def _emit_resource_event(
        self, event_type: ServiceEventType, resource: Resource, metadata: dict[str, Any]
    ) -> None:
        """Emit a resource event to subscribers.

        Args:
            event_type: Type of the event
            resource: The affected resource
            metadata: Additional event metadata
        """
        event = ResourceEvent(
            event_type=event_type,
            resource_id=resource.resource_id,
            service_name=resource.service_name,
            instance_id=resource.owner_instance_id,
            metadata=metadata,
        )

        # Emit to resource-specific handlers
        tasks = []
        action = metadata.get("action", "")

        for filter_str, handler in self._event_handlers:
            if filter_str == "*" or filter_str == action:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        tasks.append(handler(event))
                    else:
                        loop = asyncio.get_event_loop()
                        tasks.append(loop.run_in_executor(None, handler, event))
                except Exception as e:
                    logger.error(
                        "Error in resource event handler",
                        exc_info=e,
                        extra={
                            "event_type": event_type.value,
                            "resource_id": resource.resource_id,
                            "handler": str(handler),
                        },
                    )

        # Also emit to base registry handlers
        await self._registry._emit_event(event)

        # Execute resource-specific handlers
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
