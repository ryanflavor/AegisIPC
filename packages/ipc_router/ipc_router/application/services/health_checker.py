"""Health check service for monitoring service instances."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ipc_router.domain.enums import ServiceStatus
from ipc_router.domain.events import ServiceEventType
from ipc_router.infrastructure.logging import get_logger

if TYPE_CHECKING:
    from ipc_router.application.services.service_registry import ServiceRegistry
    from ipc_router.domain.events import ServiceEvent

logger = get_logger(__name__)


class HealthChecker:
    """Service for monitoring and updating health status of service instances.

    This service periodically checks instance heartbeats and marks instances
    as unhealthy when they exceed the timeout threshold.
    """

    def __init__(
        self,
        service_registry: ServiceRegistry,
        check_interval: float = 10.0,
        heartbeat_timeout: float = 30.0,
    ) -> None:
        """Initialize the health checker.

        Args:
            service_registry: Service registry to monitor
            check_interval: Interval between health checks in seconds
            heartbeat_timeout: Maximum seconds since last heartbeat to consider healthy
        """
        self._registry = service_registry
        self._check_interval = check_interval
        self._heartbeat_timeout = heartbeat_timeout
        self._running = False
        self._check_task: asyncio.Task[None] | None = None

        # Subscribe to service events to react to changes
        self._registry.subscribe_to_events(
            ServiceEventType.INSTANCE_HEARTBEAT_UPDATED,
            self._handle_heartbeat_event,
        )

        logger.info(
            "HealthChecker initialized",
            extra={
                "check_interval": check_interval,
                "heartbeat_timeout": heartbeat_timeout,
            },
        )

    async def start(self) -> None:
        """Start the health check background task."""
        if self._running:
            logger.warning("HealthChecker already running")
            return

        self._running = True
        self._check_task = asyncio.create_task(self._health_check_loop())
        logger.info("HealthChecker started")

    async def stop(self) -> None:
        """Stop the health check background task."""
        self._running = False

        if self._check_task and not self._check_task.done():
            self._check_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._check_task

        logger.info("HealthChecker stopped")

    async def _health_check_loop(self) -> None:
        """Main health check loop that runs periodically."""
        while self._running:
            try:
                await self._check_all_services()
                await asyncio.sleep(self._check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(
                    "Error in health check loop",
                    exc_info=e,
                )
                # Continue after error to maintain monitoring
                await asyncio.sleep(self._check_interval)

    async def _check_all_services(self) -> None:
        """Check health of all registered services."""
        services = await self._registry.list_services()
        total_checked = 0
        unhealthy_marked = 0

        for service_info in services.services:
            for instance in service_info.instances:
                total_checked += 1

                # Calculate time since last heartbeat
                now = datetime.now(UTC)
                if instance.last_heartbeat:
                    # Handle both naive and aware datetimes
                    last_hb = instance.last_heartbeat
                    if last_hb.tzinfo is None:
                        last_hb = last_hb.replace(tzinfo=UTC)
                    time_since_heartbeat = (now - last_hb).total_seconds()
                else:
                    # No heartbeat recorded, use registration time
                    reg_time = instance.registered_at
                    if reg_time.tzinfo is None:
                        reg_time = reg_time.replace(tzinfo=UTC)
                    time_since_heartbeat = (now - reg_time).total_seconds()

                # Check if instance should be marked unhealthy
                if (
                    instance.status == ServiceStatus.ONLINE.value
                    and time_since_heartbeat > self._heartbeat_timeout
                ):
                    await self._mark_instance_unhealthy(
                        service_info.name,
                        instance.instance_id,
                        time_since_heartbeat,
                    )
                    unhealthy_marked += 1

        if unhealthy_marked > 0:
            logger.warning(
                "Health check completed with unhealthy instances",
                extra={
                    "total_checked": total_checked,
                    "unhealthy_marked": unhealthy_marked,
                },
            )
        else:
            logger.debug(
                "Health check completed",
                extra={
                    "total_checked": total_checked,
                },
            )

    async def _mark_instance_unhealthy(
        self,
        service_name: str,
        instance_id: str,
        time_since_heartbeat: float,
    ) -> None:
        """Mark an instance as unhealthy due to heartbeat timeout.

        Args:
            service_name: Name of the service
            instance_id: ID of the instance
            time_since_heartbeat: Seconds since last heartbeat
        """
        try:
            await self._registry.update_instance_status(
                service_name,
                instance_id,
                ServiceStatus.UNHEALTHY,
            )

            logger.warning(
                "Marked instance as unhealthy due to heartbeat timeout",
                extra={
                    "service_name": service_name,
                    "instance_id": instance_id,
                    "time_since_heartbeat": time_since_heartbeat,
                    "timeout_threshold": self._heartbeat_timeout,
                },
            )

        except Exception as e:
            logger.error(
                "Failed to mark instance as unhealthy",
                exc_info=e,
                extra={
                    "service_name": service_name,
                    "instance_id": instance_id,
                },
            )

    async def _handle_heartbeat_event(self, event: ServiceEvent) -> None:
        """Handle heartbeat update events.

        This allows us to potentially mark instances as healthy again
        if they resume sending heartbeats.

        Args:
            event: The heartbeat event
        """
        # For now, we'll just log the event
        # In the future, we could implement recovery logic here
        logger.debug(
            "Received heartbeat event",
            extra={
                "service_name": event.service_name,
                "instance_id": event.instance_id,
            },
        )

    async def check_instance_health(
        self,
        service_name: str,
        instance_id: str,
    ) -> bool:
        """Check health of a specific instance.

        Args:
            service_name: Name of the service
            instance_id: ID of the instance

        Returns:
            True if instance is healthy, False otherwise
        """
        try:
            service = await self._registry.get_service(service_name)

            for instance in service.instances:
                if instance.instance_id == instance_id:
                    # Check status
                    if instance.status != ServiceStatus.ONLINE:
                        return False

                    # Check heartbeat
                    now = datetime.now(UTC)
                    last_hb = instance.last_heartbeat
                    if last_hb.tzinfo is None:
                        last_hb = last_hb.replace(tzinfo=UTC)

                    time_since_heartbeat: float = (now - last_hb).total_seconds()
                    result: bool = time_since_heartbeat <= self._heartbeat_timeout
                    return result

            # Instance not found
            return False

        except Exception as e:
            logger.error(
                "Error checking instance health",
                exc_info=e,
                extra={
                    "service_name": service_name,
                    "instance_id": instance_id,
                },
            )
            return False
