"""Round-robin load balancing strategy implementation.

This module implements a thread-safe round-robin load balancer that
distributes requests evenly across available service instances.
"""

from __future__ import annotations

import threading

from ipc_router.domain.entities.service import ServiceInstance
from ipc_router.domain.enums import ServiceStatus
from ipc_router.domain.interfaces.load_balancer import LoadBalancer
from ipc_router.infrastructure.logging import get_logger

logger = get_logger(__name__)


class RoundRobinLoadBalancer(LoadBalancer):
    """Thread-safe round-robin load balancer implementation.

    This load balancer maintains separate index counters for each service
    and distributes requests evenly across all healthy instances.
    """

    def __init__(self) -> None:
        """Initialize the round-robin load balancer."""
        self._service_indices: dict[str, int] = {}
        self._lock = threading.Lock()
        logger.debug("Initialized RoundRobinLoadBalancer")

    def select_instance(
        self, instances: list[ServiceInstance], service_name: str
    ) -> ServiceInstance | None:
        """Select the next instance using round-robin algorithm.

        Args:
            instances: List of available service instances.
            service_name: Name of the service for context.

        Returns:
            Selected service instance, or None if no healthy instance available.
        """
        # Filter for healthy instances with ONLINE status
        healthy_instances = [
            inst for inst in instances if inst.status == ServiceStatus.ONLINE and inst.is_healthy()
        ]

        if not healthy_instances:
            logger.warning(
                "No healthy instances available for service",
                extra={"service_name": service_name, "total_instances": len(instances)},
            )
            return None

        # Thread-safe index management
        with self._lock:
            if service_name not in self._service_indices:
                self._service_indices[service_name] = 0

            current_index = self._service_indices[service_name]
            selected_instance = healthy_instances[current_index % len(healthy_instances)]

            # Update index for next selection - increment without modulo to maintain fairness
            # when instance count changes
            self._service_indices[service_name] = current_index + 1

        logger.debug(
            "Selected instance via round-robin",
            extra={
                "service_name": service_name,
                "instance_id": selected_instance.instance_id,
                "healthy_count": len(healthy_instances),
                "next_index": self._service_indices[service_name],
            },
        )

        return selected_instance

    def reset(self, service_name: str) -> None:
        """Reset the round-robin index for a specific service.

        Args:
            service_name: Name of the service to reset state for.
        """
        with self._lock:
            if service_name in self._service_indices:
                self._service_indices[service_name] = 0
                logger.info(
                    "Reset round-robin index for service", extra={"service_name": service_name}
                )

    def remove_instance(self, instance_id: str, service_name: str) -> None:
        """Handle instance removal by potentially adjusting the index.

        Args:
            instance_id: ID of the instance that was removed.
            service_name: Name of the service the instance belongs to.
        """
        # When an instance is removed, we may need to adjust the index
        # to prevent skipping instances. For now, we'll reset to be safe.
        # A more sophisticated approach could track instance positions.
        with self._lock:
            if service_name in self._service_indices:
                # Reset to ensure we don't skip instances after removal
                self._service_indices[service_name] = 0
                logger.debug(
                    "Reset index after instance removal",
                    extra={"service_name": service_name, "removed_instance_id": instance_id},
                )
