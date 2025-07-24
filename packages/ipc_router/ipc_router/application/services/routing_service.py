"""Routing service for load-balanced service calls."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from ipc_router.application.models.routing_models import RouteRequest, RouteResponse
from ipc_router.domain.entities.message import Message, MessageState
from ipc_router.domain.exceptions import (
    NotFoundError,
    ServiceUnavailableError,
)
from ipc_router.domain.interfaces.load_balancer import LoadBalancer
from ipc_router.domain.strategies.round_robin import RoundRobinLoadBalancer
from ipc_router.infrastructure.logging import get_logger

if TYPE_CHECKING:
    from ipc_router.application.services.acknowledgment_service import AcknowledgmentService
    from ipc_router.application.services.message_store_service import MessageStoreService
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
        message_store: MessageStoreService | None = None,
        acknowledgment_service: AcknowledgmentService | None = None,
        load_balancer: LoadBalancer | None = None,
    ) -> None:
        """Initialize the routing service.

        Args:
            service_registry: Service registry for discovering instances
            message_store: Message store for deduplication (optional for backward compatibility)
            acknowledgment_service: Service for managing acknowledgments (optional for backward compatibility)
            load_balancer: Load balancer strategy (defaults to RoundRobin)
        """
        self._registry = service_registry
        self._message_store = message_store
        self._acknowledgment_service = acknowledgment_service
        self._load_balancer = load_balancer or RoundRobinLoadBalancer()
        logger.info(
            "RoutingService initialized",
            extra={
                "load_balancer": type(self._load_balancer).__name__,
                "reliable_delivery": bool(self._message_store and self._acknowledgment_service),
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

        # Handle reliable delivery if message_id is provided and services are configured
        if request.message_id and self._message_store and self._acknowledgment_service:
            # Check for duplicate messages
            message_id_str = str(request.message_id)
            existing_message = await self._message_store.get_message(message_id_str)
            if existing_message and existing_message.state == MessageState.ACKNOWLEDGED:
                logger.info(
                    "Duplicate message already acknowledged",
                    extra={
                        "message_id": str(request.message_id),
                        "service_name": request.service_name,
                        "trace_id": request.trace_id,
                    },
                )
                # Return success for idempotent handling
                return RouteResponse(
                    success=True,
                    message_id=request.message_id,
                    trace_id=request.trace_id,
                    duration_ms=(time.time() - start_time) * 1000,
                    error={
                        "type": "DuplicateMessage",
                        "message": "Message already processed",
                        "code": 200,
                    },
                )
            else:
                # Store new message
                message = Message(
                    message_id=str(request.message_id),
                    service_name=request.service_name,
                    method=request.method,
                    params=request.params,
                    trace_id=request.trace_id,
                    state=MessageState.PENDING,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                    ack_deadline=datetime.now(UTC) + timedelta(seconds=request.timeout),
                )
                await self._message_store.store_message(message)

        try:
            # Get healthy instances for the service
            instances = await self._registry.get_healthy_instances(request.service_name)

            # Filter out excluded instances if provided
            if request.excluded_instances:
                instances = [
                    inst for inst in instances if inst.instance_id not in request.excluded_instances
                ]

                logger.debug(
                    "Filtered excluded instances",
                    extra={
                        "service_name": request.service_name,
                        "total_instances": len(instances) + len(request.excluded_instances),
                        "excluded_count": len(request.excluded_instances),
                        "available_instances": len(instances),
                        "trace_id": request.trace_id,
                    },
                )

            if not instances:
                logger.warning(
                    "No healthy instances available for routing",
                    extra={
                        "service_name": request.service_name,
                        "trace_id": request.trace_id,
                        "excluded_instances": request.excluded_instances or [],
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
                message_id=request.message_id,
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
                message_id=request.message_id,
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
                message_id=request.message_id,
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
                message_id=request.message_id,
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

    async def acknowledge_message(self, message_id: UUID) -> bool:
        """Acknowledge a message after successful processing.

        Args:
            message_id: The ID of the message to acknowledge

        Returns:
            True if acknowledgment was successful, False otherwise
        """
        if not self._acknowledgment_service or not self._message_store:
            logger.warning(
                "Acknowledgment requested but reliable delivery not configured",
                extra={"message_id": str(message_id)},
            )
            return False

        try:
            # Get the message
            message_id_str = str(message_id)
            message = await self._message_store.get_message(message_id_str)
            if not message:
                logger.warning(
                    "Message not found for acknowledgment",
                    extra={"message_id": message_id_str},
                )
                return False

            # Send acknowledgment
            await self._acknowledgment_service.send_ack(
                message_id=message_id_str,
                service_name=message.service_name,
                instance_id="routing-service",
                success=True,
                processing_time_ms=0.0,
                trace_id=message.trace_id,
            )

            # Update message state
            await self._message_store.update_message_state(
                message_id_str, MessageState.ACKNOWLEDGED.value
            )

            logger.info(
                "Message acknowledged successfully",
                extra={
                    "message_id": str(message_id),
                    "service_name": message.service_name,
                },
            )
            return True

        except Exception as e:
            logger.error(
                "Failed to acknowledge message",
                exc_info=e,
                extra={"message_id": str(message_id)},
            )
            return False

    async def get_pending_messages(self, service_name: str | None = None) -> list[Message]:
        """Get pending messages that need retry.

        Args:
            service_name: Optional service name to filter messages

        Returns:
            List of pending messages
        """
        if not self._message_store:
            return []

        try:
            return await self._message_store.get_pending_messages_for_retry(service_name)  # type: ignore[no-any-return]
        except Exception as e:
            logger.error(
                "Failed to get pending messages",
                exc_info=e,
                extra={"service_name": service_name},
            )
            return []
