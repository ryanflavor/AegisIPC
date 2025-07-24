"""Abstract interface for acknowledgment management.

This module defines the AcknowledgmentManager interface for handling message
acknowledgments in the exactly-once delivery system.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datetime import timedelta


class AcknowledgmentManager(ABC):
    """Abstract interface for managing message acknowledgments.

    This interface defines the contract for waiting for acknowledgments,
    sending acknowledgments, and handling acknowledgment timeouts.
    """

    @abstractmethod
    async def wait_for_ack(
        self,
        message_id: str,
        timeout: timedelta,
        trace_id: str,
    ) -> tuple[bool, Any | None]:
        """Wait for acknowledgment of a message.

        Args:
            message_id: Unique message identifier to wait for
            timeout: Maximum time to wait for acknowledgment
            trace_id: Distributed tracing identifier

        Returns:
            Tuple of (success, response_data):
                - success: True if acknowledged, False if timeout
                - response_data: Optional response data from acknowledgment
        """
        ...

    @abstractmethod
    async def send_ack(
        self,
        message_id: str,
        service_name: str,
        instance_id: str,
        success: bool,
        processing_time_ms: float,
        trace_id: str,
        response_data: Any | None = None,
        error_message: str | None = None,
    ) -> None:
        """Send acknowledgment for a processed message.

        Args:
            message_id: Unique message identifier
            service_name: Name of the acknowledging service
            instance_id: ID of the service instance
            success: Whether message processing succeeded
            processing_time_ms: Time taken to process in milliseconds
            trace_id: Distributed tracing identifier
            response_data: Optional response data for caching
            error_message: Optional error message if processing failed

        Raises:
            AcknowledgmentError: If acknowledgment cannot be sent
        """
        ...

    @abstractmethod
    async def register_ack_handler(
        self,
        message_id: str,
        handler: Any,  # AsyncCallable
    ) -> None:
        """Register a handler to be notified when acknowledgment is received.

        Args:
            message_id: Unique message identifier
            handler: Async callable to invoke when acknowledgment arrives
        """
        ...

    @abstractmethod
    async def cancel_ack_wait(self, message_id: str) -> None:
        """Cancel waiting for acknowledgment of a message.

        Args:
            message_id: Unique message identifier
        """
        ...

    @abstractmethod
    async def get_pending_acks(self) -> list[str]:
        """Get list of message IDs currently waiting for acknowledgment.

        Returns:
            List of message IDs pending acknowledgment
        """
        ...
