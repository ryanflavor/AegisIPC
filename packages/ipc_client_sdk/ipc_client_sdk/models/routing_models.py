"""Routing-related models for Client SDK.

These models should match the server-side models for compatibility.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ServiceCallRequest(BaseModel):
    """Model for making a service call through the router."""

    service_name: str = Field(..., description="Target service name")
    method: str = Field(..., description="Method to call on the service")
    params: dict[str, Any] = Field(default_factory=dict, description="Method parameters")
    timeout: float = Field(default=5.0, gt=0, le=300, description="Request timeout in seconds")
    trace_id: str | None = Field(
        default=None, description="Optional trace ID for distributed tracing"
    )


class ServiceCallResponse(BaseModel):
    """Model for service call response."""

    success: bool = Field(..., description="Whether the call was successful")
    result: Any = Field(default=None, description="Result from the method call")
    error: dict[str, Any] | None = Field(default=None, description="Error details if failed")
    instance_id: str | None = Field(default=None, description="ID of instance that handled request")
    trace_id: str | None = Field(default=None, description="Trace ID for correlation")
    duration_ms: float | None = Field(default=None, description="Total duration in milliseconds")
