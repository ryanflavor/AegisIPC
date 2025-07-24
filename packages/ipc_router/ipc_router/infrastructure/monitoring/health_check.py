"""Health check endpoint for message processing system."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from ipc_router.infrastructure.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ComponentHealth:
    """Health status of a system component."""

    name: str
    status: Literal["healthy", "degraded", "unhealthy"]
    message: str
    last_check: datetime
    metadata: dict[str, Any] | None = None


@dataclass
class SystemHealth:
    """Overall system health status."""

    status: Literal["healthy", "degraded", "unhealthy"]
    timestamp: datetime
    components: list[ComponentHealth]
    metrics: dict[str, Any]


class MessageHealthChecker:
    """Health checker for message processing system."""

    def __init__(
        self,
        cache_check_threshold: float = 0.3,
        delivery_rate_threshold: float = 0.9,
        max_retry_threshold: int = 100,
    ) -> None:
        """Initialize health checker.

        Args:
            cache_check_threshold: Minimum cache hit ratio for healthy status
            delivery_rate_threshold: Minimum delivery success rate for healthy
            max_retry_threshold: Maximum retries before marking unhealthy
        """
        self.cache_check_threshold = cache_check_threshold
        self.delivery_rate_threshold = delivery_rate_threshold
        self.max_retry_threshold = max_retry_threshold
        self._last_health_check = datetime.now(UTC)

    async def check_health(
        self,
        message_store: Any,
        cache: Any,
        metrics_collector: Any,
        nats_client: Any,
    ) -> SystemHealth:
        """Check overall system health.

        Args:
            message_store: Message store service
            cache: Message cache
            metrics_collector: Metrics collector
            nats_client: NATS client

        Returns:
            System health status
        """
        components = []
        now = datetime.now(UTC)

        # Check message store health
        store_health = await self._check_message_store(message_store)
        components.append(store_health)

        # Check cache health
        cache_health = self._check_cache(cache)
        components.append(cache_health)

        # Check delivery metrics health
        metrics_health = self._check_metrics(metrics_collector)
        components.append(metrics_health)

        # Check NATS connectivity
        nats_health = self._check_nats(nats_client)
        components.append(nats_health)

        # Determine overall status
        statuses = [c.status for c in components]
        overall_status: Literal["healthy", "degraded", "unhealthy"]
        if all(s == "healthy" for s in statuses):
            overall_status = "healthy"
        elif any(s == "unhealthy" for s in statuses):
            overall_status = "unhealthy"
        else:
            overall_status = "degraded"

        # Collect metrics
        metrics = {
            "cache_hit_ratio": cache.hit_rate if cache else 0.0,
            "cache_size": cache.size if cache else 0,
            "delivery_success_rate": (
                metrics_collector.get_stats()["success_rate"] if metrics_collector else 0.0
            ),
            "last_check_duration_ms": (datetime.now(UTC) - now).total_seconds() * 1000,
        }

        self._last_health_check = now

        return SystemHealth(
            status=overall_status,
            timestamp=now,
            components=components,
            metrics=metrics,
        )

    async def _check_message_store(self, message_store: Any) -> ComponentHealth:
        """Check message store health.

        Args:
            message_store: Message store service

        Returns:
            Component health status
        """
        try:
            if not message_store:
                return ComponentHealth(
                    name="message_store",
                    status="unhealthy",
                    message="Message store not available",
                    last_check=datetime.now(UTC),
                )

            # Check if we can perform basic operations
            store_size = await message_store.get_store_size()
            pending_count = await message_store.get_pending_count()

            # Check for concerning patterns
            if pending_count > 1000:
                return ComponentHealth(
                    name="message_store",
                    status="degraded",
                    message=f"High pending message count: {pending_count}",
                    last_check=datetime.now(UTC),
                    metadata={
                        "store_size": store_size,
                        "pending_count": pending_count,
                    },
                )

            return ComponentHealth(
                name="message_store",
                status="healthy",
                message="Message store operational",
                last_check=datetime.now(UTC),
                metadata={
                    "store_size": store_size,
                    "pending_count": pending_count,
                },
            )

        except Exception as e:
            logger.error("Message store health check failed", exc_info=e)
            return ComponentHealth(
                name="message_store",
                status="unhealthy",
                message=f"Health check failed: {e!s}",
                last_check=datetime.now(UTC),
            )

    def _check_cache(self, cache: Any) -> ComponentHealth:
        """Check cache health.

        Args:
            cache: Message cache

        Returns:
            Component health status
        """
        try:
            if not cache:
                return ComponentHealth(
                    name="message_cache",
                    status="unhealthy",
                    message="Cache not available",
                    last_check=datetime.now(UTC),
                )

            hit_rate = cache.hit_rate
            stats = cache.stats

            # Check cache effectiveness
            if hit_rate < self.cache_check_threshold:
                return ComponentHealth(
                    name="message_cache",
                    status="degraded",
                    message=f"Low cache hit rate: {hit_rate:.2%}",
                    last_check=datetime.now(UTC),
                    metadata=stats,
                )

            return ComponentHealth(
                name="message_cache",
                status="healthy",
                message=f"Cache operational (hit rate: {hit_rate:.2%})",
                last_check=datetime.now(UTC),
                metadata=stats,
            )

        except Exception as e:
            logger.error("Cache health check failed", exc_info=e)
            return ComponentHealth(
                name="message_cache",
                status="unhealthy",
                message=f"Health check failed: {e!s}",
                last_check=datetime.now(UTC),
            )

    def _check_metrics(self, metrics_collector: Any) -> ComponentHealth:
        """Check metrics health.

        Args:
            metrics_collector: Metrics collector

        Returns:
            Component health status
        """
        try:
            if not metrics_collector:
                return ComponentHealth(
                    name="metrics",
                    status="degraded",
                    message="Metrics collector not available",
                    last_check=datetime.now(UTC),
                )

            stats = metrics_collector.get_stats()
            success_rate = stats["success_rate"]

            # Check delivery success rate
            if success_rate < self.delivery_rate_threshold:
                return ComponentHealth(
                    name="metrics",
                    status="degraded",
                    message=f"Low delivery success rate: {success_rate:.2%}",
                    last_check=datetime.now(UTC),
                    metadata=stats,
                )

            return ComponentHealth(
                name="metrics",
                status="healthy",
                message=f"Metrics healthy (success rate: {success_rate:.2%})",
                last_check=datetime.now(UTC),
                metadata=stats,
            )

        except Exception as e:
            logger.error("Metrics health check failed", exc_info=e)
            return ComponentHealth(
                name="metrics",
                status="unhealthy",
                message=f"Health check failed: {e!s}",
                last_check=datetime.now(UTC),
            )

    def _check_nats(self, nats_client: Any) -> ComponentHealth:
        """Check NATS connectivity.

        Args:
            nats_client: NATS client

        Returns:
            Component health status
        """
        try:
            if not nats_client:
                return ComponentHealth(
                    name="nats",
                    status="unhealthy",
                    message="NATS client not available",
                    last_check=datetime.now(UTC),
                )

            if not nats_client.is_connected:
                return ComponentHealth(
                    name="nats",
                    status="unhealthy",
                    message="NATS client disconnected",
                    last_check=datetime.now(UTC),
                )

            # Check JetStream availability
            has_jetstream = getattr(nats_client, "has_jetstream", False)
            if not has_jetstream:
                return ComponentHealth(
                    name="nats",
                    status="degraded",
                    message="NATS connected but JetStream not available",
                    last_check=datetime.now(UTC),
                    metadata={"has_jetstream": False},
                )

            return ComponentHealth(
                name="nats",
                status="healthy",
                message="NATS fully operational",
                last_check=datetime.now(UTC),
                metadata={"has_jetstream": True},
            )

        except Exception as e:
            logger.error("NATS health check failed", exc_info=e)
            return ComponentHealth(
                name="nats",
                status="unhealthy",
                message=f"Health check failed: {e!s}",
                last_check=datetime.now(UTC),
            )

    def to_dict(self, health: SystemHealth) -> dict[str, Any]:
        """Convert health status to dictionary.

        Args:
            health: System health status

        Returns:
            Dictionary representation
        """
        return {
            "status": health.status,
            "timestamp": health.timestamp.isoformat(),
            "components": [
                {
                    "name": c.name,
                    "status": c.status,
                    "message": c.message,
                    "last_check": c.last_check.isoformat(),
                    "metadata": c.metadata,
                }
                for c in health.components
            ],
            "metrics": health.metrics,
        }
