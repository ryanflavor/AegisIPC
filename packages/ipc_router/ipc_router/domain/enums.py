"""Domain enums for the IPC Router."""

from __future__ import annotations

from enum import Enum


class ServiceStatus(Enum):
    """Service instance status enumeration."""

    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    UNHEALTHY = "UNHEALTHY"
