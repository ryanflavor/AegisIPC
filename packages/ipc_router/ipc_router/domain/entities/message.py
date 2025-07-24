"""Message entity for reliable message delivery.

This module defines the core Message entity and MessageState enum for tracking
message lifecycle in the exactly-once delivery system.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class MessageState(Enum):
    """Message lifecycle states for tracking delivery status."""

    PENDING = "pending"  # Message sent, awaiting acknowledgment
    ACKNOWLEDGED = "acknowledged"  # Message successfully acknowledged
    FAILED = "failed"  # Message processing failed
    EXPIRED = "expired"  # Message expired before acknowledgment


@dataclass
class Message:
    """Entity representing a message in the reliable delivery system.

    This entity tracks the complete lifecycle of a message from creation
    through acknowledgment or failure, supporting exactly-once delivery.

    Attributes:
        message_id: Globally unique message identifier (UUID v4)
        service_name: Target service name for routing
        resource_id: Optional resource ID for precise routing (from Story 1.4)
        method: Method name to invoke on the target service
        params: Method parameters as key-value pairs
        state: Current message state in the delivery lifecycle
        created_at: Message creation timestamp (UTC)
        updated_at: Last state update timestamp (UTC)
        retry_count: Number of delivery retry attempts
        last_error: Error message from the last failed attempt
        response: Cached response for idempotent operations
        ack_deadline: Deadline for acknowledgment before timeout (UTC)
        trace_id: Distributed tracing identifier
    """

    message_id: str
    service_name: str
    method: str
    params: dict[str, Any]
    state: MessageState
    created_at: datetime
    updated_at: datetime
    ack_deadline: datetime
    trace_id: str
    resource_id: str | None = None
    retry_count: int = 0
    last_error: str | None = None
    response: Any | None = None

    def __post_init__(self) -> None:
        """Validate message entity after initialization."""
        if not self.message_id:
            raise ValueError("Message ID cannot be empty")
        if not self.service_name:
            raise ValueError("Service name cannot be empty")
        if not self.method:
            raise ValueError("Method name cannot be empty")
        if not self.trace_id:
            raise ValueError("Trace ID cannot be empty")

        # Ensure timestamps are UTC
        if self.created_at.tzinfo is None:
            self.created_at = self.created_at.replace(tzinfo=UTC)
        if self.updated_at.tzinfo is None:
            self.updated_at = self.updated_at.replace(tzinfo=UTC)
        if self.ack_deadline.tzinfo is None:
            self.ack_deadline = self.ack_deadline.replace(tzinfo=UTC)

    def is_expired(self) -> bool:
        """Check if the message has expired based on acknowledgment deadline.

        Returns:
            True if current time is past the acknowledgment deadline
        """
        return datetime.now(UTC) > self.ack_deadline

    def can_retry(self, max_retries: int = 3) -> bool:
        """Check if the message can be retried.

        Args:
            max_retries: Maximum number of retry attempts allowed

        Returns:
            True if message can be retried (not expired and under retry limit)
        """
        return (
            self.state == MessageState.PENDING
            and self.retry_count < max_retries
            and not self.is_expired()
        )

    def increment_retry(self, error: str | None = None) -> None:
        """Increment retry count and update error information.

        Args:
            error: Error message from the failed attempt
        """
        self.retry_count += 1
        self.last_error = error
        self.updated_at = datetime.now(UTC)

    def mark_acknowledged(self, response: Any | None = None) -> None:
        """Mark message as acknowledged with optional response.

        Args:
            response: Response data to cache for idempotency
        """
        self.state = MessageState.ACKNOWLEDGED
        self.response = response
        self.updated_at = datetime.now(UTC)

    def mark_failed(self, error: str) -> None:
        """Mark message as failed with error information.

        Args:
            error: Error message describing the failure
        """
        self.state = MessageState.FAILED
        self.last_error = error
        self.updated_at = datetime.now(UTC)

    def mark_expired(self) -> None:
        """Mark message as expired."""
        self.state = MessageState.EXPIRED
        self.updated_at = datetime.now(UTC)
