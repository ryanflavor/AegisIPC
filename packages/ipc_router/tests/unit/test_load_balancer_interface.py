"""Unit tests for load balancer interface."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from ipc_router.domain.entities.service import ServiceInstance
from ipc_router.domain.enums import ServiceStatus
from ipc_router.domain.interfaces.load_balancer import LoadBalancer


class MockLoadBalancer(LoadBalancer):
    """Mock implementation of LoadBalancer for testing."""

    def __init__(self) -> None:
        """Initialize mock load balancer."""
        self.select_called = False
        self.reset_called = False
        self.remove_called = False
        self.removed_instances: list[str] = []

    def select_instance(
        self, instances: list[ServiceInstance], service_name: str
    ) -> ServiceInstance | None:
        """Select an instance from the available instances."""
        self.select_called = True
        return instances[0] if instances else None

    def reset(self, service_name: str) -> None:
        """Reset the load balancer state for a specific service."""
        self.reset_called = True

    def remove_instance(self, instance_id: str, service_name: str) -> None:
        """Notify the load balancer that an instance has been removed."""
        self.remove_called = True
        self.removed_instances.append(instance_id)


class TestLoadBalancerInterface:
    """Test LoadBalancer interface."""

    def test_load_balancer_is_abstract(self) -> None:
        """Test that LoadBalancer cannot be instantiated directly."""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            LoadBalancer()  # type: ignore

    def test_mock_implementation_select_instance(self) -> None:
        """Test mock implementation of select_instance."""
        balancer = MockLoadBalancer()

        # Test with instances
        instances = [
            ServiceInstance(
                service_name="test-service",
                instance_id="instance-1",
                registered_at=datetime.now(UTC),
                status=ServiceStatus.ONLINE,
            ),
            ServiceInstance(
                service_name="test-service",
                instance_id="instance-2",
                registered_at=datetime.now(UTC),
                status=ServiceStatus.ONLINE,
            ),
        ]

        result = balancer.select_instance(instances, "test-service")
        assert balancer.select_called
        assert result == instances[0]

        # Test with empty list
        result = balancer.select_instance([], "test-service")
        assert result is None

    def test_mock_implementation_reset(self) -> None:
        """Test mock implementation of reset."""
        balancer = MockLoadBalancer()

        balancer.reset("test-service")
        assert balancer.reset_called

    def test_mock_implementation_remove_instance(self) -> None:
        """Test mock implementation of remove_instance."""
        balancer = MockLoadBalancer()

        balancer.remove_instance("instance-1", "test-service")
        assert balancer.remove_called
        assert "instance-1" in balancer.removed_instances

        balancer.remove_instance("instance-2", "test-service")
        assert len(balancer.removed_instances) == 2
