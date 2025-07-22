"""NATS handler for routing service requests."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from ipc_router.application.error_handling import RetryConfig, with_retry
from ipc_router.application.models.routing_models import RouteRequest, RouteResponse
from ipc_router.domain.exceptions import ServiceUnavailableError
from ipc_router.infrastructure.logging import get_logger

if TYPE_CHECKING:
    from ipc_router.application.services.routing_service import RoutingService
    from ipc_router.infrastructure.messaging.nats_client import NATSClient

logger = get_logger(__name__)


class RouteRequestHandler:
    """Handler for routing service requests via NATS.

    This handler listens for routing requests, determines the target instance,
    and forwards the request to the selected instance.
    """

    def __init__(
        self,
        nats_client: NATSClient,
        routing_service: RoutingService,
        route_subject: str = "ipc.route.request",
    ) -> None:
        """Initialize the route request handler.

        Args:
            nats_client: NATS client for messaging
            routing_service: Service for routing logic
            route_subject: Subject to listen for routing requests
        """
        self._nats = nats_client
        self._routing_service = routing_service
        self._route_subject = route_subject
        self._retry_config = RetryConfig(max_attempts=3, initial_delay=0.5)
        # Track active requests for correlation
        self._active_requests: dict[str, asyncio.Future[Any]] = {}
        logger.info(
            "RouteRequestHandler initialized",
            extra={"route_subject": route_subject},
        )

    async def start(self) -> None:
        """Start listening for routing requests."""
        await self._nats.subscribe(
            self._route_subject,
            callback=self._handle_route_request,
        )
        logger.info(
            "Started listening for route requests",
            extra={"subject": self._route_subject},
        )

    async def stop(self) -> None:
        """Stop listening for routing requests."""
        await self._nats.unsubscribe(self._route_subject)
        # Cancel any pending requests
        for future in self._active_requests.values():
            if not future.done():
                future.cancel()
        self._active_requests.clear()
        logger.info("Stopped route request handler")

    async def _handle_route_request(self, data: Any, reply_subject: str | None) -> None:
        """Handle incoming routing request.

        Args:
            data: Deserialized request data
            reply_subject: Subject to send response to
        """
        start_time = time.time()

        try:
            # Parse request
            route_request = RouteRequest(**data)

            logger.debug(
                "Received route request",
                extra={
                    "service_name": route_request.service_name,
                    "method": route_request.method,
                    "trace_id": route_request.trace_id,
                },
            )

            # Get routing decision
            route_response = await self._routing_service.route_request(route_request)

            if not route_response.success:
                # Send error response
                await self._send_response(reply_subject or "", route_response)
                return

            # Forward request to selected instance
            await self._forward_request(
                route_request,
                route_response.instance_id,
                reply_subject or "",
            )

        except Exception as e:
            logger.error(
                "Error handling route request",
                exc_info=e,
                extra={
                    "subject": self._route_subject,
                    "reply": reply_subject,
                },
            )

            # Send error response
            error_response = RouteResponse(
                success=False,
                error={
                    "type": type(e).__name__,
                    "message": str(e),
                    "code": 500,
                },
                trace_id=data.get("trace_id", "unknown") if "data" in locals() else "unknown",
                duration_ms=(time.time() - start_time) * 1000,
            )

            if reply_subject:
                await self._send_response(reply_subject, error_response)

    async def _forward_request(
        self,
        request: RouteRequest,
        instance_id: str,
        reply_to: str,
    ) -> None:
        """Forward request to the selected instance.

        Args:
            request: The routing request
            instance_id: ID of the selected instance
            reply_to: Subject to send the response to
        """
        # Build instance-specific subject
        instance_subject = f"ipc.instance.{instance_id}.inbox"

        logger.debug(
            "Forwarding request to instance",
            extra={
                "instance_id": instance_id,
                "subject": instance_subject,
                "method": request.method,
                "trace_id": request.trace_id,
            },
        )

        # Create correlation ID for tracking
        correlation_id = f"{request.trace_id}:{instance_id}:{time.time()}"

        # Prepare forwarded message
        forward_msg = {
            "method": request.method,
            "params": request.params,
            "trace_id": request.trace_id,
            "correlation_id": correlation_id,
        }

        try:
            # Track timing for this forward operation
            forward_start = time.time()

            # Use retry mechanism for forwarding
            @with_retry(self._retry_config)
            async def send_and_wait() -> Any:
                # Create future for response tracking
                response_future: asyncio.Future[Any] = asyncio.Future()
                self._active_requests[correlation_id] = response_future

                try:
                    # Subscribe to response with correlation
                    response_subject = f"ipc.response.{correlation_id}"

                    async def handle_response(data: Any, reply_subject: str | None) -> None:
                        """Handle response from instance."""
                        try:
                            if not response_future.done():
                                response_future.set_result(data)
                        except Exception as e:
                            if not response_future.done():
                                response_future.set_exception(e)

                    # Subscribe to response
                    await self._nats.subscribe(
                        response_subject,
                        callback=handle_response,
                    )

                    # Send request to instance
                    await self._nats.publish(
                        instance_subject,
                        forward_msg,
                        reply=response_subject,
                    )

                    # Wait for response with timeout
                    try:
                        response_data = await asyncio.wait_for(
                            response_future,
                            timeout=request.timeout,
                        )

                        # Send response back to original caller
                        response = RouteResponse(
                            success=True,
                            result=response_data.get("result"),
                            instance_id=instance_id,
                            trace_id=request.trace_id,
                            duration_ms=(time.time() - forward_start) * 1000,
                        )

                        await self._send_response(reply_to, response)

                    except TimeoutError as e:
                        raise ServiceUnavailableError(
                            service_name=request.service_name,
                            reason=f"Instance {instance_id} did not respond within {request.timeout}s",
                        ) from e

                    finally:
                        # Cleanup
                        await self._nats.unsubscribe(response_subject)
                        self._active_requests.pop(correlation_id, None)

                except Exception:
                    # Remove from active requests on error
                    self._active_requests.pop(correlation_id, None)
                    raise

            await send_and_wait()

        except Exception as e:
            logger.error(
                "Failed to forward request to instance",
                exc_info=e,
                extra={
                    "instance_id": instance_id,
                    "trace_id": request.trace_id,
                },
            )

            # Send error response
            error_response = RouteResponse(
                success=False,
                error={
                    "type": (
                        "InstanceTimeoutError"
                        if isinstance(e, ServiceUnavailableError)
                        else type(e).__name__
                    ),
                    "message": str(e),
                    "code": 504 if isinstance(e, ServiceUnavailableError) else 500,
                },
                instance_id=instance_id,
                trace_id=request.trace_id,
                duration_ms=(time.time() - forward_start) * 1000,
            )

            await self._send_response(reply_to, error_response)

    async def _send_response(self, reply_to: str, response: RouteResponse) -> None:
        """Send response back to the requester.

        Args:
            reply_to: Subject to send response to
            response: Response to send
        """
        if not reply_to:
            logger.warning("No reply subject provided, cannot send response")
            return

        try:
            # Convert to dict and serialize datetime to ISO format string
            response_data = response.model_dump(mode="json")
            await self._nats.publish(reply_to, response_data)

            logger.debug(
                "Sent route response",
                extra={
                    "reply_to": reply_to,
                    "success": response.success,
                    "trace_id": response.trace_id,
                },
            )

        except Exception as e:
            logger.error(
                "Failed to send route response",
                exc_info=e,
                extra={
                    "reply_to": reply_to,
                    "trace_id": response.trace_id,
                },
            )
