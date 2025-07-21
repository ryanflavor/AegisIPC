"""Service registration and discovery data models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ServiceRegistrationRequest(BaseModel):
    """Request model for service registration.

    Attributes:
        service_name: Name of the service to register
        instance_id: Unique identifier for this service instance
        metadata: Optional metadata associated with the instance
    """

    service_name: str = Field(..., description="Name of the service to register")
    instance_id: str = Field(..., description="Unique identifier for this service instance")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Optional metadata")

    @field_validator("service_name", "instance_id")
    @classmethod
    def validate_non_empty(cls, v: str) -> str:
        """Validate that service name and instance ID are not empty."""
        if not v or not v.strip():
            raise ValueError("Value must not be empty")
        return v.strip()

    @field_validator("instance_id")
    @classmethod
    def validate_instance_id(cls, v: str) -> str:
        """Validate instance ID format."""
        if len(v) < 8:
            raise ValueError("Instance ID must be at least 8 characters")
        return v

    model_config = {
        "json_schema_extra": {
            "example": {
                "service_name": "user-service",
                "instance_id": "usr_srv_01_abc123",
                "metadata": {"version": "1.0.0", "region": "us-east-1"},
            }
        }
    }


class ServiceRegistrationResponse(BaseModel):
    """Response model for service registration.

    Attributes:
        success: Whether the registration was successful
        service_name: Name of the registered service
        instance_id: ID of the registered instance
        registered_at: Timestamp when the instance was registered
        message: Optional message about the registration
    """

    success: bool = Field(..., description="Whether the registration was successful")
    service_name: str = Field(..., description="Name of the registered service")
    instance_id: str = Field(..., description="ID of the registered instance")
    registered_at: datetime = Field(..., description="Registration timestamp")
    message: str | None = Field(None, description="Optional message about the registration")

    model_config = {
        "json_schema_extra": {
            "example": {
                "success": True,
                "service_name": "user-service",
                "instance_id": "usr_srv_01_abc123",
                "registered_at": "2025-01-21T10:00:00Z",
                "message": "Service instance registered successfully",
            }
        }
    }


class ServiceInstanceInfo(BaseModel):
    """Information about a service instance.

    Attributes:
        instance_id: Unique identifier for this service instance
        status: Current status of the instance
        registered_at: Timestamp when the instance was registered
        last_heartbeat: Timestamp of the last heartbeat
        metadata: Optional metadata associated with the instance
    """

    instance_id: str = Field(..., description="Unique instance identifier")
    status: str = Field(..., description="Current status (ONLINE, OFFLINE, UNHEALTHY)")
    registered_at: datetime = Field(..., description="Registration timestamp")
    last_heartbeat: datetime = Field(..., description="Last heartbeat timestamp")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Optional metadata")


class ServiceInfo(BaseModel):
    """Information about a service and its instances.

    Attributes:
        name: Name of the service
        instances: List of service instances
        created_at: Timestamp when the service was first registered
        metadata: Optional metadata associated with the service
    """

    name: str = Field(..., description="Service name")
    instances: list[ServiceInstanceInfo] = Field(..., description="List of service instances")
    created_at: datetime = Field(..., description="Service creation timestamp")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Optional metadata")

    @property
    def instance_count(self) -> int:
        """Get the total number of instances."""
        return len(self.instances)

    @property
    def healthy_instance_count(self) -> int:
        """Get the number of healthy instances."""
        return len([i for i in self.instances if i.status == "ONLINE"])


class ServiceListResponse(BaseModel):
    """Response model for listing all services.

    Attributes:
        services: List of all registered services
        total_count: Total number of services
    """

    services: list[ServiceInfo] = Field(..., description="List of all registered services")
    total_count: int = Field(..., description="Total number of services")

    model_config = {
        "json_schema_extra": {
            "example": {
                "services": [
                    {
                        "name": "user-service",
                        "instances": [
                            {
                                "instance_id": "usr_srv_01",
                                "status": "ONLINE",
                                "registered_at": "2025-01-21T10:00:00Z",
                                "last_heartbeat": "2025-01-21T10:05:00Z",
                                "metadata": {},
                            }
                        ],
                        "created_at": "2025-01-21T10:00:00Z",
                        "metadata": {},
                    }
                ],
                "total_count": 1,
            }
        }
    }
