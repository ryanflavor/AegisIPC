"""Resource management Pydantic models for request/response handling."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ResourceMetadata(BaseModel):
    """Resource metadata structured definition."""

    resource_type: str = Field(
        ..., description="Resource type (e.g., 'user', 'session', 'document')"
    )
    version: int = Field(..., description="Resource version number for optimistic locking")
    tags: list[str] = Field(
        default_factory=list, description="Resource tags for classification and search"
    )
    attributes: dict[str, Any] = Field(default_factory=dict, description="Custom attributes")
    created_by: str = Field(..., description="Creator identifier")
    last_modified: datetime = Field(..., description="Last modification time")
    ttl_seconds: int | None = Field(
        default=None, description="Resource TTL in seconds, None for permanent"
    )
    priority: int = Field(default=0, description="Resource priority for load balancing decisions")

    @field_validator("resource_type")
    @classmethod
    def validate_resource_type(cls, v: str) -> str:
        """Validate resource type is not empty."""
        if not v or not v.strip():
            raise ValueError("Resource type cannot be empty")
        return v.strip()

    @field_validator("created_by")
    @classmethod
    def validate_created_by(cls, v: str) -> str:
        """Validate creator is not empty."""
        if not v or not v.strip():
            raise ValueError("Creator cannot be empty")
        return v.strip()

    model_config = {
        "json_schema_extra": {
            "example": {
                "resource_type": "user_session",
                "version": 1,
                "tags": ["active", "premium"],
                "attributes": {"region": "us-west", "tier": "gold"},
                "created_by": "auth-service",
                "last_modified": "2025-07-22T10:00:00Z",
                "ttl_seconds": 3600,
                "priority": 10,
            }
        }
    }


class ResourceRegistrationRequest(BaseModel):
    """Request to register resources to a service instance."""

    service_name: str = Field(..., description="Service name")
    instance_id: str = Field(..., description="Instance ID")
    resource_ids: list[str] = Field(..., description="List of resource IDs to register")
    force: bool = Field(default=False, description="Force override existing registration")
    metadata: dict[str, ResourceMetadata] = Field(
        default_factory=dict, description="Metadata for each resource ID"
    )
    trace_id: str = Field(..., description="Distributed tracing ID")

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

    @field_validator("resource_ids")
    @classmethod
    def validate_resource_ids(cls, v: list[str]) -> list[str]:
        """Validate resource IDs list is not empty and contains valid IDs."""
        if not v:
            raise ValueError("Resource IDs list cannot be empty")
        for resource_id in v:
            if not resource_id or not resource_id.strip():
                raise ValueError("Resource ID cannot be empty")
        return v

    model_config = {
        "json_schema_extra": {
            "example": {
                "service_name": "user-service",
                "instance_id": "user-service-1",
                "resource_ids": ["user-123", "user-456"],
                "force": False,
                "metadata": {
                    "user-123": {
                        "resource_type": "user_session",
                        "version": 1,
                        "tags": ["active"],
                        "attributes": {"region": "us-west"},
                        "created_by": "auth-service",
                        "last_modified": "2025-07-22T10:00:00Z",
                        "ttl_seconds": 3600,
                        "priority": 10,
                    }
                },
                "trace_id": "trace-abc-123",
            }
        }
    }


class ResourceRegistrationResponse(BaseModel):
    """Response for resource registration request."""

    success: bool = Field(..., description="Whether registration was successful")
    registered: list[str] = Field(..., description="Successfully registered resource IDs")
    conflicts: dict[str, str] = Field(
        default_factory=dict, description="Conflicting resource IDs and their current owners"
    )
    trace_id: str = Field(..., description="Distributed tracing ID")

    model_config = {
        "json_schema_extra": {
            "example": {
                "success": True,
                "registered": ["user-123", "user-456"],
                "conflicts": {"user-789": "user-service-2"},
                "trace_id": "trace-abc-123",
            }
        }
    }


class ResourceReleaseRequest(BaseModel):
    """Request to release resources from a service instance."""

    service_name: str = Field(..., description="Service name")
    instance_id: str = Field(..., description="Instance ID")
    resource_ids: list[str] = Field(..., description="List of resource IDs to release")
    trace_id: str = Field(..., description="Distributed tracing ID")

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

    @field_validator("resource_ids")
    @classmethod
    def validate_resource_ids(cls, v: list[str]) -> list[str]:
        """Validate resource IDs list is not empty and contains valid IDs."""
        if not v:
            raise ValueError("Resource IDs list cannot be empty")
        for resource_id in v:
            if not resource_id or not resource_id.strip():
                raise ValueError("Resource ID cannot be empty")
        return v

    model_config = {
        "json_schema_extra": {
            "example": {
                "service_name": "user-service",
                "instance_id": "user-service-1",
                "resource_ids": ["user-123", "user-456"],
                "trace_id": "trace-abc-123",
            }
        }
    }


class ResourceReleaseResponse(BaseModel):
    """Response for resource release request."""

    success: bool = Field(..., description="Whether release was successful")
    released: list[str] = Field(..., description="Successfully released resource IDs")
    errors: dict[str, str] = Field(
        default_factory=dict, description="Failed resource IDs and error messages"
    )
    trace_id: str = Field(..., description="Distributed tracing ID")

    model_config = {
        "json_schema_extra": {
            "example": {
                "success": True,
                "released": ["user-123", "user-456"],
                "errors": {"user-789": "Resource not owned by instance"},
                "trace_id": "trace-abc-123",
            }
        }
    }


class BulkResourceRegistrationRequest(BaseModel):
    """Bulk resource registration request for large-scale resource registration."""

    service_name: str = Field(..., description="Service name")
    instance_id: str = Field(..., description="Instance ID")
    resources: list[ResourceRegistrationItem] = Field(..., description="Bulk resource items")
    batch_size: int = Field(default=100, gt=0, le=1000, description="Resources per batch")
    continue_on_error: bool = Field(default=False, description="Continue on error")
    trace_id: str = Field(..., description="Distributed tracing ID")

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

    @field_validator("resources")
    @classmethod
    def validate_resources(
        cls, v: list[ResourceRegistrationItem]
    ) -> list[ResourceRegistrationItem]:
        """Validate resources list is not empty."""
        if not v:
            raise ValueError("Resources list cannot be empty")
        return v

    model_config = {
        "json_schema_extra": {
            "example": {
                "service_name": "user-service",
                "instance_id": "user-service-1",
                "resources": [
                    {
                        "resource_id": "user-123",
                        "metadata": {
                            "resource_type": "user_session",
                            "version": 1,
                            "tags": ["active"],
                            "attributes": {"region": "us-west"},
                            "created_by": "auth-service",
                            "last_modified": "2025-07-22T10:00:00Z",
                            "ttl_seconds": 3600,
                            "priority": 10,
                        },
                        "force": False,
                    }
                ],
                "batch_size": 100,
                "continue_on_error": False,
                "trace_id": "trace-abc-123",
            }
        }
    }


class ResourceRegistrationItem(BaseModel):
    """Single resource registration item."""

    resource_id: str = Field(..., description="Resource ID")
    metadata: ResourceMetadata = Field(..., description="Resource metadata")
    force: bool = Field(default=False, description="Force override existing registration")

    @field_validator("resource_id")
    @classmethod
    def validate_resource_id(cls, v: str) -> str:
        """Validate resource ID is not empty."""
        if not v or not v.strip():
            raise ValueError("Resource ID cannot be empty")
        return v.strip()

    model_config = {
        "json_schema_extra": {
            "example": {
                "resource_id": "user-123",
                "metadata": {
                    "resource_type": "user_session",
                    "version": 1,
                    "tags": ["active"],
                    "attributes": {"region": "us-west"},
                    "created_by": "auth-service",
                    "last_modified": "2025-07-22T10:00:00Z",
                    "ttl_seconds": 3600,
                    "priority": 10,
                },
                "force": False,
            }
        }
    }


class BulkResourceRegistrationResponse(BaseModel):
    """Bulk registration response."""

    total_requested: int = Field(..., description="Total resources requested")
    total_registered: int = Field(..., description="Total resources registered")
    registered: list[str] = Field(..., description="Successfully registered resource IDs")
    failed: list[ResourceRegistrationFailure] = Field(..., description="Failed registrations")
    batch_results: list[BatchResult] = Field(..., description="Results per batch")
    trace_id: str = Field(..., description="Distributed tracing ID")

    model_config = {
        "json_schema_extra": {
            "example": {
                "total_requested": 100,
                "total_registered": 95,
                "registered": ["user-123", "user-456"],
                "failed": [
                    {
                        "resource_id": "user-789",
                        "reason": "Resource already registered",
                        "current_owner": "user-service-2",
                        "error_code": "RESOURCE_CONFLICT",
                    }
                ],
                "batch_results": [
                    {
                        "batch_number": 1,
                        "success_count": 95,
                        "failure_count": 5,
                        "duration_ms": 125.5,
                    }
                ],
                "trace_id": "trace-abc-123",
            }
        }
    }


class ResourceRegistrationFailure(BaseModel):
    """Registration failure details."""

    resource_id: str = Field(..., description="Resource ID that failed")
    reason: str = Field(..., description="Failure reason")
    current_owner: str | None = Field(default=None, description="Current owner if conflict")
    error_code: str = Field(..., description="Error code")

    model_config = {
        "json_schema_extra": {
            "example": {
                "resource_id": "user-789",
                "reason": "Resource already registered",
                "current_owner": "user-service-2",
                "error_code": "RESOURCE_CONFLICT",
            }
        }
    }


class BatchResult(BaseModel):
    """Batch processing result."""

    batch_number: int = Field(..., description="Batch number")
    success_count: int = Field(..., description="Successful operations")
    failure_count: int = Field(..., description="Failed operations")
    duration_ms: float = Field(..., description="Processing duration in milliseconds")

    model_config = {
        "json_schema_extra": {
            "example": {
                "batch_number": 1,
                "success_count": 95,
                "failure_count": 5,
                "duration_ms": 125.5,
            }
        }
    }


class ResourceTransferRequest(BaseModel):
    """Resource ownership transfer request."""

    service_name: str = Field(..., description="Service name")
    resource_ids: list[str] = Field(..., description="Resource IDs to transfer")
    from_instance_id: str = Field(..., description="Current owner instance ID")
    to_instance_id: str = Field(..., description="Target instance ID")
    verify_ownership: bool = Field(default=True, description="Verify sender is current owner")
    reason: str = Field(..., description="Transfer reason for audit")
    trace_id: str = Field(..., description="Distributed tracing ID")

    @field_validator("service_name")
    @classmethod
    def validate_service_name(cls, v: str) -> str:
        """Validate service name is not empty."""
        if not v or not v.strip():
            raise ValueError("Service name cannot be empty")
        return v.strip()

    @field_validator("resource_ids")
    @classmethod
    def validate_resource_ids(cls, v: list[str]) -> list[str]:
        """Validate resource IDs list is not empty and contains valid IDs."""
        if not v:
            raise ValueError("Resource IDs list cannot be empty")
        for resource_id in v:
            if not resource_id or not resource_id.strip():
                raise ValueError("Resource ID cannot be empty")
        return v

    @field_validator("from_instance_id")
    @classmethod
    def validate_from_instance_id(cls, v: str) -> str:
        """Validate from instance ID is not empty."""
        if not v or not v.strip():
            raise ValueError("From instance ID cannot be empty")
        return v.strip()

    @field_validator("to_instance_id")
    @classmethod
    def validate_to_instance_id(cls, v: str) -> str:
        """Validate to instance ID is not empty."""
        if not v or not v.strip():
            raise ValueError("To instance ID cannot be empty")
        return v.strip()

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: str) -> str:
        """Validate reason is not empty."""
        if not v or not v.strip():
            raise ValueError("Transfer reason cannot be empty")
        return v.strip()

    model_config = {
        "json_schema_extra": {
            "example": {
                "service_name": "user-service",
                "resource_ids": ["user-123", "user-456"],
                "from_instance_id": "user-service-1",
                "to_instance_id": "user-service-2",
                "verify_ownership": True,
                "reason": "Load balancing",
                "trace_id": "trace-abc-123",
            }
        }
    }


class ResourceTransferResponse(BaseModel):
    """Resource transfer response."""

    success: bool = Field(..., description="Whether transfer was successful")
    transferred: list[str] = Field(..., description="Successfully transferred resource IDs")
    failed: dict[str, str] = Field(
        default_factory=dict, description="Failed resource IDs and reasons"
    )
    transfer_id: str = Field(..., description="Transfer operation unique identifier")
    trace_id: str = Field(..., description="Distributed tracing ID")

    model_config = {
        "json_schema_extra": {
            "example": {
                "success": True,
                "transferred": ["user-123", "user-456"],
                "failed": {"user-789": "Resource not found"},
                "transfer_id": "transfer-xyz-789",
                "trace_id": "trace-abc-123",
            }
        }
    }


class ResourceQueryRequest(BaseModel):
    """Resource query request."""

    service_name: str | None = Field(default=None, description="Filter by service name")
    instance_id: str | None = Field(default=None, description="Filter by instance ID")
    resource_ids: list[str] | None = Field(default=None, description="Filter by resource IDs")
    resource_type: str | None = Field(default=None, description="Filter by resource type")
    tags: list[str] | None = Field(default=None, description="Filter by tags")
    include_metadata: bool = Field(default=True, description="Include metadata in response")
    limit: int = Field(default=100, gt=0, le=1000, description="Result limit")
    offset: int = Field(default=0, ge=0, description="Result offset")
    trace_id: str = Field(..., description="Distributed tracing ID")

    model_config = {
        "json_schema_extra": {
            "example": {
                "service_name": "user-service",
                "instance_id": "user-service-1",
                "resource_ids": ["user-123", "user-456"],
                "resource_type": "user_session",
                "tags": ["active"],
                "include_metadata": True,
                "limit": 100,
                "offset": 0,
                "trace_id": "trace-abc-123",
            }
        }
    }


class ResourceQueryResponse(BaseModel):
    """Resource query response."""

    resources: list[ResourceInfo] = Field(..., description="Matching resources")
    total_count: int = Field(..., description="Total matching resources")
    has_more: bool = Field(..., description="Whether more results exist")
    trace_id: str = Field(..., description="Distributed tracing ID")

    model_config = {
        "json_schema_extra": {
            "example": {
                "resources": [
                    {
                        "resource_id": "user-123",
                        "owner_instance_id": "user-service-1",
                        "service_name": "user-service",
                        "registered_at": "2025-07-22T10:00:00Z",
                        "metadata": {
                            "resource_type": "user_session",
                            "version": 1,
                            "tags": ["active"],
                            "attributes": {"region": "us-west"},
                            "created_by": "auth-service",
                            "last_modified": "2025-07-22T10:00:00Z",
                            "ttl_seconds": 3600,
                            "priority": 10,
                        },
                        "is_healthy": True,
                    }
                ],
                "total_count": 150,
                "has_more": True,
                "trace_id": "trace-abc-123",
            }
        }
    }


class ResourceInfo(BaseModel):
    """Resource detailed information."""

    resource_id: str = Field(..., description="Resource ID")
    owner_instance_id: str = Field(..., description="Owner instance ID")
    service_name: str = Field(..., description="Service name")
    registered_at: datetime = Field(..., description="Registration timestamp")
    metadata: ResourceMetadata | None = Field(default=None, description="Resource metadata")
    is_healthy: bool = Field(..., description="Whether owner instance is healthy")

    model_config = {
        "json_schema_extra": {
            "example": {
                "resource_id": "user-123",
                "owner_instance_id": "user-service-1",
                "service_name": "user-service",
                "registered_at": "2025-07-22T10:00:00Z",
                "metadata": {
                    "resource_type": "user_session",
                    "version": 1,
                    "tags": ["active"],
                    "attributes": {"region": "us-west"},
                    "created_by": "auth-service",
                    "last_modified": "2025-07-22T10:00:00Z",
                    "ttl_seconds": 3600,
                    "priority": 10,
                },
                "is_healthy": True,
            }
        }
    }


class BulkResourceReleaseRequest(BaseModel):
    """Bulk resource release request for large-scale resource release."""

    service_name: str = Field(..., description="Service name")
    instance_id: str = Field(..., description="Instance ID")
    resource_ids: list[str] = Field(..., description="Resource IDs to release")
    batch_size: int = Field(default=100, gt=0, le=1000, description="Resources per batch")
    continue_on_error: bool = Field(default=False, description="Continue on error")
    transactional: bool = Field(default=True, description="Use transactional processing")
    trace_id: str = Field(..., description="Distributed tracing ID")

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

    @field_validator("resource_ids")
    @classmethod
    def validate_resource_ids(cls, v: list[str]) -> list[str]:
        """Validate resource IDs list is not empty and contains valid IDs."""
        if not v:
            raise ValueError("Resource IDs list cannot be empty")
        for resource_id in v:
            if not resource_id or not resource_id.strip():
                raise ValueError("Resource ID cannot be empty")
        return [rid.strip() for rid in v]

    model_config = {
        "json_schema_extra": {
            "example": {
                "service_name": "user-service",
                "instance_id": "user-service-1",
                "resource_ids": ["user-123", "user-456", "user-789"],
                "batch_size": 100,
                "continue_on_error": False,
                "transactional": True,
                "trace_id": "trace-abc-123",
            }
        }
    }


class BulkResourceReleaseResponse(BaseModel):
    """Bulk release response."""

    total_requested: int = Field(..., description="Total resources requested for release")
    total_released: int = Field(..., description="Total resources successfully released")
    released: list[str] = Field(..., description="Successfully released resource IDs")
    failed: list[ResourceReleaseFailure] = Field(..., description="Failed releases")
    batch_results: list[BatchResult] = Field(..., description="Results per batch")
    rollback_performed: bool = Field(default=False, description="Whether a rollback was performed")
    trace_id: str = Field(..., description="Distributed tracing ID")

    model_config = {
        "json_schema_extra": {
            "example": {
                "total_requested": 100,
                "total_released": 95,
                "released": ["user-123", "user-456"],
                "failed": [
                    {
                        "resource_id": "user-789",
                        "reason": "Resource not owned by instance",
                        "error_code": "NOT_OWNER",
                    }
                ],
                "batch_results": [
                    {
                        "batch_number": 1,
                        "success_count": 95,
                        "failure_count": 5,
                        "duration_ms": 125.5,
                    }
                ],
                "rollback_performed": False,
                "trace_id": "trace-abc-123",
            }
        }
    }


class ResourceReleaseFailure(BaseModel):
    """Release failure details."""

    resource_id: str = Field(..., description="Resource ID that failed")
    reason: str = Field(..., description="Failure reason")
    error_code: str = Field(..., description="Error code")

    model_config = {
        "json_schema_extra": {
            "example": {
                "resource_id": "user-789",
                "reason": "Resource not owned by instance",
                "error_code": "NOT_OWNER",
            }
        }
    }
