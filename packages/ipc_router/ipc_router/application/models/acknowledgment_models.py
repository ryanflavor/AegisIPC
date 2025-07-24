"""Acknowledgment-related Pydantic models for reliable message delivery."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class AcknowledgmentRetryConfig(BaseModel):
    """Configuration for message acknowledgment retry behavior.

    This model extends the general retry concept with acknowledgment-specific
    settings for reliable message delivery.
    """

    max_attempts: int = Field(
        default=3, ge=1, le=10, description="Maximum acknowledgment retry attempts"
    )
    ack_timeout: float = Field(
        default=30.0, gt=0, le=300, description="Timeout for acknowledgment in seconds"
    )
    retry_delay: float = Field(
        default=5.0, gt=0, le=60, description="Delay between retry attempts in seconds"
    )
    exponential_backoff: bool = Field(
        default=True, description="Use exponential backoff for retry delays"
    )
    max_retry_delay: float = Field(
        default=60.0, gt=0, le=300, description="Maximum delay between retries in seconds"
    )
    dead_letter_after_retries: bool = Field(
        default=True, description="Send to dead letter queue after max retries"
    )

    @field_validator("max_retry_delay")
    @classmethod
    def validate_max_retry_delay(cls, v: float, info: object) -> float:
        """Ensure max_retry_delay is greater than or equal to retry_delay."""
        retry_delay = info.data.get("retry_delay", 5.0)  # type: ignore[attr-defined]
        if v < retry_delay:
            raise ValueError("max_retry_delay must be >= retry_delay")
        return v

    model_config = {
        "json_schema_extra": {
            "example": {
                "max_attempts": 3,
                "ack_timeout": 30.0,
                "retry_delay": 5.0,
                "exponential_backoff": True,
                "max_retry_delay": 60.0,
                "dead_letter_after_retries": True,
            }
        }
    }


class MessageDeliveryConfig(BaseModel):
    """Configuration for overall message delivery behavior.

    This model combines retry configuration with other delivery settings
    for complete control over reliable message delivery.
    """

    retry_config: AcknowledgmentRetryConfig = Field(
        default_factory=AcknowledgmentRetryConfig,
        description="Retry configuration for acknowledgments",
    )
    require_explicit_ack: bool = Field(
        default=True, description="Whether messages require explicit acknowledgment"
    )
    auto_ack_on_success: bool = Field(
        default=False, description="Automatically acknowledge on successful processing"
    )
    message_ttl: float = Field(default=3600.0, gt=0, description="Message time-to-live in seconds")
    enable_deduplication: bool = Field(default=True, description="Enable message deduplication")
    dedup_window: float = Field(default=300.0, gt=0, description="Deduplication window in seconds")

    model_config = {
        "json_schema_extra": {
            "example": {
                "retry_config": {
                    "max_attempts": 3,
                    "ack_timeout": 30.0,
                    "retry_delay": 5.0,
                },
                "require_explicit_ack": True,
                "auto_ack_on_success": False,
                "message_ttl": 3600.0,
                "enable_deduplication": True,
                "dedup_window": 300.0,
            }
        }
    }


class AcknowledgmentRequest(BaseModel):
    """Request model for acknowledging message receipt and processing.

    This model is sent by services to acknowledge that they have received
    and processed a message, supporting exactly-once delivery semantics.
    """

    message_id: UUID = Field(..., description="Unique message ID being acknowledged")
    service_name: str = Field(..., description="Name of the service sending acknowledgment")
    instance_id: str = Field(..., description="ID of the specific service instance")
    status: Literal["success", "failure"] = Field(
        ..., description="Processing status of the message"
    )
    error_message: str | None = Field(
        default=None, description="Error message if processing failed"
    )
    processing_time_ms: float = Field(
        ..., gt=0, description="Time taken to process the message in milliseconds"
    )
    trace_id: str = Field(..., description="Distributed tracing ID for correlation")

    @field_validator("service_name", "instance_id")
    @classmethod
    def validate_not_empty(cls, v: str) -> str:
        """Validate that service_name and instance_id are not empty."""
        if not v or not v.strip():
            raise ValueError("Value cannot be empty")
        return v.strip()

    def model_post_init(self, __context: object) -> None:
        """Validate error_message based on status after model initialization."""
        if self.status == "failure" and not self.error_message:
            raise ValueError("Error message must be provided when status is failure")
        if self.status == "success" and self.error_message:
            raise ValueError("Error message should not be provided when status is success")

    model_config = {
        "json_schema_extra": {
            "examples": {
                "success": {
                    "message_id": "550e8400-e29b-41d4-a716-446655440000",
                    "service_name": "user-service",
                    "instance_id": "user-service-1",
                    "status": "success",
                    "processing_time_ms": 45.5,
                    "trace_id": "trace-abc-123",
                },
                "failure": {
                    "message_id": "550e8400-e29b-41d4-a716-446655440000",
                    "service_name": "user-service",
                    "instance_id": "user-service-1",
                    "status": "failure",
                    "error_message": "Database connection failed",
                    "processing_time_ms": 120.5,
                    "trace_id": "trace-abc-123",
                },
            }
        }
    }


class AcknowledgmentResponse(BaseModel):
    """Response model for acknowledgment requests.

    This model confirms that the acknowledgment was received and processed
    by the message router.
    """

    success: bool = Field(..., description="Whether acknowledgment was processed successfully")
    message: str = Field(..., description="Human-readable status message")
    trace_id: str = Field(..., description="Distributed tracing ID for correlation")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Acknowledgment timestamp"
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "success": True,
                "message": "Acknowledgment received and processed",
                "trace_id": "trace-abc-123",
                "timestamp": "2025-07-21T10:00:00Z",
            }
        }
    }


class MessageStatusRequest(BaseModel):
    """Request model for querying message status.

    This model is used to query the current status of a message,
    including its processing state and retry information.
    """

    message_id: UUID = Field(..., description="Message ID to query status for")
    trace_id: str = Field(..., description="Distributed tracing ID for correlation")

    model_config = {
        "json_schema_extra": {
            "example": {
                "message_id": "550e8400-e29b-41d4-a716-446655440000",
                "trace_id": "trace-abc-123",
            }
        }
    }


class MessageStatusResponse(BaseModel):
    """Response model for message status queries.

    This model provides detailed information about a message's current state,
    processing history, and any errors encountered.
    """

    message_id: UUID = Field(..., description="The queried message ID")
    state: str = Field(..., description="Current state of the message (MessageState enum value)")
    retry_count: int = Field(..., ge=0, description="Number of retry attempts made")
    created_at: datetime = Field(..., description="When the message was first created")
    updated_at: datetime = Field(..., description="When the message was last updated")
    last_error: str | None = Field(default=None, description="Last error encountered if any")
    service_name: str = Field(..., description="Target service for the message")
    method: str = Field(..., description="Method being called")
    instance_id: str | None = Field(default=None, description="Instance that processed the message")
    ack_deadline: datetime | None = Field(default=None, description="Deadline for acknowledgment")
    trace_id: str = Field(..., description="Distributed tracing ID for correlation")

    model_config = {
        "json_schema_extra": {
            "examples": {
                "pending": {
                    "message_id": "550e8400-e29b-41d4-a716-446655440000",
                    "state": "pending",
                    "retry_count": 0,
                    "created_at": "2025-07-21T10:00:00Z",
                    "updated_at": "2025-07-21T10:00:00Z",
                    "service_name": "user-service",
                    "method": "get_user",
                    "ack_deadline": "2025-07-21T10:00:30Z",
                    "trace_id": "trace-abc-123",
                },
                "acknowledged": {
                    "message_id": "550e8400-e29b-41d4-a716-446655440000",
                    "state": "acknowledged",
                    "retry_count": 0,
                    "created_at": "2025-07-21T10:00:00Z",
                    "updated_at": "2025-07-21T10:00:05Z",
                    "service_name": "user-service",
                    "method": "get_user",
                    "instance_id": "user-service-1",
                    "trace_id": "trace-abc-123",
                },
                "failed": {
                    "message_id": "550e8400-e29b-41d4-a716-446655440000",
                    "state": "failed",
                    "retry_count": 3,
                    "created_at": "2025-07-21T10:00:00Z",
                    "updated_at": "2025-07-21T10:02:00Z",
                    "last_error": "Maximum retry attempts exceeded",
                    "service_name": "user-service",
                    "method": "get_user",
                    "trace_id": "trace-abc-123",
                },
            }
        }
    }
