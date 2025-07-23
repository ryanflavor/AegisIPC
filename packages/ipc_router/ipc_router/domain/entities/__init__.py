"""Domain entities for the IPC Router."""

from __future__ import annotations

from .resource import Resource, ResourceCollection, ResourceMetadata
from .service import Service, ServiceInstance

__all__ = ["Resource", "ResourceCollection", "ResourceMetadata", "Service", "ServiceInstance"]
