"""Routing-related Pydantic models for request/response handling."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class RouteRequest(BaseModel):
    """Model for routing requests to services.

    This model represents a request to route a method call to a service instance.
    """

    service_name: str = Field(..., description="Target service name")
    resource_id: str | None = Field(default=None, description="Resource ID for precise routing")
    method: str = Field(..., description="Method to call on the service")
    params: dict[str, Any] = Field(default_factory=dict, description="Method parameters")
    timeout: float = Field(default=5.0, gt=0, le=300, description="Request timeout in seconds")
    trace_id: str = Field(..., description="Distributed tracing ID")
    message_id: UUID | None = Field(
        default=None, description="Unique message ID for exactly-once delivery"
    )
    require_ack: bool = Field(
        default=False, description="Whether this request requires acknowledgment"
    )
    excluded_instances: list[str] = Field(
        default_factory=list, description="Instance IDs to exclude from routing (for retry logic)"
    )

    @field_validator("service_name")
    @classmethod
    def validate_service_name(cls, v: str) -> str:
        """Validate service name is not empty."""
        if not v or not v.strip():
            raise ValueError("Service name cannot be empty")
        return v.strip()

    @field_validator("method")
    @classmethod
    def validate_method(cls, v: str) -> str:
        """Validate method name is not empty."""
        if not v or not v.strip():
            raise ValueError("Method name cannot be empty")
        return v.strip()

    model_config = {
        "json_schema_extra": {
            "example": {
                "service_name": "user-service",
                "resource_id": "user-123",
                "method": "get_user",
                "params": {"user_id": "123"},
                "timeout": 5.0,
                "trace_id": "trace-abc-123",
                "message_id": "550e8400-e29b-41d4-a716-446655440000",
                "require_ack": False,
            }
        }
    }


class RouteResponse(BaseModel):
    """Model for routing response.

    This model represents the response from a routed method call.
    """

    success: bool = Field(..., description="Whether the routing was successful")
    result: Any = Field(default=None, description="Result from the method call")
    error: dict[str, Any] | None = Field(default=None, description="Error details if failed")
    instance_id: str | None = Field(default=None, description="ID of instance that handled request")
    trace_id: str = Field(..., description="Distributed tracing ID")
    message_id: UUID | None = Field(
        default=None, description="Message ID for tracking acknowledgments"
    )
    duration_ms: float | None = Field(default=None, description="Total duration in milliseconds")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Response timestamp"
    )

    model_config = {
        "json_schema_extra": {
            "examples": {
                "success": {
                    "success": True,
                    "result": {"user_id": "123", "name": "John Doe"},
                    "instance_id": "user-service-1",
                    "trace_id": "trace-abc-123",
                    "duration_ms": 25.5,
                    "timestamp": "2025-07-21T10:00:00Z",
                },
                "error": {
                    "success": False,
                    "error": {
                        "type": "ServiceUnavailableError",
                        "message": "No healthy instances available",
                        "code": 503,
                    },
                    "trace_id": "trace-abc-123",
                    "duration_ms": 5.2,
                    "timestamp": "2025-07-21T10:00:00Z",
                },
            }
        }
    }


class HeartbeatRequest(BaseModel):
    """Model for service instance heartbeat requests.

    This model represents a heartbeat message sent by a service instance
    to indicate it is still alive and healthy.
    """

    service_name: str = Field(..., description="Name of the service sending heartbeat")
    instance_id: str = Field(..., description="Unique instance identifier")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Heartbeat timestamp"
    )
    status: str = Field(default="healthy", description="Instance status")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Optional metadata about instance state"
    )

    @field_validator("service_name")
    @classmethod
    def validate_service_name(cls, v: str) -> str:
        """Validate service name is not empty."""
        if not v or not v.strip():
            raise ValueError("Service name cannot be empty")
        return v.strip()

    @field_validator("instance_id")
    @classmethod
    def validate_instance_id(cls, v: str) -> str:
        """Validate instance ID is not empty."""
        if not v or not v.strip():
            raise ValueError("Instance ID cannot be empty")
        return v.strip()

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        """Validate status is one of allowed values."""
        allowed_statuses = {"healthy", "unhealthy", "degraded"}
        if v not in allowed_statuses:
            raise ValueError(f"Status must be one of: {', '.join(allowed_statuses)}")
        return v

    model_config = {
        "json_schema_extra": {
            "example": {
                "service_name": "user-service",
                "instance_id": "instance_abc123",
                "timestamp": "2025-07-21T10:00:00Z",
                "status": "healthy",
                "metadata": {"cpu_usage": 45.2, "memory_mb": 512, "active_connections": 10},
            }
        }
    }


class HeartbeatResponse(BaseModel):
    """Model for service instance heartbeat responses.

    This model represents the response sent back to a service instance
    after receiving its heartbeat.
    """

    success: bool = Field(..., description="Whether heartbeat was processed successfully")
    message: str = Field(default="", description="Optional response message")
    next_interval: float | None = Field(
        default=None, description="Suggested next heartbeat interval in seconds"
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Response timestamp"
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "success": True,
                "message": "Heartbeat received",
                "next_interval": 5.0,
                "timestamp": "2025-07-21T10:00:00Z",
            }
        }
    }
