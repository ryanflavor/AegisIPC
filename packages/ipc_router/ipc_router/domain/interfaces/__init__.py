"""Domain interfaces for IPC Router.

This module contains abstract interfaces that define contracts
for various domain services and strategies.
"""

from __future__ import annotations

from .load_balancer import LoadBalancer
from .resource_manager import ResourceManager

__all__ = ["LoadBalancer", "ResourceManager"]
