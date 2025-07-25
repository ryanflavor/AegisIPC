"""Unit tests for Service and ServiceInstance domain entities."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from ipc_router.domain.entities.service import Service, ServiceInstance
from ipc_router.domain.enums import ServiceRole, ServiceStatus


class TestServiceInstance:
    """Tests for ServiceInstance entity."""

    def test_service_instance_creation(self) -> None:
        """Test creating a ServiceInstance with all attributes."""
        instance = ServiceInstance(
            instance_id="test_instance_01",
            service_name="test-service",
            status=ServiceStatus.ONLINE.value,
            metadata={"version": "1.0.0", "region": "us-east-1"},
        )

        assert instance.instance_id == "test_instance_01"
        assert instance.service_name == "test-service"
        assert instance.status == ServiceStatus.ONLINE.value
        assert instance.metadata == {"version": "1.0.0", "region": "us-east-1"}
        assert isinstance(instance.registered_at, datetime)
        assert isinstance(instance.last_heartbeat, datetime)
        assert instance.role is None  # Default role should be None

    def test_service_instance_defaults(self) -> None:
        """Test ServiceInstance with default values."""
        instance = ServiceInstance(
            instance_id="test_instance",
            service_name="test-service",
            status=ServiceStatus.ONLINE.value,
        )

        assert instance.metadata == {}
        assert instance.registered_at <= datetime.now(UTC)
        assert instance.last_heartbeat <= datetime.now(UTC)
        assert instance.role is None  # Default role should be None

    def test_service_instance_with_role(self) -> None:
        """Test creating a ServiceInstance with role."""
        # Test with ACTIVE role
        active_instance = ServiceInstance(
            instance_id="active_instance",
            service_name="test-service",
            status=ServiceStatus.ONLINE.value,
            role=ServiceRole.ACTIVE,
        )
        assert active_instance.role == ServiceRole.ACTIVE

        # Test with STANDBY role
        standby_instance = ServiceInstance(
            instance_id="standby_instance",
            service_name="test-service",
            status=ServiceStatus.ONLINE.value,
            role=ServiceRole.STANDBY,
        )
        assert standby_instance.role == ServiceRole.STANDBY

    def test_update_heartbeat(self) -> None:
        """Test updating heartbeat timestamp."""
        instance = ServiceInstance(
            instance_id="test_instance",
            service_name="test-service",
            status=ServiceStatus.ONLINE.value,
        )

        # Store original heartbeat
        original_heartbeat = instance.last_heartbeat

        # Mock time to ensure heartbeat changes
        future_time = datetime.now(UTC) + timedelta(seconds=5)
        with patch("ipc_router.domain.entities.service.datetime") as mock_datetime:
            mock_datetime.now.return_value = future_time
            instance.update_heartbeat()

        assert instance.last_heartbeat == future_time
        assert instance.last_heartbeat > original_heartbeat

    def test_is_healthy_within_timeout(self) -> None:
        """Test is_healthy returns True when within timeout."""
        instance = ServiceInstance(
            instance_id="test_instance",
            service_name="test-service",
            status=ServiceStatus.ONLINE.value,
        )

        # Instance just created, should be healthy
        assert instance.is_healthy(timeout_seconds=30) is True
        assert instance.is_healthy(timeout_seconds=60) is True

    def test_is_healthy_outside_timeout(self) -> None:
        """Test is_healthy returns False when outside timeout."""
        # Create instance with old heartbeat
        old_time = datetime.now(UTC) - timedelta(seconds=60)
        instance = ServiceInstance(
            instance_id="test_instance",
            service_name="test-service",
            status=ServiceStatus.ONLINE.value,
            last_heartbeat=old_time,
        )

        # Should be unhealthy with 30 second timeout
        assert instance.is_healthy(timeout_seconds=30) is False
        # Should be healthy with 90 second timeout
        assert instance.is_healthy(timeout_seconds=90) is True

    def test_is_healthy_edge_case(self) -> None:
        """Test is_healthy at exact timeout boundary."""
        # Use a fixed time for consistent testing
        fixed_time = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

        instance = ServiceInstance(
            instance_id="test_instance",
            service_name="test-service",
            status=ServiceStatus.ONLINE.value,
            last_heartbeat=fixed_time - timedelta(seconds=30),
        )

        # Mock datetime.now to return the fixed time
        with patch("ipc_router.domain.entities.service.datetime") as mock_datetime:
            mock_datetime.now.return_value = fixed_time

            # Should be healthy at exact boundary (30 seconds = timeout)
            assert instance.is_healthy(timeout_seconds=30) is True

            # Should be unhealthy if heartbeat is older than timeout
            instance.last_heartbeat = fixed_time - timedelta(seconds=30, microseconds=1)
            assert instance.is_healthy(timeout_seconds=30) is False


class TestService:
    """Tests for Service entity."""

    def test_service_creation(self) -> None:
        """Test creating a Service with all attributes."""
        service = Service(
            name="test-service",
            metadata={"description": "Test service", "owner": "team-a"},
        )

        assert service.name == "test-service"
        assert service.instances == {}
        assert service.metadata == {"description": "Test service", "owner": "team-a"}
        assert isinstance(service.created_at, datetime)

    def test_service_defaults(self) -> None:
        """Test Service with default values."""
        service = Service(name="test-service")

        assert service.instances == {}
        assert service.metadata == {}
        assert service.created_at <= datetime.now(UTC)

    def test_add_instance(self) -> None:
        """Test adding instances to a service."""
        service = Service(name="test-service")
        instance1 = ServiceInstance(
            instance_id="instance_01",
            service_name="test-service",
            status=ServiceStatus.ONLINE.value,
        )
        instance2 = ServiceInstance(
            instance_id="instance_02",
            service_name="test-service",
            status=ServiceStatus.ONLINE.value,
        )

        # Add instances
        service.add_instance(instance1)
        service.add_instance(instance2)

        assert len(service.instances) == 2
        assert service.instances["instance_01"] == instance1
        assert service.instances["instance_02"] == instance2

    def test_add_instance_overwrites_existing(self) -> None:
        """Test that adding an instance with same ID overwrites the existing one."""
        service = Service(name="test-service")
        instance1 = ServiceInstance(
            instance_id="instance_01",
            service_name="test-service",
            status=ServiceStatus.ONLINE.value,
        )
        instance2 = ServiceInstance(
            instance_id="instance_01",  # Same ID
            service_name="test-service",
            status=ServiceStatus.OFFLINE.value,
        )

        service.add_instance(instance1)
        service.add_instance(instance2)

        assert len(service.instances) == 1
        assert service.instances["instance_01"] == instance2
        assert service.instances["instance_01"].status == ServiceStatus.OFFLINE.value

    def test_remove_instance_existing(self) -> None:
        """Test removing an existing instance."""
        service = Service(name="test-service")
        instance = ServiceInstance(
            instance_id="instance_01",
            service_name="test-service",
            status=ServiceStatus.ONLINE.value,
        )
        service.add_instance(instance)

        # Remove instance
        removed = service.remove_instance("instance_01")

        assert removed == instance
        assert len(service.instances) == 0
        assert "instance_01" not in service.instances

    def test_remove_instance_non_existing(self) -> None:
        """Test removing a non-existing instance returns None."""
        service = Service(name="test-service")

        removed = service.remove_instance("non_existing")

        assert removed is None
        assert len(service.instances) == 0

    def test_get_instance_existing(self) -> None:
        """Test getting an existing instance."""
        service = Service(name="test-service")
        instance = ServiceInstance(
            instance_id="instance_01",
            service_name="test-service",
            status=ServiceStatus.ONLINE.value,
        )
        service.add_instance(instance)

        retrieved = service.get_instance("instance_01")

        assert retrieved == instance

    def test_get_instance_non_existing(self) -> None:
        """Test getting a non-existing instance returns None."""
        service = Service(name="test-service")

        retrieved = service.get_instance("non_existing")

        assert retrieved is None

    def test_get_healthy_instances(self) -> None:
        """Test getting only healthy instances."""
        service = Service(name="test-service")

        # Add healthy instance
        healthy_instance = ServiceInstance(
            instance_id="healthy_01",
            service_name="test-service",
            status=ServiceStatus.ONLINE.value,
        )

        # Add unhealthy instance (old heartbeat)
        unhealthy_instance = ServiceInstance(
            instance_id="unhealthy_01",
            service_name="test-service",
            status=ServiceStatus.ONLINE.value,
            last_heartbeat=datetime.now(UTC) - timedelta(seconds=60),
        )

        service.add_instance(healthy_instance)
        service.add_instance(unhealthy_instance)

        healthy = service.get_healthy_instances(timeout_seconds=30)

        assert len(healthy) == 1
        assert healthy[0] == healthy_instance

    def test_get_healthy_instances_custom_timeout(self) -> None:
        """Test getting healthy instances with custom timeout."""
        service = Service(name="test-service")

        # Add instance with heartbeat 45 seconds ago
        instance = ServiceInstance(
            instance_id="instance_01",
            service_name="test-service",
            status=ServiceStatus.ONLINE.value,
            last_heartbeat=datetime.now(UTC) - timedelta(seconds=45),
        )
        service.add_instance(instance)

        # Should be unhealthy with 30 second timeout
        healthy_30 = service.get_healthy_instances(timeout_seconds=30)
        assert len(healthy_30) == 0

        # Should be healthy with 60 second timeout
        healthy_60 = service.get_healthy_instances(timeout_seconds=60)
        assert len(healthy_60) == 1

    def test_get_healthy_instances_empty_service(self) -> None:
        """Test getting healthy instances from empty service."""
        service = Service(name="test-service")

        healthy = service.get_healthy_instances()

        assert healthy == []

    def test_instance_count_property(self) -> None:
        """Test instance_count property."""
        service = Service(name="test-service")

        assert service.instance_count == 0

        # Add instances
        for i in range(3):
            instance = ServiceInstance(
                instance_id=f"instance_{i}",
                service_name="test-service",
                status=ServiceStatus.ONLINE.value,
            )
            service.add_instance(instance)

        assert service.instance_count == 3

        # Remove one
        service.remove_instance("instance_1")
        assert service.instance_count == 2

    def test_healthy_instance_count_property(self) -> None:
        """Test healthy_instance_count property."""
        service = Service(name="test-service")

        assert service.healthy_instance_count == 0

        # Add healthy instances
        for i in range(2):
            instance = ServiceInstance(
                instance_id=f"healthy_{i}",
                service_name="test-service",
                status=ServiceStatus.ONLINE.value,
            )
            service.add_instance(instance)

        # Add unhealthy instance
        unhealthy = ServiceInstance(
            instance_id="unhealthy",
            service_name="test-service",
            status=ServiceStatus.ONLINE.value,
            last_heartbeat=datetime.now(UTC) - timedelta(seconds=60),
        )
        service.add_instance(unhealthy)

        assert service.instance_count == 3
        assert service.healthy_instance_count == 2

    def test_service_with_multiple_statuses(self) -> None:
        """Test service with instances in different statuses."""
        service = Service(name="test-service")

        # Add instances with different statuses
        online = ServiceInstance(
            instance_id="online",
            service_name="test-service",
            status=ServiceStatus.ONLINE.value,
        )
        offline = ServiceInstance(
            instance_id="offline",
            service_name="test-service",
            status=ServiceStatus.OFFLINE.value,
        )
        unhealthy = ServiceInstance(
            instance_id="unhealthy",
            service_name="test-service",
            status=ServiceStatus.UNHEALTHY.value,
        )

        service.add_instance(online)
        service.add_instance(offline)
        service.add_instance(unhealthy)

        assert service.instance_count == 3
        # healthy_instance_count uses is_healthy() which checks heartbeat, not status
        # All instances have recent heartbeats, so all are considered healthy
        assert service.healthy_instance_count == 3

        # Make one instance have an old heartbeat
        offline.last_heartbeat = datetime.now(UTC) - timedelta(seconds=60)
        assert service.healthy_instance_count == 2
