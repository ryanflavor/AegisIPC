"""Resource-aware routing service extending base routing with resource support.

This module provides routing that considers resource ownership for precise
request delivery to the instance managing a specific resource.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from ipc_router.application.models.routing_models import RouteRequest, RouteResponse
from ipc_router.domain.exceptions import (
    NotFoundError,
)
from ipc_router.domain.interfaces.load_balancer import LoadBalancer
from ipc_router.infrastructure.logging import get_logger

from .routing_service import RoutingService

if TYPE_CHECKING:
    from ipc_router.application.services.resource_registry import ResourceRegistry

logger = get_logger(__name__)


class ResourceAwareRoutingService(RoutingService):
    """Routing service with resource-based routing capabilities.

    This service extends the base RoutingService to support routing requests
    directly to instances that own specific resources.
    """

    def __init__(
        self,
        resource_registry: ResourceRegistry,
        load_balancer: LoadBalancer | None = None,
    ) -> None:
        """Initialize the resource-aware routing service.

        Args:
            resource_registry: Registry that includes resource management
            load_balancer: Load balancer strategy for non-resource routing
        """
        # ResourceRegistry extends ServiceRegistry, so we can use it for both
        super().__init__(resource_registry, load_balancer)
        self._resource_registry = resource_registry
        logger.info("ResourceAwareRoutingService initialized")

    async def route_request(self, request: RouteRequest) -> RouteResponse:
        """Route a request considering resource ownership.

        If a resource_id is provided, routes directly to the owning instance.
        Otherwise, falls back to standard load-balanced routing.

        Args:
            request: The routing request with optional resource_id

        Returns:
            RouteResponse with routing decision
        """
        start_time = time.time()

        # Check if this is a resource-based routing request
        if request.resource_id:
            return await self._route_to_resource_owner(request, start_time)

        # Fall back to standard routing
        return await super().route_request(request)

    async def _route_to_resource_owner(
        self, request: RouteRequest, start_time: float
    ) -> RouteResponse:
        """Route request to the instance owning the specified resource.

        Args:
            request: Routing request with resource_id
            start_time: Request start time for duration calculation

        Returns:
            RouteResponse with the resource owner instance
        """
        try:
            # Get resource owner - resource_id must be non-None at this point
            assert request.resource_id is not None  # type guard
            owner_instance_id = await self._resource_registry.get_resource_owner(
                request.resource_id
            )

            if owner_instance_id is None:
                duration_ms = (time.time() - start_time) * 1000
                logger.warning(
                    "Resource not found for routing",
                    extra={
                        "resource_id": request.resource_id,
                        "service_name": request.service_name,
                        "trace_id": request.trace_id,
                    },
                )

                return RouteResponse(
                    success=False,
                    error={
                        "type": "ResourceNotFoundError",
                        "message": f"Resource '{request.resource_id}' not found",
                        "code": 404,
                        "resource_id": request.resource_id,
                    },
                    trace_id=request.trace_id,
                    duration_ms=duration_ms,
                )

            # Verify the instance is still healthy
            try:
                service_info = await self._registry.get_service(request.service_name)
                instance_healthy = False

                for instance in service_info.instances:
                    # Handle both enum and string status values
                    status_value = (
                        instance.status
                        if isinstance(instance.status, str)
                        else instance.status.value
                    )
                    if (
                        instance.instance_id == owner_instance_id
                        and status_value.lower() == "online"
                    ):
                        instance_healthy = True
                        break

                if not instance_healthy:
                    duration_ms = (time.time() - start_time) * 1000
                    logger.warning(
                        "Resource owner instance is not healthy",
                        extra={
                            "resource_id": request.resource_id,
                            "owner_instance_id": owner_instance_id,
                            "service_name": request.service_name,
                            "trace_id": request.trace_id,
                        },
                    )

                    return RouteResponse(
                        success=False,
                        error={
                            "type": "ServiceUnavailableError",
                            "message": (
                                f"Instance '{owner_instance_id}' owning resource "
                                f"'{request.resource_id}' is not healthy"
                            ),
                            "code": 503,
                            "resource_id": request.resource_id,
                            "owner_instance_id": owner_instance_id,
                        },
                        trace_id=request.trace_id,
                        duration_ms=duration_ms,
                    )

            except NotFoundError:
                # Service doesn't exist, but we found the resource
                # This is an inconsistent state that should trigger cleanup
                duration_ms = (time.time() - start_time) * 1000
                logger.error(
                    "Resource exists but service not found - inconsistent state",
                    extra={
                        "resource_id": request.resource_id,
                        "owner_instance_id": owner_instance_id,
                        "service_name": request.service_name,
                        "trace_id": request.trace_id,
                    },
                )

                # Attempt to clean up the orphaned resource
                try:
                    await self._resource_registry.release_resource(
                        request.resource_id, owner_instance_id
                    )
                    logger.info(
                        "Cleaned up orphaned resource",
                        extra={
                            "resource_id": request.resource_id,
                            "owner_instance_id": owner_instance_id,
                        },
                    )
                except Exception as cleanup_error:
                    logger.error(
                        "Failed to clean up orphaned resource",
                        exc_info=cleanup_error,
                        extra={
                            "resource_id": request.resource_id,
                            "owner_instance_id": owner_instance_id,
                        },
                    )

                return RouteResponse(
                    success=False,
                    error={
                        "type": "ServiceNotFoundError",
                        "message": (
                            f"Service '{request.service_name}' not found. "
                            f"Resource '{request.resource_id}' has been orphaned."
                        ),
                        "code": 404,
                        "resource_id": request.resource_id,
                        "service_name": request.service_name,
                    },
                    trace_id=request.trace_id,
                    duration_ms=duration_ms,
                )

            # Log successful resource-based routing
            duration_ms = (time.time() - start_time) * 1000
            logger.info(
                "Route request to resource owner",
                extra={
                    "service_name": request.service_name,
                    "resource_id": request.resource_id,
                    "instance_id": owner_instance_id,
                    "method": request.method,
                    "trace_id": request.trace_id,
                    "routing_time_ms": duration_ms,
                    "routing_type": "resource-based",
                },
            )

            return RouteResponse(
                success=True,
                instance_id=owner_instance_id,
                trace_id=request.trace_id,
                duration_ms=duration_ms,
            )

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            logger.error(
                "Unexpected error during resource-based routing",
                exc_info=e,
                extra={
                    "service_name": request.service_name,
                    "resource_id": request.resource_id,
                    "trace_id": request.trace_id,
                },
            )

            return RouteResponse(
                success=False,
                error={
                    "type": type(e).__name__,
                    "message": str(e),
                    "code": 500,
                },
                trace_id=request.trace_id,
                duration_ms=duration_ms,
            )

    async def get_routing_stats(self) -> dict[str, Any]:
        """Get routing statistics including resource routing metrics.

        Returns:
            Dictionary with routing statistics
        """
        # TODO: Implement routing statistics tracking
        return {
            "resource_routing_enabled": True,
            "load_balancer": type(self._load_balancer).__name__,
        }
