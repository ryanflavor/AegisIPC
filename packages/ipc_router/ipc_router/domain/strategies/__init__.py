"""Domain strategy implementations.

This module contains concrete implementations of domain strategy interfaces
such as load balancing algorithms.
"""

from __future__ import annotations

from .round_robin import RoundRobinLoadBalancer

__all__ = ["RoundRobinLoadBalancer"]
