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

from ...domain.entities import Service, ServiceInstance
from ...domain.enums import ServiceStatus
from ...domain.exceptions import DuplicateServiceInstanceError, NotFoundError
from ...infrastructure.logging import get_logger

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

            # Create and add new instance
            now = datetime.now(UTC)
            instance = ServiceInstance(
                instance_id=instance_id,
                service_name=service_name,
                status=ServiceStatus.ONLINE,
                registered_at=now,
                last_heartbeat=now,
                metadata=request.metadata,
            )

            service.add_instance(instance)

            logger.info(
                "Service instance registered successfully",
                extra={
                    "service_name": service_name,
                    "instance_id": instance_id,
                    "instance_count": service.instance_count,
                    "metadata": request.metadata,
                },
            )

            return ServiceRegistrationResponse(
                success=True,
                service_name=service_name,
                instance_id=instance_id,
                registered_at=now,
                message="Service instance registered successfully",
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
