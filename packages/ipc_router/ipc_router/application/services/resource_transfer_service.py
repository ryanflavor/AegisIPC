"""Resource transfer service for managing resource ownership transfers."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ipc_router.domain.events import ServiceEventType
from ipc_router.domain.exceptions import (
    NotFoundError,
    ResourceNotFoundError,
    ValidationError,
)
from ipc_router.infrastructure.logging import get_logger

from .resource_registry import ResourceRegistry
from .service_registry import ServiceRegistry

logger = get_logger(__name__)


@dataclass
class ResourceTransferEvent:
    """Event for resource transfer operations."""

    event_type: ServiceEventType
    resource_ids: list[str]
    from_instance_id: str
    to_instance_id: str
    service_name: str
    transfer_id: str
    reason: str
    timestamp: datetime
    metadata: dict[str, Any]


class ResourceTransferService:
    """Service for managing resource ownership transfers between instances.

    This service provides atomic resource transfer operations with
    ownership verification, audit logging, and event notifications.
    """

    def __init__(
        self,
        resource_registry: ResourceRegistry,
        service_registry: ServiceRegistry,
    ) -> None:
        """Initialize the resource transfer service.

        Args:
            resource_registry: Registry for resource management
            service_registry: Registry for service instances
        """
        self._resource_registry = resource_registry
        self._service_registry = service_registry
        self._transfer_lock = asyncio.Lock()
        self._transfer_history: list[ResourceTransferEvent] = []
        self._max_history_size = 1000

    async def transfer_resources(
        self,
        service_name: str,
        resource_ids: list[str],
        from_instance_id: str,
        to_instance_id: str,
        verify_ownership: bool = True,
        reason: str = "Manual transfer",
    ) -> tuple[list[str], dict[str, str], str]:
        """Transfer resource ownership between instances.

        Args:
            service_name: Service name
            resource_ids: Resource IDs to transfer
            from_instance_id: Current owner instance ID
            to_instance_id: Target instance ID
            verify_ownership: Whether to verify current ownership
            reason: Transfer reason for audit

        Returns:
            Tuple of (transferred IDs, failed transfers, transfer ID)

        Raises:
            ValidationError: If validation fails
            NotFoundError: If target instance not found
        """
        # Validate inputs
        if not resource_ids:
            raise ValidationError("Resource IDs list cannot be empty")

        if from_instance_id == to_instance_id:
            raise ValidationError("Source and target instances cannot be the same")

        # Generate unique transfer ID
        transfer_id = f"transfer_{uuid.uuid4().hex[:16]}"

        logger.info(
            "Starting resource transfer",
            extra={
                "transfer_id": transfer_id,
                "service_name": service_name,
                "from_instance_id": from_instance_id,
                "to_instance_id": to_instance_id,
                "resource_count": len(resource_ids),
                "reason": reason,
            },
        )

        # Verify target instance exists and is healthy
        try:
            service_info = await self._service_registry.get_service(service_name)
            target_instance = None
            for instance in service_info.instances:
                if instance.instance_id == to_instance_id:
                    target_instance = instance
                    break

            if not target_instance:
                raise NotFoundError(resource_type="Instance", resource_id=to_instance_id)

            # Check if instance is healthy
            status_value = (
                target_instance.status
                if isinstance(target_instance.status, str)
                else target_instance.status.value
            )
            if status_value.lower() != "online":
                raise ValidationError(f"Target instance {to_instance_id} is not healthy")
        except NotFoundError as e:
            raise NotFoundError(resource_type="Instance", resource_id=to_instance_id) from e

        # Execute transfer atomically
        async with self._transfer_lock:
            transferred: list[str] = []
            failed: dict[str, str] = {}

            for resource_id in resource_ids:
                try:
                    # Verify ownership if required
                    if verify_ownership:
                        current_owner = await self._verify_resource_ownership(
                            service_name, resource_id, from_instance_id
                        )
                        if not current_owner:
                            failed[resource_id] = "Not owned by source instance"
                            continue

                    # Execute atomic transfer
                    success = await self._execute_atomic_transfer(
                        service_name,
                        resource_id,
                        from_instance_id,
                        to_instance_id,
                    )

                    if success:
                        transferred.append(resource_id)
                    else:
                        failed[resource_id] = "Transfer failed"

                except ResourceNotFoundError:
                    failed[resource_id] = "Resource not found"
                except Exception as e:
                    logger.error(
                        "Unexpected error during resource transfer",
                        exc_info=e,
                        extra={
                            "transfer_id": transfer_id,
                            "resource_id": resource_id,
                        },
                    )
                    failed[resource_id] = f"Unexpected error: {e!s}"

            # Create transfer event
            transfer_event = ResourceTransferEvent(
                event_type=ServiceEventType.CUSTOM,
                resource_ids=transferred,
                from_instance_id=from_instance_id,
                to_instance_id=to_instance_id,
                service_name=service_name,
                transfer_id=transfer_id,
                reason=reason,
                timestamp=datetime.now(),
                metadata={
                    "total_requested": len(resource_ids),
                    "total_transferred": len(transferred),
                    "total_failed": len(failed),
                },
            )

            # Record in audit log
            await self._record_transfer_audit(transfer_event, failed)

            # Notify about transfer
            await self._notify_transfer(transfer_event)

            logger.info(
                "Resource transfer completed",
                extra={
                    "transfer_id": transfer_id,
                    "transferred_count": len(transferred),
                    "failed_count": len(failed),
                },
            )

            return transferred, failed, transfer_id

    async def _verify_resource_ownership(
        self,
        service_name: str,
        resource_id: str,
        expected_owner: str,
    ) -> bool:
        """Verify resource ownership.

        Args:
            service_name: Service name
            resource_id: Resource ID
            expected_owner: Expected owner instance ID

        Returns:
            True if resource is owned by expected owner

        Raises:
            ResourceNotFoundError: If resource not found
        """
        try:
            owner = await self._resource_registry.get_resource_owner(resource_id)
            return owner == expected_owner
        except ResourceNotFoundError:
            raise

    async def _execute_atomic_transfer(
        self,
        service_name: str,
        resource_id: str,
        from_instance_id: str,
        to_instance_id: str,
    ) -> bool:
        """Execute atomic resource transfer.

        Args:
            service_name: Service name
            resource_id: Resource ID
            from_instance_id: Source instance ID
            to_instance_id: Target instance ID

        Returns:
            True if transfer succeeded
        """
        # Store metadata for potential rollback
        resource_metadata = None

        try:
            # Get current resource with metadata
            resource = await self._resource_registry.get_resource(resource_id)

            if not resource:
                raise ResourceNotFoundError(resource_id)

            # Store metadata for potential rollback
            resource_metadata = resource.metadata

            # Release from source
            release_success = await self._resource_registry.release_resource(
                resource_id, from_instance_id
            )

            if not release_success:
                logger.warning(
                    "Failed to release resource from source",
                    extra={
                        "resource_id": resource_id,
                        "from_instance_id": from_instance_id,
                    },
                )
                return False

            # Register to target with same metadata
            await self._resource_registry.register_resource(
                resource_id=resource_id,
                owner_instance_id=to_instance_id,
                service_name=service_name,
                metadata=resource_metadata,  # Preserve metadata
                force=True,  # Force to ensure atomic transfer
            )

            return True

        except Exception as e:
            logger.error(
                "Atomic transfer failed",
                exc_info=e,
                extra={
                    "resource_id": resource_id,
                    "from_instance_id": from_instance_id,
                    "to_instance_id": to_instance_id,
                },
            )
            # Attempt to restore original state if we have metadata
            if resource_metadata is not None:
                try:
                    await self._resource_registry.register_resource(
                        resource_id=resource_id,
                        owner_instance_id=from_instance_id,
                        service_name=service_name,
                        metadata=resource_metadata,
                        force=True,
                    )
                except Exception:
                    logger.critical(
                        "Failed to restore resource after failed transfer",
                        extra={"resource_id": resource_id},
                    )
            return False

    async def _record_transfer_audit(
        self,
        transfer_event: ResourceTransferEvent,
        failed: dict[str, str],
    ) -> None:
        """Record transfer in audit log.

        Args:
            transfer_event: Transfer event
            failed: Failed transfers with reasons
        """
        # Add to history
        self._transfer_history.append(transfer_event)

        # Trim history if needed
        if len(self._transfer_history) > self._max_history_size:
            self._transfer_history = self._transfer_history[-self._max_history_size :]

        # Log audit entry
        logger.info(
            "Resource transfer audit",
            extra={
                "transfer_id": transfer_event.transfer_id,
                "from_instance_id": transfer_event.from_instance_id,
                "to_instance_id": transfer_event.to_instance_id,
                "resource_count": len(transfer_event.resource_ids),
                "failed_count": len(failed),
                "reason": transfer_event.reason,
                "timestamp": transfer_event.timestamp.isoformat(),
            },
        )

    async def _notify_transfer(self, transfer_event: ResourceTransferEvent) -> None:
        """Send notifications about resource transfer.

        Args:
            transfer_event: Transfer event to notify about
        """
        # For now, just log the notification
        # In a real implementation, this would publish to event bus
        logger.info(
            "Resource transfer notification",
            extra={
                "event_type": "resource_transfer_completed",
                "transfer_id": transfer_event.transfer_id,
                "resource_ids": transfer_event.resource_ids,
            },
        )

    def get_transfer_history(
        self,
        limit: int = 100,
        service_name: str | None = None,
        instance_id: str | None = None,
    ) -> list[ResourceTransferEvent]:
        """Get transfer history.

        Args:
            limit: Maximum number of entries to return
            service_name: Filter by service name
            instance_id: Filter by instance ID (source or target)

        Returns:
            List of transfer events, most recent first
        """
        # Filter history
        filtered = self._transfer_history

        if service_name:
            filtered = [e for e in filtered if e.service_name == service_name]

        if instance_id:
            filtered = [
                e
                for e in filtered
                if e.from_instance_id == instance_id or e.to_instance_id == instance_id
            ]

        # Return most recent first, limited
        return list(reversed(filtered))[:limit]
