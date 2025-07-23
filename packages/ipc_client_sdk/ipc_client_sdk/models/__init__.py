"""Shared data models for IPC Client SDK."""

from __future__ import annotations

from .resource_models import (
    BatchResult,
    BulkResourceRegistrationRequest,
    BulkResourceRegistrationResponse,
    BulkResourceReleaseRequest,
    BulkResourceReleaseResponse,
    ResourceMetadata,
    ResourceRegistrationFailure,
    ResourceRegistrationItem,
    ResourceRegistrationRequest,
    ResourceRegistrationResponse,
    ResourceReleaseFailure,
    ResourceReleaseRequest,
    ResourceReleaseResponse,
    ResourceTransferRequest,
    ResourceTransferResponse,
)
from .routing_models import ServiceCallRequest, ServiceCallResponse
from .service_models import (
    ServiceInfo,
    ServiceInstanceInfo,
    ServiceListResponse,
    ServiceRegistrationRequest,
    ServiceRegistrationResponse,
)

__all__ = [
    "BatchResult",
    "BulkResourceRegistrationRequest",
    "BulkResourceRegistrationResponse",
    "BulkResourceReleaseRequest",
    "BulkResourceReleaseResponse",
    "ResourceMetadata",
    "ResourceRegistrationFailure",
    "ResourceRegistrationItem",
    "ResourceRegistrationRequest",
    "ResourceRegistrationResponse",
    "ResourceReleaseFailure",
    "ResourceReleaseRequest",
    "ResourceReleaseResponse",
    "ResourceTransferRequest",
    "ResourceTransferResponse",
    "ServiceCallRequest",
    "ServiceCallResponse",
    "ServiceInfo",
    "ServiceInstanceInfo",
    "ServiceListResponse",
    "ServiceRegistrationRequest",
    "ServiceRegistrationResponse",
]
