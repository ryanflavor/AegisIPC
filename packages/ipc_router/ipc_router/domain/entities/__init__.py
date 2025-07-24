"""Domain entities for the IPC Router."""

from __future__ import annotations

from .message import Message, MessageState
from .resource import Resource, ResourceCollection, ResourceMetadata
from .service import Service, ServiceInstance

__all__ = [
    "Message",
    "MessageState",
    "Resource",
    "ResourceCollection",
    "ResourceMetadata",
    "Service",
    "ServiceInstance",
]
