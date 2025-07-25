"""Service registry application service."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from ipc_client_sdk.models import (
    ServiceInfo,
    ServiceInstanceInfo,
    ServiceListResponse,
    ServiceRegistrationRequest,
    ServiceRegistrationResponse,
)

from ipc_router.domain.entities import Service, ServiceInstance
from ipc_router.domain.enums import ServiceRole, ServiceStatus
from ipc_router.domain.events import (
    InstanceStatusChangedEvent,
    RoleChangedEvent,
    ServiceEvent,
    ServiceEventType,
)
from ipc_router.domain.exceptions import (
    ConflictError,
    DuplicateServiceInstanceError,
    NotFoundError,
)
from ipc_router.infrastructure.logging import get_logger

logger = get_logger(__name__)


class ServiceRegistry:
    """Application service for managing service registration and discovery.

    This service provides the core business logic for registering services,
    managing their lifecycle, and enabling service discovery.
    """

    def __init__(self) -> None:
        """Initialize the service registry."""
        self._services: dict[str, Service] = {}
        self._lock = asyncio.Lock()
        self._event_handlers: list[tuple[ServiceEventType | None, Any]] = []
        # Track resource -> active instance mapping
        self._resource_active_instances: dict[
            str, tuple[str, str]
        ] = {}  # resource_id -> (service_name, instance_id)
        logger.info("ServiceRegistry initialized")

    async def register_service(
        self, request: ServiceRegistrationRequest
    ) -> ServiceRegistrationResponse:
        """Register a new service instance.

        Args:
            request: Service registration request containing service details

        Returns:
            ServiceRegistrationResponse indicating success or failure

        Raises:
            DuplicateServiceInstanceError: If instance ID already exists for the service
        """
        async with self._lock:
            service_name = request.service_name
            instance_id = request.instance_id

            # Check if service exists, create if not
            if service_name not in self._services:
                self._services[service_name] = Service(
                    name=service_name,
                    metadata=request.metadata,
                )
                logger.info(
                    "Created new service",
                    extra={
                        "service_name": service_name,
                        "metadata": request.metadata,
                    },
                )

            service = self._services[service_name]

            # Check for duplicate instance
            if service.get_instance(instance_id) is not None:
                logger.warning(
                    "Duplicate service instance registration attempt",
                    extra={
                        "service_name": service_name,
                        "instance_id": instance_id,
                    },
                )
                raise DuplicateServiceInstanceError(
                    service_name=service_name,
                    instance_id=instance_id,
                )

            # Determine role - default to STANDBY if not specified
            role = ServiceRole.STANDBY
            if hasattr(request, "role") and request.role:
                role = ServiceRole(request.role.upper())

            # Check for role conflicts if registering as ACTIVE
            if role == ServiceRole.ACTIVE:
                # Check if there's already an active instance for this resource
                resource_id = self._get_resource_id_from_metadata(request.metadata)
                if resource_id and resource_id in self._resource_active_instances:
                    existing_service, existing_instance = self._resource_active_instances[
                        resource_id
                    ]
                    logger.warning(
                        "Active role conflict detected",
                        extra={
                            "service_name": service_name,
                            "instance_id": instance_id,
                            "resource_id": resource_id,
                            "existing_service": existing_service,
                            "existing_instance": existing_instance,
                        },
                    )
                    raise ConflictError(
                        f"Resource {resource_id} already has an active instance: "
                        f"{existing_service}/{existing_instance}"
                    )

            # Create and add new instance
            now = datetime.now(UTC)
            instance = ServiceInstance(
                instance_id=instance_id,
                service_name=service_name,
                status=ServiceStatus.ONLINE,
                role=role,
                registered_at=now,
                last_heartbeat=now,
                metadata=request.metadata,
            )

            # Track active instance for resource if applicable
            if role == ServiceRole.ACTIVE:
                resource_id = self._get_resource_id_from_metadata(request.metadata)
                if resource_id:
                    self._resource_active_instances[resource_id] = (service_name, instance_id)

            service.add_instance(instance)

            # Emit role changed event for new registration
            resource_id = self._get_resource_id_from_metadata(request.metadata)
            event = RoleChangedEvent(
                service_name=service_name,
                instance_id=instance_id,
                timestamp=now,
                old_role=None,  # New registration
                new_role=role,
                resource_id=resource_id,
                metadata={"event_type": "registration"},
            )
            await self._emit_event(event)

            # Log role transition
            logger.info(
                "Role transition: new registration",
                extra={
                    "service_name": service_name,
                    "instance_id": instance_id,
                    "old_role": None,
                    "new_role": role.value,
                    "resource_id": resource_id,
                    "event_type": "registration",
                },
            )

            logger.info(
                "Service instance registered successfully",
                extra={
                    "service_name": service_name,
                    "instance_id": instance_id,
                    "role": role.value,
                    "instance_count": service.instance_count,
                    "metadata": request.metadata,
                },
            )

            return ServiceRegistrationResponse(
                success=True,
                service_name=service_name,
                instance_id=instance_id,
                role=role.value,
                registered_at=now,
                message=f"Service instance registered successfully as {role.value}",
            )

    async def get_service(self, service_name: str) -> ServiceInfo:
        """Get information about a specific service.

        Args:
            service_name: Name of the service to retrieve

        Returns:
            ServiceInfo containing service details and instances

        Raises:
            NotFoundError: If service does not exist
        """
        async with self._lock:
            if service_name not in self._services:
                raise NotFoundError(
                    resource_type="Service",
                    resource_id=service_name,
                )

            service = self._services[service_name]
            instances = [
                ServiceInstanceInfo(
                    instance_id=inst.instance_id,
                    status=inst.status,
                    role=inst.role.value if inst.role else None,
                    registered_at=inst.registered_at,
                    last_heartbeat=inst.last_heartbeat,
                    metadata=inst.metadata,
                )
                for inst in service.instances.values()
            ]

            return ServiceInfo(
                name=service.name,
                instances=instances,
                created_at=service.created_at,
                metadata=service.metadata,
            )

    async def list_services(self) -> ServiceListResponse:
        """List all registered services.

        Returns:
            ServiceListResponse containing all services and their instances
        """
        async with self._lock:
            services = []

            for service in self._services.values():
                instances = [
                    ServiceInstanceInfo(
                        instance_id=inst.instance_id,
                        status=inst.status,
                        role=inst.role.value if inst.role else None,
                        registered_at=inst.registered_at,
                        last_heartbeat=inst.last_heartbeat,
                        metadata=inst.metadata,
                    )
                    for inst in service.instances.values()
                ]

                services.append(
                    ServiceInfo(
                        name=service.name,
                        instances=instances,
                        created_at=service.created_at,
                        metadata=service.metadata,
                    )
                )

            logger.debug(
                "Listed all services",
                extra={
                    "service_count": len(services),
                    "total_instances": sum(len(s.instances) for s in services),
                },
            )

            return ServiceListResponse(
                services=services,
                total_count=len(services),
            )

    async def update_heartbeat(self, service_name: str, instance_id: str) -> None:
        """Update the heartbeat timestamp for a service instance.

        Args:
            service_name: Name of the service
            instance_id: ID of the instance to update

        Raises:
            NotFoundError: If service or instance does not exist
        """
        async with self._lock:
            if service_name not in self._services:
                raise NotFoundError(
                    resource_type="Service",
                    resource_id=service_name,
                )

            service = self._services[service_name]
            instance = service.get_instance(instance_id)

            if instance is None:
                raise NotFoundError(
                    resource_type="ServiceInstance",
                    resource_id=f"{service_name}/{instance_id}",
                )

            instance.update_heartbeat()

            logger.debug(
                "Updated heartbeat",
                extra={
                    "service_name": service_name,
                    "instance_id": instance_id,
                    "last_heartbeat": instance.last_heartbeat.isoformat(),
                },
            )

    async def unregister_instance(self, service_name: str, instance_id: str) -> None:
        """Unregister a service instance.

        Args:
            service_name: Name of the service
            instance_id: ID of the instance to unregister

        Raises:
            NotFoundError: If service or instance does not exist
        """
        async with self._lock:
            if service_name not in self._services:
                raise NotFoundError(
                    resource_type="Service",
                    resource_id=service_name,
                )

            service = self._services[service_name]
            removed_instance = service.remove_instance(instance_id)

            if removed_instance is None:
                raise NotFoundError(
                    resource_type="ServiceInstance",
                    resource_id=f"{service_name}/{instance_id}",
                )

            # Emit role changed event for unregistration
            if removed_instance.role:
                resource_id = self._get_resource_id_from_metadata(removed_instance.metadata)
                event = RoleChangedEvent(
                    service_name=service_name,
                    instance_id=instance_id,
                    timestamp=datetime.now(UTC),
                    old_role=removed_instance.role,
                    new_role=None,  # Unregistration
                    resource_id=resource_id,
                    metadata={"event_type": "unregistration"},
                )
                await self._emit_event(event)

                # Log role transition
                logger.info(
                    "Role transition: unregistration",
                    extra={
                        "service_name": service_name,
                        "instance_id": instance_id,
                        "old_role": removed_instance.role.value,
                        "new_role": None,
                        "resource_id": resource_id,
                        "event_type": "unregistration",
                    },
                )

            # Clean up active instance tracking if needed
            if removed_instance.role == ServiceRole.ACTIVE:
                resource_id = self._get_resource_id_from_metadata(removed_instance.metadata)
                if resource_id and resource_id in self._resource_active_instances:
                    stored_service, stored_instance = self._resource_active_instances[resource_id]
                    if stored_service == service_name and stored_instance == instance_id:
                        del self._resource_active_instances[resource_id]
                        logger.info(
                            "Removed active instance tracking for resource",
                            extra={
                                "service_name": service_name,
                                "instance_id": instance_id,
                                "resource_id": resource_id,
                            },
                        )

            # Remove service if no more instances
            if service.instance_count == 0:
                del self._services[service_name]
                logger.info(
                    "Removed service with no remaining instances",
                    extra={"service_name": service_name},
                )

            logger.info(
                "Service instance unregistered",
                extra={
                    "service_name": service_name,
                    "instance_id": instance_id,
                    "remaining_instances": (
                        service.instance_count if service_name in self._services else 0
                    ),
                },
            )

    async def check_health(self, timeout_seconds: int = 30) -> dict[str, Any]:
        """Check the health of all registered services.

        Args:
            timeout_seconds: Maximum seconds since last heartbeat to consider healthy

        Returns:
            Dictionary containing health status information
        """
        async with self._lock:
            total_services = len(self._services)
            total_instances = 0
            healthy_instances = 0
            unhealthy_services = []

            for service in self._services.values():
                instances = list(service.instances.values())
                total_instances += len(instances)

                healthy = [inst for inst in instances if inst.is_healthy(timeout_seconds)]
                healthy_instances += len(healthy)

                if len(healthy) < len(instances):
                    unhealthy_services.append(
                        {
                            "service_name": service.name,
                            "total_instances": len(instances),
                            "healthy_instances": len(healthy),
                        }
                    )

            health_status = {
                "total_services": total_services,
                "total_instances": total_instances,
                "healthy_instances": healthy_instances,
                "unhealthy_services": unhealthy_services,
                "health_percentage": (
                    (healthy_instances / total_instances * 100) if total_instances > 0 else 0
                ),
            }

            logger.info(
                "Health check completed",
                extra=health_status,
            )

            return health_status

    async def get_healthy_instances(
        self, service_name: str, timeout_seconds: int = 30
    ) -> list[ServiceInstance]:
        """Get all healthy instances for a specific service.

        Args:
            service_name: Name of the service to get instances for
            timeout_seconds: Maximum seconds since last heartbeat to consider healthy

        Returns:
            List of healthy ServiceInstance objects

        Raises:
            NotFoundError: If service does not exist
        """
        async with self._lock:
            if service_name not in self._services:
                raise NotFoundError(
                    resource_type="Service",
                    resource_id=service_name,
                )

            service = self._services[service_name]
            healthy_instances: list[ServiceInstance] = service.get_healthy_instances(
                timeout_seconds
            )

            logger.debug(
                "Retrieved healthy instances",
                extra={
                    "service_name": service_name,
                    "healthy_count": len(healthy_instances),
                    "total_count": service.instance_count,
                },
            )

            return healthy_instances

    async def update_instance_status(
        self, service_name: str, instance_id: str, status: ServiceStatus
    ) -> None:
        """Update the status of a specific service instance.

        Args:
            service_name: Name of the service
            instance_id: ID of the instance to update
            status: New status for the instance

        Raises:
            NotFoundError: If service or instance does not exist
        """
        async with self._lock:
            if service_name not in self._services:
                raise NotFoundError(
                    resource_type="Service",
                    resource_id=service_name,
                )

            service = self._services[service_name]
            instance = service.get_instance(instance_id)

            if instance is None:
                raise NotFoundError(
                    resource_type="ServiceInstance",
                    resource_id=f"{service_name}/{instance_id}",
                )

            old_status = instance.status
            instance.status = status

            logger.info(
                "Updated instance status",
                extra={
                    "service_name": service_name,
                    "instance_id": instance_id,
                    "old_status": old_status.value,
                    "new_status": status.value,
                },
            )

            # Notify listeners about status change (will be implemented in subtask 2.3)
            await self._notify_status_change(service_name, instance_id, old_status, status)

    def subscribe_to_events(self, event_type: ServiceEventType | None, handler: Any) -> None:
        """Subscribe to service registry events.

        Args:
            event_type: Type of events to subscribe to, or None for all events
            handler: Async callback function to handle events
        """
        self._event_handlers.append((event_type, handler))
        logger.debug(
            "Event handler subscribed",
            extra={
                "event_type": event_type.value if event_type else "all",
                "handler": handler.__name__ if hasattr(handler, "__name__") else str(handler),
            },
        )

    def unsubscribe_from_events(self, handler: Any) -> None:
        """Unsubscribe from service registry events.

        Args:
            handler: The handler function to remove
        """
        self._event_handlers = [
            (evt_type, h) for evt_type, h in self._event_handlers if h != handler
        ]

    async def _notify_status_change(
        self,
        service_name: str,
        instance_id: str,
        old_status: ServiceStatus,
        new_status: ServiceStatus,
    ) -> None:
        """Notify listeners about instance status change.

        Args:
            service_name: Name of the service
            instance_id: ID of the instance that changed
            old_status: Previous status
            new_status: New status
        """
        event = InstanceStatusChangedEvent(
            service_name=service_name,
            instance_id=instance_id,
            timestamp=datetime.now(UTC),
            old_status=old_status,
            new_status=new_status,
            metadata={
                "old_status": old_status.value,
                "new_status": new_status.value,
            },
        )

        await self._emit_event(event)

    async def _emit_event(self, event: ServiceEvent) -> None:
        """Emit an event to all registered handlers.

        Args:
            event: The event to emit
        """
        tasks = []
        for event_type, handler in self._event_handlers:
            # Check if handler should receive this event
            if event_type is None or event_type == event.event_type:
                try:
                    # Support both sync and async handlers
                    if asyncio.iscoroutinefunction(handler):
                        tasks.append(handler(event))
                    else:
                        # Run sync handler in executor to avoid blocking
                        loop = asyncio.get_event_loop()
                        tasks.append(loop.run_in_executor(None, handler, event))
                except Exception as e:
                    logger.error(
                        "Error in event handler",
                        exc_info=e,
                        extra={
                            "event_type": event.event_type.value,
                            "handler": (
                                handler.__name__ if hasattr(handler, "__name__") else str(handler)
                            ),
                        },
                    )

        # Execute all handlers concurrently
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def get_active_instance_for_resource(self, resource_id: str) -> tuple[str, str] | None:
        """Get the active instance for a specific resource.

        Args:
            resource_id: ID of the resource to check

        Returns:
            Tuple of (service_name, instance_id) if an active instance exists, None otherwise
        """
        async with self._lock:
            return self._resource_active_instances.get(resource_id)

    async def get_instances_by_role(
        self, service_name: str, role: ServiceRole
    ) -> list[ServiceInstance]:
        """Get all instances of a service with a specific role.

        Args:
            service_name: Name of the service
            role: Role to filter by

        Returns:
            List of ServiceInstance objects with the specified role

        Raises:
            NotFoundError: If service does not exist
        """
        async with self._lock:
            if service_name not in self._services:
                raise NotFoundError(
                    resource_type="Service",
                    resource_id=service_name,
                )

            service = self._services[service_name]
            return [instance for instance in service.instances.values() if instance.role == role]

    @staticmethod
    def _get_resource_id_from_metadata(metadata: dict[str, Any] | None) -> str | None:
        """Extract resource_id from metadata dictionary.

        Args:
            metadata: Metadata dictionary that may contain resource_id

        Returns:
            The resource_id if present, None otherwise
        """
        return metadata.get("resource_id") if metadata else None
