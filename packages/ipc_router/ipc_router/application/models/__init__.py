"""Application layer models for IPC Router."""

from __future__ import annotations

from .resource_models import (
    BatchResult,
    BulkResourceRegistrationRequest,
    BulkResourceRegistrationResponse,
    BulkResourceReleaseRequest,
    BulkResourceReleaseResponse,
    ResourceInfo,
    ResourceMetadata,
    ResourceQueryRequest,
    ResourceQueryResponse,
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
from .routing_models import RouteRequest, RouteResponse

__all__ = [
    "BatchResult",
    "BulkResourceRegistrationRequest",
    "BulkResourceRegistrationResponse",
    "BulkResourceReleaseRequest",
    "BulkResourceReleaseResponse",
    "ResourceInfo",
    "ResourceMetadata",
    "ResourceQueryRequest",
    "ResourceQueryResponse",
    "ResourceRegistrationFailure",
    "ResourceRegistrationItem",
    "ResourceRegistrationRequest",
    "ResourceRegistrationResponse",
    "ResourceReleaseFailure",
    "ResourceReleaseRequest",
    "ResourceReleaseResponse",
    "ResourceTransferRequest",
    "ResourceTransferResponse",
    "RouteRequest",
    "RouteResponse",
]
