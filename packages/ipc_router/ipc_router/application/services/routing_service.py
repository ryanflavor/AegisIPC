"""Routing service for load-balanced service calls."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from ipc_router.application.models.routing_models import RouteRequest, RouteResponse
from ipc_router.domain.exceptions import NotFoundError, ServiceUnavailableError
from ipc_router.domain.interfaces.load_balancer import LoadBalancer
from ipc_router.domain.strategies.round_robin import RoundRobinLoadBalancer
from ipc_router.infrastructure.logging import get_logger

if TYPE_CHECKING:
    from ipc_router.application.services.service_registry import ServiceRegistry

logger = get_logger(__name__)


class RoutingService:
    """Application service for routing requests to service instances.

    This service handles the routing logic, including service discovery,
    load balancing, and request forwarding.
    """

    def __init__(
        self,
        service_registry: ServiceRegistry,
        load_balancer: LoadBalancer | None = None,
    ) -> None:
        """Initialize the routing service.

        Args:
            service_registry: Service registry for discovering instances
            load_balancer: Load balancer strategy (defaults to RoundRobin)
        """
        self._registry = service_registry
        self._load_balancer = load_balancer or RoundRobinLoadBalancer()
        logger.info(
            "RoutingService initialized",
            extra={
                "load_balancer": type(self._load_balancer).__name__,
            },
        )

    async def route_request(self, request: RouteRequest) -> RouteResponse:
        """Route a request to an available service instance.

        Args:
            request: The routing request containing service name and method

        Returns:
            RouteResponse with the result or error details

        Raises:
            NotFoundError: If the service doesn't exist
            ServiceUnavailableError: If no healthy instances are available
        """
        start_time = time.time()

        try:
            # Get healthy instances for the service
            instances = await self._registry.get_healthy_instances(request.service_name)

            if not instances:
                logger.warning(
                    "No healthy instances available for routing",
                    extra={
                        "service_name": request.service_name,
                        "trace_id": request.trace_id,
                    },
                )
                raise ServiceUnavailableError(
                    service_name=request.service_name,
                    message="No healthy instances available for service",
                )

            # Select instance using load balancer
            selected_instance = self._load_balancer.select_instance(instances, request.service_name)

            if selected_instance is None:
                logger.error(
                    "Load balancer returned no instance despite healthy instances",
                    extra={
                        "service_name": request.service_name,
                        "healthy_count": len(instances),
                        "trace_id": request.trace_id,
                    },
                )
                raise ServiceUnavailableError(
                    service_name=request.service_name,
                    message="Failed to select instance for routing",
                )

            # Log routing decision
            duration_ms = (time.time() - start_time) * 1000
            logger.info(
                "Route request to instance",
                extra={
                    "service_name": request.service_name,
                    "instance_id": selected_instance.instance_id,
                    "method": request.method,
                    "trace_id": request.trace_id,
                    "available_instances": len(instances),
                    "routing_time_ms": duration_ms,
                },
            )

            # Return routing decision (actual forwarding will be handled by NATS handler)
            return RouteResponse(
                success=True,
                instance_id=selected_instance.instance_id,
                trace_id=request.trace_id,
                duration_ms=duration_ms,
            )

        except NotFoundError:
            duration_ms = (time.time() - start_time) * 1000
            logger.error(
                "Service not found for routing",
                extra={
                    "service_name": request.service_name,
                    "trace_id": request.trace_id,
                },
            )
            return RouteResponse(
                success=False,
                error={
                    "type": "NotFoundError",
                    "message": f"Service '{request.service_name}' not found",
                    "code": 404,
                },
                trace_id=request.trace_id,
                duration_ms=duration_ms,
            )

        except ServiceUnavailableError as e:
            duration_ms = (time.time() - start_time) * 1000
            return RouteResponse(
                success=False,
                error={
                    "type": "ServiceUnavailableError",
                    "message": str(e),
                    "code": 503,
                },
                trace_id=request.trace_id,
                duration_ms=duration_ms,
            )

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            logger.error(
                "Unexpected error during routing",
                exc_info=e,
                extra={
                    "service_name": request.service_name,
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

    def reset_load_balancer(self, service_name: str) -> None:
        """Reset load balancer state for a specific service.

        Args:
            service_name: Name of the service to reset
        """
        self._load_balancer.reset(service_name)
        logger.info(
            "Reset load balancer for service",
            extra={"service_name": service_name},
        )
