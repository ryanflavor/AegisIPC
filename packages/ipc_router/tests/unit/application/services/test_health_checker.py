"""Unit tests for HealthChecker service."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from ipc_client_sdk.models import ServiceInfo, ServiceInstanceInfo, ServiceListResponse
from ipc_router.application.services.health_checker import HealthChecker
from ipc_router.application.services.service_registry import ServiceRegistry
from ipc_router.domain.enums import ServiceStatus
from ipc_router.domain.events import ServiceEventType


@pytest.mark.asyncio
class TestHealthChecker:
    """Test cases for HealthChecker service."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.mock_registry = AsyncMock(spec=ServiceRegistry)
        self.check_interval = 1.0
        self.heartbeat_timeout = 3.0
        self.health_checker = HealthChecker(
            self.mock_registry,
            check_interval=self.check_interval,
            heartbeat_timeout=self.heartbeat_timeout,
        )

    async def test_initialization(self) -> None:
        """Test health checker initialization."""
        assert self.health_checker._registry is self.mock_registry
        assert self.health_checker._check_interval == self.check_interval
        assert self.health_checker._heartbeat_timeout == self.heartbeat_timeout
        assert self.health_checker._running is False
        assert self.health_checker._check_task is None

        # Verify event subscription
        self.mock_registry.subscribe_to_events.assert_called_once_with(
            ServiceEventType.INSTANCE_HEARTBEAT_UPDATED,
            self.health_checker._handle_heartbeat_event,
        )

    async def test_start_health_checker(self) -> None:
        """Test starting the health checker."""
        # Start the health checker
        await self.health_checker.start()

        assert self.health_checker._running is True
        assert self.health_checker._check_task is not None
        assert not self.health_checker._check_task.done()

        # Clean up
        await self.health_checker.stop()

    async def test_start_already_running(self) -> None:
        """Test starting health checker when already running."""
        # Start the health checker
        await self.health_checker.start()

        # Try to start again
        await self.health_checker.start()

        # Should still be running with same task
        assert self.health_checker._running is True

        # Clean up
        await self.health_checker.stop()

    async def test_stop_health_checker(self) -> None:
        """Test stopping the health checker."""
        # Start first
        await self.health_checker.start()
        task = self.health_checker._check_task

        # Stop
        await self.health_checker.stop()

        assert self.health_checker._running is False
        assert task.cancelled()

    async def test_stop_when_not_running(self) -> None:
        """Test stopping health checker when not running."""
        # Should not raise any error
        await self.health_checker.stop()
        assert self.health_checker._running is False

    async def test_check_all_services_no_services(self) -> None:
        """Test health check when no services are registered."""
        # Mock empty service list
        self.mock_registry.list_services.return_value = ServiceListResponse(
            services=[], total_count=0
        )

        await self.health_checker._check_all_services()

        self.mock_registry.list_services.assert_called_once()
        self.mock_registry.update_instance_status.assert_not_called()

    async def test_check_all_services_healthy_instances(self) -> None:
        """Test health check with all healthy instances."""
        now = datetime.now(UTC)

        # Create healthy instances
        instances = [
            ServiceInstanceInfo(
                instance_id="inst-1",
                status=ServiceStatus.ONLINE.value,
                registered_at=now,
                last_heartbeat=now,
                metadata={},
            ),
            ServiceInstanceInfo(
                instance_id="inst-2",
                status=ServiceStatus.ONLINE.value,
                registered_at=now,
                last_heartbeat=now - timedelta(seconds=1),  # Recent heartbeat
                metadata={},
            ),
        ]

        service = ServiceInfo(
            name="test-service",
            instances=instances,
            created_at=now,
        )
        self.mock_registry.list_services.return_value = ServiceListResponse(
            services=[service], total_count=1
        )

        await self.health_checker._check_all_services()

        # Should not update any instance status
        self.mock_registry.update_instance_status.assert_not_called()

    async def test_check_all_services_stale_heartbeat(self) -> None:
        """Test health check marks instances with stale heartbeat as unhealthy."""
        now = datetime.now(UTC)

        # Create instances with different heartbeat times
        instances = [
            ServiceInstanceInfo(
                instance_id="inst-1",
                status=ServiceStatus.ONLINE.value,
                registered_at=now,
                last_heartbeat=now,  # Fresh
                metadata={},
            ),
            ServiceInstanceInfo(
                instance_id="inst-2",
                status=ServiceStatus.ONLINE.value,
                registered_at=now - timedelta(seconds=10),
                last_heartbeat=now - timedelta(seconds=10),  # Stale
                metadata={},
            ),
        ]

        service = ServiceInfo(
            name="test-service",
            instances=instances,
            created_at=now,
        )
        self.mock_registry.list_services.return_value = ServiceListResponse(
            services=[service], total_count=1
        )

        await self.health_checker._check_all_services()

        # Should mark inst-2 as unhealthy
        self.mock_registry.update_instance_status.assert_called_once_with(
            "test-service", "inst-2", ServiceStatus.UNHEALTHY
        )

    async def test_check_all_services_no_heartbeat(self) -> None:
        """Test health check uses registration time when no heartbeat exists."""
        now = datetime.now(UTC)

        # Create instance without heartbeat
        instance = ServiceInstanceInfo(
            instance_id="inst-1",
            status="ONLINE",
            registered_at=now - timedelta(seconds=10),  # Old registration
            last_heartbeat=now - timedelta(seconds=10),  # Old heartbeat
            metadata={},
        )

        service = ServiceInfo(
            name="test-service",
            instances=[instance],
            created_at=now,
        )
        self.mock_registry.list_services.return_value = ServiceListResponse(
            services=[service], total_count=1
        )

        await self.health_checker._check_all_services()

        # Should mark as unhealthy due to old registration
        self.mock_registry.update_instance_status.assert_called_once_with(
            "test-service", "inst-1", ServiceStatus.UNHEALTHY
        )

    async def test_check_all_services_already_unhealthy(self) -> None:
        """Test health check doesn't update already unhealthy instances."""
        now = datetime.now(UTC)

        instance = ServiceInstanceInfo(
            instance_id="inst-1",
            status=ServiceStatus.UNHEALTHY.value,  # Already unhealthy
            registered_at=now - timedelta(seconds=10),
            last_heartbeat=now - timedelta(seconds=10),
            metadata={},
        )

        service = ServiceInfo(
            name="test-service",
            instances=[instance],
            created_at=now,
        )
        self.mock_registry.list_services.return_value = ServiceListResponse(
            services=[service], total_count=1
        )

        await self.health_checker._check_all_services()

        # Should not update status
        self.mock_registry.update_instance_status.assert_not_called()

    async def test_check_all_services_timezone_handling(self) -> None:
        """Test health check handles naive datetime objects."""
        now = datetime.now()  # Naive datetime

        instance = ServiceInstanceInfo(
            instance_id="inst-1",
            status="ONLINE",
            registered_at=now,
            last_heartbeat=now,  # Naive datetime
            metadata={},
        )

        service = ServiceInfo(
            name="test-service",
            instances=[instance],
            created_at=now,
        )
        self.mock_registry.list_services.return_value = ServiceListResponse(
            services=[service], total_count=1
        )

        # Should not raise any timezone errors
        await self.health_checker._check_all_services()

    async def test_mark_instance_unhealthy_success(self) -> None:
        """Test successfully marking instance as unhealthy."""
        await self.health_checker._mark_instance_unhealthy("test-service", "inst-1", 35.5)

        self.mock_registry.update_instance_status.assert_called_once_with(
            "test-service", "inst-1", ServiceStatus.UNHEALTHY
        )

    async def test_mark_instance_unhealthy_error(self) -> None:
        """Test error handling when marking instance unhealthy fails."""
        self.mock_registry.update_instance_status.side_effect = RuntimeError("Update failed")

        # Should not raise exception
        await self.health_checker._mark_instance_unhealthy("test-service", "inst-1", 35.5)

    async def test_handle_heartbeat_event(self) -> None:
        """Test handling heartbeat events."""
        from ipc_router.domain.events import ServiceEvent

        event = ServiceEvent(
            event_type=ServiceEventType.INSTANCE_HEARTBEAT_UPDATED,
            service_name="test-service",
            instance_id="inst-1",
            timestamp=datetime.now(UTC),
        )

        # Should not raise any error
        await self.health_checker._handle_heartbeat_event(event)

    async def test_check_instance_health_healthy(self) -> None:
        """Test checking health of a specific healthy instance."""
        now = datetime.now(UTC)

        # Mock get_service to return domain entity
        from ipc_router.domain.entities.service import Service, ServiceInstance

        instance = ServiceInstance(
            instance_id="inst-1",
            service_name="test-service",
            status=ServiceStatus.ONLINE,
            registered_at=now,
            last_heartbeat=now,
        )

        service = Service(name="test-service", instances=[instance])
        self.mock_registry.get_service.return_value = service

        result = await self.health_checker.check_instance_health("test-service", "inst-1")

        assert result is True

    async def test_check_instance_health_unhealthy_status(self) -> None:
        """Test checking health of instance with unhealthy status."""
        now = datetime.now(UTC)

        from ipc_router.domain.entities.service import Service, ServiceInstance

        instance = ServiceInstance(
            instance_id="inst-1",
            service_name="test-service",
            status=ServiceStatus.UNHEALTHY,
            registered_at=now,
            last_heartbeat=now,
        )

        service = Service(name="test-service", instances=[instance])
        self.mock_registry.get_service.return_value = service

        result = await self.health_checker.check_instance_health("test-service", "inst-1")

        assert result is False

    async def test_check_instance_health_stale_heartbeat(self) -> None:
        """Test checking health of instance with stale heartbeat."""
        now = datetime.now(UTC)

        from ipc_router.domain.entities.service import Service, ServiceInstance

        instance = ServiceInstance(
            instance_id="inst-1",
            service_name="test-service",
            status=ServiceStatus.ONLINE,
            registered_at=now,
            last_heartbeat=now - timedelta(seconds=10),  # Stale
        )

        service = Service(name="test-service", instances=[instance])
        self.mock_registry.get_service.return_value = service

        result = await self.health_checker.check_instance_health("test-service", "inst-1")

        assert result is False

    async def test_check_instance_health_not_found(self) -> None:
        """Test checking health of non-existent instance."""
        from ipc_router.domain.entities.service import Service

        service = Service(name="test-service", instances=[])
        self.mock_registry.get_service.return_value = service

        result = await self.health_checker.check_instance_health("test-service", "inst-1")

        assert result is False

    async def test_check_instance_health_error(self) -> None:
        """Test error handling in instance health check."""
        self.mock_registry.get_service.side_effect = RuntimeError("Service lookup failed")

        result = await self.health_checker.check_instance_health("test-service", "inst-1")

        assert result is False

    async def test_health_check_loop_continuous_operation(self) -> None:
        """Test health check loop runs continuously."""
        check_count = 0

        async def mock_check_all() -> None:
            nonlocal check_count
            check_count += 1
            if check_count >= 3:
                self.health_checker._running = False

        self.health_checker._running = True
        with (
            patch.object(self.health_checker, "_check_all_services", mock_check_all),
            patch("asyncio.sleep", return_value=asyncio.sleep(0)),
        ):
            await self.health_checker._health_check_loop()

        assert check_count == 3

    async def test_health_check_loop_error_recovery(self) -> None:
        """Test health check loop continues after errors."""
        check_count = 0

        async def mock_check_all() -> None:
            nonlocal check_count
            check_count += 1
            if check_count == 1:
                raise RuntimeError("Check failed")
            if check_count >= 3:
                self.health_checker._running = False

        self.health_checker._running = True
        with (
            patch.object(self.health_checker, "_check_all_services", mock_check_all),
            patch("asyncio.sleep", return_value=asyncio.sleep(0)),
        ):
            await self.health_checker._health_check_loop()

        assert check_count == 3  # Should continue after error

    async def test_health_check_loop_cancellation(self) -> None:
        """Test health check loop handles cancellation properly."""

        async def mock_check_all() -> None:
            await asyncio.sleep(0)

        with (
            patch.object(self.health_checker, "_check_all_services", mock_check_all),
            patch("asyncio.sleep", side_effect=asyncio.CancelledError),
        ):
            # Should exit cleanly
            await self.health_checker._health_check_loop()
