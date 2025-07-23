"""NATS message handlers."""

from __future__ import annotations

from .bulk_resource_handler import BulkResourceHandler
from .heartbeat_handler import HeartbeatHandler
from .registration_handler import RegistrationHandler
from .resource_handler import ResourceHandler
from .route_handler import RouteRequestHandler

__all__ = [
    "BulkResourceHandler",
    "HeartbeatHandler",
    "RegistrationHandler",
    "ResourceHandler",
    "RouteRequestHandler",
]
