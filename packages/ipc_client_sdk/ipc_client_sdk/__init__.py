"""IPC Client SDK for AegisIPC."""

from __future__ import annotations

from .clients import ServiceClient, ServiceClientConfig, ServiceRegistrationError
from .models import (
    ServiceInfo,
    ServiceInstanceInfo,
    ServiceListResponse,
    ServiceRegistrationRequest,
    ServiceRegistrationResponse,
)

__version__ = "0.1.0"

__all__ = [
    "ServiceClient",
    "ServiceClientConfig",
    "ServiceInfo",
    "ServiceInstanceInfo",
    "ServiceListResponse",
    "ServiceRegistrationError",
    "ServiceRegistrationRequest",
    "ServiceRegistrationResponse",
]
