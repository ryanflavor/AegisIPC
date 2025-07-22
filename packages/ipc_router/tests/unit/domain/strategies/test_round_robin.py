"""Unit tests for RoundRobinLoadBalancer."""

from __future__ import annotations

import threading
from datetime import UTC, datetime

from ipc_router.domain.entities.service import ServiceInstance
from ipc_router.domain.enums import ServiceStatus
from ipc_router.domain.strategies.round_robin import RoundRobinLoadBalancer


class TestRoundRobinLoadBalancer:
    """Test cases for RoundRobinLoadBalancer."""

    def test_initialization(self):
        """Test load balancer initialization."""
        lb = RoundRobinLoadBalancer()
        assert lb._service_indices == {}
        assert isinstance(lb._lock, threading.Lock)

    def test_select_instance_empty_list(self):
        """Test selection with empty instance list."""
        lb = RoundRobinLoadBalancer()
        result = lb.select_instance([], "test-service")
        assert result is None

    def test_select_instance_no_healthy_instances(self):
        """Test selection when all instances are unhealthy."""
        lb = RoundRobinLoadBalancer()

        # Create unhealthy instances
        instances = [
            ServiceInstance(
                instance_id="inst-1",
                service_name="test-service",
                status=ServiceStatus.UNHEALTHY,
                registered_at=datetime.now(UTC),
                last_heartbeat=datetime.now(UTC),
            ),
            ServiceInstance(
                instance_id="inst-2",
                service_name="test-service",
                status=ServiceStatus.OFFLINE,
                registered_at=datetime.now(UTC),
                last_heartbeat=datetime.now(UTC),
            ),
        ]

        result = lb.select_instance(instances, "test-service")
        assert result is None

    def test_select_instance_single_healthy(self):
        """Test selection with single healthy instance."""
        lb = RoundRobinLoadBalancer()

        instance = ServiceInstance(
            instance_id="inst-1",
            service_name="test-service",
            status=ServiceStatus.ONLINE,
            registered_at=datetime.now(UTC),
            last_heartbeat=datetime.now(UTC),
        )

        instances = [instance]

        # Should always select the same instance
        for _ in range(5):
            result = lb.select_instance(instances, "test-service")
            assert result == instance

    def test_round_robin_distribution(self):
        """Test round-robin distribution across multiple instances."""
        lb = RoundRobinLoadBalancer()

        # Create 3 healthy instances
        instances = [
            ServiceInstance(
                instance_id=f"inst-{i}",
                service_name="test-service",
                status=ServiceStatus.ONLINE,
                registered_at=datetime.now(UTC),
                last_heartbeat=datetime.now(UTC),
            )
            for i in range(1, 4)
        ]

        # Track selections
        selections = []
        for _ in range(9):  # 3 full rounds
            result = lb.select_instance(instances, "test-service")
            selections.append(result.instance_id)

        # Verify round-robin pattern
        expected = ["inst-1", "inst-2", "inst-3"] * 3
        assert selections == expected

    def test_round_robin_with_mixed_health(self):
        """Test round-robin with mix of healthy and unhealthy instances."""
        lb = RoundRobinLoadBalancer()

        # Create mix of instances
        instances = [
            ServiceInstance(
                instance_id="inst-1",
                service_name="test-service",
                status=ServiceStatus.ONLINE,
                registered_at=datetime.now(UTC),
                last_heartbeat=datetime.now(UTC),
            ),
            ServiceInstance(
                instance_id="inst-2",
                service_name="test-service",
                status=ServiceStatus.UNHEALTHY,  # Unhealthy
                registered_at=datetime.now(UTC),
                last_heartbeat=datetime.now(UTC),
            ),
            ServiceInstance(
                instance_id="inst-3",
                service_name="test-service",
                status=ServiceStatus.ONLINE,
                registered_at=datetime.now(UTC),
                last_heartbeat=datetime.now(UTC),
            ),
        ]

        # Should only select healthy instances
        selections = []
        for _ in range(6):
            result = lb.select_instance(instances, "test-service")
            selections.append(result.instance_id)

        # Should alternate between inst-1 and inst-3
        expected = ["inst-1", "inst-3"] * 3
        assert selections == expected

    def test_multiple_services_isolated(self):
        """Test that different services maintain separate indices."""
        lb = RoundRobinLoadBalancer()

        # Create instances for service A
        service_a_instances = [
            ServiceInstance(
                instance_id=f"a-{i}",
                service_name="service-a",
                status=ServiceStatus.ONLINE,
                registered_at=datetime.now(UTC),
                last_heartbeat=datetime.now(UTC),
            )
            for i in range(1, 3)
        ]

        # Create instances for service B
        service_b_instances = [
            ServiceInstance(
                instance_id=f"b-{i}",
                service_name="service-b",
                status=ServiceStatus.ONLINE,
                registered_at=datetime.now(UTC),
                last_heartbeat=datetime.now(UTC),
            )
            for i in range(1, 3)
        ]

        # Interleave selections
        results = []
        for _ in range(3):
            results.append(lb.select_instance(service_a_instances, "service-a").instance_id)
            results.append(lb.select_instance(service_b_instances, "service-b").instance_id)

        # Verify independent round-robin for each service
        assert results == ["a-1", "b-1", "a-2", "b-2", "a-1", "b-1"]

    def test_reset_service(self):
        """Test resetting index for a specific service."""
        lb = RoundRobinLoadBalancer()

        instances = [
            ServiceInstance(
                instance_id=f"inst-{i}",
                service_name="test-service",
                status=ServiceStatus.ONLINE,
                registered_at=datetime.now(UTC),
                last_heartbeat=datetime.now(UTC),
            )
            for i in range(1, 4)
        ]

        # Make some selections
        lb.select_instance(instances, "test-service")  # inst-1
        lb.select_instance(instances, "test-service")  # inst-2

        # Reset should go back to first instance
        lb.reset("test-service")
        result = lb.select_instance(instances, "test-service")
        assert result.instance_id == "inst-1"

    def test_remove_instance(self):
        """Test removing an instance resets the index."""
        lb = RoundRobinLoadBalancer()

        instances = [
            ServiceInstance(
                instance_id=f"inst-{i}",
                service_name="test-service",
                status=ServiceStatus.ONLINE,
                registered_at=datetime.now(UTC),
                last_heartbeat=datetime.now(UTC),
            )
            for i in range(1, 4)
        ]

        # Make some selections
        lb.select_instance(instances, "test-service")  # inst-1
        lb.select_instance(instances, "test-service")  # inst-2

        # Remove instance should reset
        lb.remove_instance("inst-2", "test-service")
        result = lb.select_instance(instances, "test-service")
        assert result.instance_id == "inst-1"

    def test_thread_safety(self):
        """Test thread-safe operations."""
        lb = RoundRobinLoadBalancer()

        instances = [
            ServiceInstance(
                instance_id=f"inst-{i}",
                service_name="test-service",
                status=ServiceStatus.ONLINE,
                registered_at=datetime.now(UTC),
                last_heartbeat=datetime.now(UTC),
            )
            for i in range(1, 11)  # 10 instances
        ]

        selections = []
        lock = threading.Lock()

        def select_many():
            for _ in range(100):
                result = lb.select_instance(instances, "test-service")
                with lock:
                    selections.append(result.instance_id)

        # Run multiple threads
        threads = []
        for _ in range(10):
            t = threading.Thread(target=select_many)
            threads.append(t)
            t.start()

        # Wait for all threads
        for t in threads:
            t.join()

        # Should have 1000 selections total
        assert len(selections) == 1000

        # Count occurrences of each instance
        counts = {}
        for sel in selections:
            counts[sel] = counts.get(sel, 0) + 1

        # Each instance should be selected exactly 100 times
        for instance_id in [f"inst-{i}" for i in range(1, 11)]:
            assert counts[instance_id] == 100

    def test_heartbeat_timeout_filtering(self):
        """Test filtering based on heartbeat timeout."""
        lb = RoundRobinLoadBalancer()

        now = datetime.now(UTC)
        old_time = datetime(2020, 1, 1, tzinfo=UTC)

        instances = [
            ServiceInstance(
                instance_id="inst-fresh",
                service_name="test-service",
                status=ServiceStatus.ONLINE,
                registered_at=now,
                last_heartbeat=now,  # Fresh heartbeat
            ),
            ServiceInstance(
                instance_id="inst-stale",
                service_name="test-service",
                status=ServiceStatus.ONLINE,
                registered_at=old_time,
                last_heartbeat=old_time,  # Stale heartbeat
            ),
        ]

        # Should only select instance with fresh heartbeat
        result = lb.select_instance(instances, "test-service")
        assert result.instance_id == "inst-fresh"
