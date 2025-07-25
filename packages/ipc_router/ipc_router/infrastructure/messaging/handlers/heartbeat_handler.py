"""Heartbeat handler for NATS messaging."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from ipc_router.domain.exceptions import NotFoundError, ValidationError
from ipc_router.infrastructure.logging import get_logger

# Import heartbeat models for Story 2.1
try:
    from ipc_router.application.models import HeartbeatRequest, HeartbeatResponse
except ImportError:
    HeartbeatRequest = None
    HeartbeatResponse = None

# Import metrics for heartbeat monitoring
try:
    from prometheus_client import Counter, Histogram

    heartbeats_received_total = Counter(
        "ipc_heartbeats_received_total",
        "Total number of heartbeats received",
        ["service_name", "instance_id", "status"],
    )

    heartbeat_processing_duration = Histogram(
        "ipc_heartbeat_processing_duration_seconds",
        "Heartbeat processing duration in seconds",
        ["service_name", "status"],
    )
except ImportError:
    heartbeats_received_total = None
    heartbeat_processing_duration = None

if TYPE_CHECKING:
    from ipc_router.application.services import ServiceRegistry
    from ipc_router.infrastructure.messaging import NATSClient

logger = get_logger(__name__)


class HeartbeatHandler:
    """Handles heartbeat updates via NATS."""

    def __init__(self, nats_client: NATSClient, service_registry: ServiceRegistry) -> None:
        """Initialize heartbeat handler.

        Args:
            nats_client: NATS client for messaging
            service_registry: Service registry for updating heartbeats
        """
        self.nats_client = nats_client
        self.service_registry = service_registry
        self._subscription: Any | None = None
        self._subject = "ipc.service.heartbeat"

    async def start(self) -> None:
        """Start listening for heartbeat messages."""
        logger.info("Starting heartbeat handler", extra={"subject": self._subject})
        self._subscription = await self.nats_client.subscribe(
            self._subject, self._handle_heartbeat_request
        )

    async def stop(self) -> None:
        """Stop listening for heartbeat messages."""
        if self._subscription:
            await self.nats_client.unsubscribe(self._subscription)
            self._subscription = None
        logger.info("Stopped heartbeat handler")

    async def _handle_heartbeat_request(
        self, heartbeat_data: dict[str, Any], reply: str | None = None
    ) -> None:
        """Handle incoming heartbeat request.

        Args:
            heartbeat_data: Unpacked heartbeat data dictionary
            reply: Optional reply subject
        """
        trace_id = None
        response: dict[str, Any] = {}
        start_time = datetime.now(UTC).timestamp()

        try:
            # Data is already unpacked by NATSClient
            trace_id = heartbeat_data.get("trace_id", "heartbeat-unknown")

            # Use HeartbeatRequest model for validation if available
            if HeartbeatRequest:
                try:
                    heartbeat_request = HeartbeatRequest(**heartbeat_data)
                    service_name = heartbeat_request.service_name
                    instance_id = heartbeat_request.instance_id
                    status = heartbeat_request.status
                except Exception as e:
                    raise ValidationError(f"Invalid heartbeat request: {e}") from e
            else:
                # Fallback to manual validation
                service_name = heartbeat_data.get("service_name")
                instance_id = heartbeat_data.get("instance_id")
                status = heartbeat_data.get("status", "healthy")

                if not service_name or not instance_id:
                    raise ValidationError("Missing required fields: service_name and instance_id")

            logger.debug(
                "Received heartbeat request",
                extra={
                    "trace_id": trace_id,
                    "service_name": service_name,
                    "instance_id": instance_id,
                    "status": status,
                },
            )

            # Update heartbeat
            await self.service_registry.update_heartbeat(service_name, instance_id)

            # Record metrics
            if heartbeats_received_total:
                heartbeats_received_total.labels(
                    service_name=service_name,
                    instance_id=instance_id,
                    status=status,
                ).inc()

            if heartbeat_processing_duration:
                processing_time = datetime.now(UTC).timestamp() - start_time
                heartbeat_processing_duration.labels(
                    service_name=service_name,
                    status="success",
                ).observe(processing_time)

            # Send success response
            response = {
                "envelope": {
                    "success": True,
                    "message": f"Heartbeat updated for {service_name}/{instance_id}",
                    "timestamp": datetime.now(UTC).isoformat(),
                },
                "data": {
                    "service_name": service_name,
                    "instance_id": instance_id,
                    "updated_at": datetime.now(UTC).isoformat(),
                },
            }

            logger.info(
                "Heartbeat updated successfully",
                extra={
                    "trace_id": trace_id,
                    "service_name": service_name,
                    "instance_id": instance_id,
                },
            )

        except NotFoundError as e:
            # Service or instance not found
            response = {
                "envelope": {
                    "success": False,
                    "error_code": "NOT_FOUND",
                    "message": str(e),
                    "timestamp": datetime.now(UTC).isoformat(),
                },
                "data": {},
            }

            logger.warning(
                "Heartbeat failed - not found",
                extra={
                    "trace_id": trace_id,
                    "error": str(e),
                },
            )

            # Record failure metric
            if heartbeat_processing_duration:
                processing_time = datetime.now(UTC).timestamp() - start_time
                heartbeat_processing_duration.labels(
                    service_name="unknown",
                    status="not_found",
                ).observe(processing_time)

        except ValidationError as e:
            # Invalid heartbeat data
            response = {
                "envelope": {
                    "success": False,
                    "error_code": "VALIDATION_ERROR",
                    "message": str(e),
                    "timestamp": datetime.now(UTC).isoformat(),
                },
                "data": {},
            }

            logger.error(
                "Heartbeat validation failed",
                extra={
                    "trace_id": trace_id,
                    "error": str(e),
                },
            )

            # Record failure metric
            if heartbeat_processing_duration:
                processing_time = datetime.now(UTC).timestamp() - start_time
                heartbeat_processing_duration.labels(
                    service_name="unknown",
                    status="validation_error",
                ).observe(processing_time)

        except Exception as e:
            # Unexpected error
            response = {
                "envelope": {
                    "success": False,
                    "error_code": "INTERNAL_ERROR",
                    "message": f"Failed to process heartbeat: {e}",
                    "timestamp": datetime.now(UTC).isoformat(),
                },
                "data": {},
            }

            logger.error(
                "Unexpected error processing heartbeat",
                extra={
                    "trace_id": trace_id,
                    "error": str(e),
                },
                exc_info=e,
            )

        # Send response if reply subject exists
        if reply and response:
            try:
                await self.nats_client.publish(reply, response)
            except Exception as e:
                logger.error(
                    "Failed to send heartbeat response",
                    extra={
                        "trace_id": trace_id,
                        "error": str(e),
                    },
                )

    def _create_queue_group(self) -> str:
        """Create queue group name for load balancing.

        Returns:
            Queue group name
        """
        return "ipc.heartbeat.handlers"
