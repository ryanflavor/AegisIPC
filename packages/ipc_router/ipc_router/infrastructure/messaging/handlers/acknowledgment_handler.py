"""Handler for processing acknowledgment messages."""

from __future__ import annotations

from typing import Any

from ipc_router.application.models.acknowledgment_models import (
    AcknowledgmentRequest,
    AcknowledgmentResponse,
)
from ipc_router.infrastructure.logging import get_logger
from ipc_router.infrastructure.messaging.nats_client import NATSClient

logger = get_logger(__name__)


class AcknowledgmentHandler:
    """Handles acknowledgment message processing.

    This handler is responsible for sending and processing acknowledgment
    messages in the reliable delivery system.
    """

    def __init__(self, nats_client: NATSClient) -> None:
        """Initialize the acknowledgment handler.

        Args:
            nats_client: NATS client for messaging operations
        """
        self._nats_client = nats_client

    async def send_acknowledgment(
        self,
        ack_request: AcknowledgmentRequest,
    ) -> None:
        """Send an acknowledgment message.

        Args:
            ack_request: Acknowledgment request containing message details
        """
        # Create the acknowledgment subject based on message ID
        ack_subject = f"ipc.ack.{ack_request.message_id}"

        # Prepare acknowledgment data
        ack_data = {
            "message_id": str(ack_request.message_id),
            "service_name": ack_request.service_name,
            "instance_id": ack_request.instance_id,
            "status": ack_request.status,
            "error_message": ack_request.error_message,
            "processing_time_ms": ack_request.processing_time_ms,
            "trace_id": ack_request.trace_id,
        }

        try:
            # Send acknowledgment via NATS
            await self._nats_client.publish(
                subject=ack_subject,
                data=ack_data,
            )

            logger.info(
                "Sent acknowledgment",
                extra={
                    "message_id": str(ack_request.message_id),
                    "status": ack_request.status,
                    "processing_time_ms": ack_request.processing_time_ms,
                    "trace_id": ack_request.trace_id,
                },
            )

        except Exception as e:
            logger.error(
                "Failed to send acknowledgment",
                exc_info=e,
                extra={
                    "message_id": str(ack_request.message_id),
                    "subject": ack_subject,
                    "trace_id": ack_request.trace_id,
                },
            )
            raise

    async def handle_acknowledgment_response(
        self,
        data: dict[str, Any],
        reply: str | None,
    ) -> None:
        """Handle incoming acknowledgment response messages.

        This method is used when we need to process acknowledgment responses
        in a queue-based pattern.

        Args:
            data: The acknowledgment response data
            reply: Optional reply subject
        """
        try:
            # Create response model from data
            response = AcknowledgmentResponse(
                success=data.get("success", False),
                message=data.get("message", ""),
                trace_id=data.get("trace_id", ""),
            )

            logger.info(
                "Received acknowledgment response",
                extra={
                    "success": response.success,
                    "message": response.message,
                    "trace_id": response.trace_id,
                },
            )

            # If there's a reply subject, send a confirmation
            if reply:
                await self._nats_client.publish(
                    subject=reply,
                    data={"confirmed": True},
                )

        except Exception as e:
            logger.error(
                "Error processing acknowledgment response",
                exc_info=e,
                extra={
                    "data": data,
                    "reply": reply,
                },
            )

    async def setup_acknowledgment_listeners(self) -> None:
        """Set up listeners for acknowledgment-related messages.

        This method sets up the necessary subscriptions for handling
        acknowledgment messages in the system.
        """
        try:
            # Subscribe to acknowledgment response subject
            await self._nats_client.subscribe(
                subject="ipc.ack.response",
                callback=self.handle_acknowledgment_response,
                queue="acknowledgment-handlers",
            )

            logger.info("Set up acknowledgment listeners")

        except Exception as e:
            logger.error(
                "Failed to set up acknowledgment listeners",
                exc_info=e,
            )
            raise
