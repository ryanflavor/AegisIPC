"""Abstract interface for load balancing strategies.

This module defines the contract for implementing different
load balancing algorithms for service instance selection.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ipc_router.domain.entities.service import ServiceInstance


class LoadBalancer(ABC):
    """Abstract base class for load balancing strategies.

    This interface defines the contract for implementing various
    load balancing algorithms such as round-robin, least connections,
    weighted distribution, etc.
    """

    @abstractmethod
    def select_instance(
        self, instances: list[ServiceInstance], service_name: str
    ) -> ServiceInstance | None:
        """Select an instance from the available instances.

        Args:
            instances: List of available service instances.
            service_name: Name of the service for context.

        Returns:
            Selected service instance, or None if no instance available.

        Note:
            Implementations should handle empty instance lists gracefully
            and may maintain internal state for algorithms like round-robin.
        """
        pass

    @abstractmethod
    def reset(self, service_name: str) -> None:
        """Reset the load balancer state for a specific service.

        Args:
            service_name: Name of the service to reset state for.

        Note:
            This is useful when service topology changes significantly
            or when you want to restart the balancing algorithm.
        """
        pass

    @abstractmethod
    def remove_instance(self, instance_id: str, service_name: str) -> None:
        """Notify the load balancer that an instance has been removed.

        Args:
            instance_id: ID of the instance that was removed.
            service_name: Name of the service the instance belongs to.

        Note:
            This allows the load balancer to update its internal state
            when instances are removed from the pool.
        """
        pass
