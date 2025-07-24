"""Metrics collection for reliable message delivery."""

from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime
from typing import Any

from prometheus_client import Counter, Gauge, Histogram

from ipc_router.infrastructure.logging import get_logger

logger = get_logger(__name__)

# Message delivery metrics
messages_sent_total = Counter(
    "ipc_messages_sent_total",
    "Total number of messages sent",
    ["service_name", "method"],
)

messages_acknowledged_total = Counter(
    "ipc_messages_acknowledged_total",
    "Total number of messages acknowledged",
    ["service_name", "method", "status"],
)

messages_retried_total = Counter(
    "ipc_messages_retried_total",
    "Total number of message retries",
    ["service_name", "method", "retry_count"],
)

messages_duplicates_total = Counter(
    "ipc_messages_duplicates_total",
    "Total number of duplicate messages detected",
    ["service_name", "method"],
)

# Timing metrics
message_processing_duration = Histogram(
    "ipc_message_processing_duration_seconds",
    "Message processing duration in seconds",
    ["service_name", "method"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

acknowledgment_wait_duration = Histogram(
    "ipc_acknowledgment_wait_duration_seconds",
    "Time spent waiting for acknowledgment in seconds",
    ["service_name", "method"],
    buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)

# Failure metrics
acknowledgment_timeout_total = Counter(
    "ipc_acknowledgment_timeout_total",
    "Total number of acknowledgment timeouts",
    ["service_name", "method"],
)

message_delivery_failures_total = Counter(
    "ipc_message_delivery_failures_total",
    "Total number of message delivery failures",
    ["service_name", "method", "failure_type"],
)

# Instance-level failure metrics
instance_routing_failures_total = Counter(
    "ipc_instance_routing_failures_total",
    "Total number of instance-level routing failures",
    ["service_name", "instance_id", "error_code"],
)

instance_routing_duration = Histogram(
    "ipc_instance_routing_duration_seconds",
    "Duration of routing to specific instances",
    ["service_name", "instance_id", "success"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

# Cache metrics
message_cache_hit_ratio = Gauge(
    "ipc_message_cache_hit_ratio",
    "Message cache hit ratio",
    ["service_name"],
)

message_cache_size = Gauge(
    "ipc_message_cache_size",
    "Current size of message cache",
    ["service_name"],
)

message_cache_evictions_total = Counter(
    "ipc_message_cache_evictions_total",
    "Total number of cache evictions",
    ["service_name", "reason"],
)

# Success rate metric
message_delivery_success_rate = Gauge(
    "ipc_message_delivery_success_rate",
    "Message delivery success rate (rolling window)",
    ["service_name"],
)

# JetStream metrics
jetstream_messages_published = Counter(
    "ipc_jetstream_messages_published_total",
    "Total messages published to JetStream",
    ["stream", "subject"],
)

jetstream_publish_errors = Counter(
    "ipc_jetstream_publish_errors_total",
    "Total JetStream publish errors",
    ["stream", "error_type"],
)


class MessageMetricsCollector:
    """Collects and tracks message delivery metrics."""

    def __init__(self, service_name: str) -> None:
        """Initialize metrics collector.

        Args:
            service_name: Name of the service
        """
        self.service_name = service_name
        self._success_count = 0
        self._failure_count = 0
        self._window_start = datetime.now(UTC)
        # Thread safety lock for protecting shared state
        self._lock = threading.Lock()
        # Also provide async lock for async contexts
        self._async_lock = asyncio.Lock()

    def record_message_sent(self, method: str) -> None:
        """Record that a message was sent.

        Args:
            method: Method name
        """
        messages_sent_total.labels(
            service_name=self.service_name,
            method=method,
        ).inc()

        logger.debug(
            "Message sent",
            extra={
                "service_name": self.service_name,
                "method": method,
                "metric": "messages_sent_total",
            },
        )

    def record_acknowledgment(
        self,
        method: str,
        status: str,
        processing_time_seconds: float,
    ) -> None:
        """Record message acknowledgment.

        Args:
            method: Method name
            status: Acknowledgment status (success/failure)
            processing_time_seconds: Processing time in seconds
        """
        messages_acknowledged_total.labels(
            service_name=self.service_name,
            method=method,
            status=status,
        ).inc()

        message_processing_duration.labels(
            service_name=self.service_name,
            method=method,
        ).observe(processing_time_seconds)

        # Update success rate with thread safety
        with self._lock:
            if status == "success":
                self._success_count += 1
            else:
                self._failure_count += 1

            self._update_success_rate()

        logger.info(
            "Message acknowledged",
            extra={
                "service_name": self.service_name,
                "method": method,
                "status": status,
                "processing_time_seconds": processing_time_seconds,
                "metric": "messages_acknowledged_total",
            },
        )

    def record_retry(self, method: str, retry_count: int) -> None:
        """Record message retry.

        Args:
            method: Method name
            retry_count: Current retry attempt number
        """
        messages_retried_total.labels(
            service_name=self.service_name,
            method=method,
            retry_count=str(retry_count),
        ).inc()

        logger.warning(
            "Message retry",
            extra={
                "service_name": self.service_name,
                "method": method,
                "retry_count": retry_count,
                "metric": "messages_retried_total",
            },
        )

    def record_duplicate(self, method: str, message_id: str) -> None:
        """Record duplicate message detection.

        Args:
            method: Method name
            message_id: Duplicate message ID
        """
        messages_duplicates_total.labels(
            service_name=self.service_name,
            method=method,
        ).inc()

        logger.info(
            "Duplicate message detected",
            extra={
                "service_name": self.service_name,
                "method": method,
                "message_id": message_id,
                "metric": "messages_duplicates_total",
            },
        )

    def record_acknowledgment_wait(
        self,
        method: str,
        wait_seconds: float,
    ) -> None:
        """Record acknowledgment wait time.

        Args:
            method: Method name
            wait_seconds: Time waited for acknowledgment
        """
        acknowledgment_wait_duration.labels(
            service_name=self.service_name,
            method=method,
        ).observe(wait_seconds)

    def record_acknowledgment_timeout(
        self,
        method: str,
        message_id: str,
        timeout_seconds: float,
    ) -> None:
        """Record acknowledgment timeout.

        Args:
            method: Method name
            message_id: Message ID that timed out
            timeout_seconds: Timeout duration
        """
        acknowledgment_timeout_total.labels(
            service_name=self.service_name,
            method=method,
        ).inc()

        with self._lock:
            self._failure_count += 1
            self._update_success_rate()

        logger.error(
            "Acknowledgment timeout",
            extra={
                "service_name": self.service_name,
                "method": method,
                "message_id": message_id,
                "timeout_seconds": timeout_seconds,
                "metric": "acknowledgment_timeout_total",
            },
        )

    def record_delivery_failure(
        self,
        method: str,
        failure_type: str,
        error_message: str,
    ) -> None:
        """Record message delivery failure.

        Args:
            method: Method name
            failure_type: Type of failure
            error_message: Error message
        """
        message_delivery_failures_total.labels(
            service_name=self.service_name,
            method=method,
            failure_type=failure_type,
        ).inc()

        with self._lock:
            self._failure_count += 1
            self._update_success_rate()

        logger.error(
            "Message delivery failure",
            extra={
                "service_name": self.service_name,
                "method": method,
                "failure_type": failure_type,
                "error_message": error_message,
                "metric": "message_delivery_failures_total",
            },
        )

    def update_cache_metrics(
        self,
        hit_ratio: float,
        cache_size: int,
    ) -> None:
        """Update cache-related metrics.

        Args:
            hit_ratio: Current cache hit ratio
            cache_size: Current cache size
        """
        message_cache_hit_ratio.labels(
            service_name=self.service_name,
        ).set(hit_ratio)

        message_cache_size.labels(
            service_name=self.service_name,
        ).set(cache_size)

    def record_cache_eviction(self, reason: str) -> None:
        """Record cache eviction.

        Args:
            reason: Eviction reason
        """
        message_cache_evictions_total.labels(
            service_name=self.service_name,
            reason=reason,
        ).inc()

    def record_jetstream_publish(
        self,
        stream: str,
        subject: str,
        success: bool,
        error_type: str | None = None,
    ) -> None:
        """Record JetStream publish event.

        Args:
            stream: JetStream stream name
            subject: Message subject
            success: Whether publish succeeded
            error_type: Type of error if failed
        """
        if success:
            jetstream_messages_published.labels(
                stream=stream,
                subject=subject,
            ).inc()
        else:
            jetstream_publish_errors.labels(
                stream=stream,
                error_type=error_type or "unknown",
            ).inc()

    def _update_success_rate(self) -> None:
        """Update the success rate metric.

        Note: This method assumes the caller already holds the lock.
        """
        total = self._success_count + self._failure_count
        if total > 0:
            rate = self._success_count / total
            message_delivery_success_rate.labels(
                service_name=self.service_name,
            ).set(rate)

            # Reset counters periodically (every hour)
            now = datetime.now(UTC)
            if (now - self._window_start).total_seconds() > 3600:
                self._success_count = 0
                self._failure_count = 0
                self._window_start = now

    async def record_acknowledgment_async(
        self,
        method: str,
        status: str,
        processing_time_seconds: float,
    ) -> None:
        """Record message acknowledgment (async version with proper locking).

        Args:
            method: Method name
            status: Acknowledgment status (success/failure)
            processing_time_seconds: Processing time in seconds
        """
        messages_acknowledged_total.labels(
            service_name=self.service_name,
            method=method,
            status=status,
        ).inc()

        message_processing_duration.labels(
            service_name=self.service_name,
            method=method,
        ).observe(processing_time_seconds)

        # Update success rate with proper locking
        async with self._async_lock:
            if status == "success":
                self._success_count += 1
            else:
                self._failure_count += 1

            # Update within the lock
            total = self._success_count + self._failure_count
            if total > 0:
                rate = self._success_count / total
                message_delivery_success_rate.labels(
                    service_name=self.service_name,
                ).set(rate)

                # Reset counters periodically (every hour)
                now = datetime.now(UTC)
                if (now - self._window_start).total_seconds() > 3600:
                    self._success_count = 0
                    self._failure_count = 0
                    self._window_start = now

        logger.info(
            "Message acknowledged",
            extra={
                "service_name": self.service_name,
                "method": method,
                "status": status,
                "processing_time_seconds": processing_time_seconds,
                "metric": "messages_acknowledged_total",
            },
        )

    async def record_acknowledgment_timeout_async(
        self,
        method: str,
        message_id: str,
        timeout_seconds: float,
    ) -> None:
        """Record acknowledgment timeout (async version with proper locking).

        Args:
            method: Method name
            message_id: Message ID that timed out
            timeout_seconds: Timeout duration
        """
        acknowledgment_timeout_total.labels(
            service_name=self.service_name,
            method=method,
        ).inc()

        async with self._async_lock:
            self._failure_count += 1

            # Update within the lock
            total = self._success_count + self._failure_count
            if total > 0:
                rate = self._success_count / total
                message_delivery_success_rate.labels(
                    service_name=self.service_name,
                ).set(rate)

                # Reset counters periodically (every hour)
                now = datetime.now(UTC)
                if (now - self._window_start).total_seconds() > 3600:
                    self._success_count = 0
                    self._failure_count = 0
                    self._window_start = now

        logger.error(
            "Acknowledgment timeout",
            extra={
                "service_name": self.service_name,
                "method": method,
                "message_id": message_id,
                "timeout_seconds": timeout_seconds,
                "metric": "acknowledgment_timeout_total",
            },
        )

    async def record_delivery_failure_async(
        self,
        method: str,
        failure_type: str,
        error_message: str,
    ) -> None:
        """Record message delivery failure (async version with proper locking).

        Args:
            method: Method name
            failure_type: Type of failure
            error_message: Error message
        """
        message_delivery_failures_total.labels(
            service_name=self.service_name,
            method=method,
            failure_type=failure_type,
        ).inc()

        async with self._async_lock:
            self._failure_count += 1

            # Update within the lock
            total = self._success_count + self._failure_count
            if total > 0:
                rate = self._success_count / total
                message_delivery_success_rate.labels(
                    service_name=self.service_name,
                ).set(rate)

                # Reset counters periodically (every hour)
                now = datetime.now(UTC)
                if (now - self._window_start).total_seconds() > 3600:
                    self._success_count = 0
                    self._failure_count = 0
                    self._window_start = now

        logger.error(
            "Message delivery failure",
            extra={
                "service_name": self.service_name,
                "method": method,
                "failure_type": failure_type,
                "error_message": error_message,
                "metric": "message_delivery_failures_total",
            },
        )

    def get_stats(self) -> dict[str, Any]:
        """Get current metrics statistics.

        Returns:
            Dictionary of current metrics
        """
        with self._lock:
            total = self._success_count + self._failure_count
            success_rate = self._success_count / total if total > 0 else 0.0

            return {
                "service_name": self.service_name,
                "success_count": self._success_count,
                "failure_count": self._failure_count,
                "success_rate": success_rate,
                "window_start": self._window_start.isoformat(),
            }

    async def get_stats_async(self) -> dict[str, Any]:
        """Get current metrics statistics (async version).

        Returns:
            Dictionary of current metrics
        """
        async with self._async_lock:
            total = self._success_count + self._failure_count
            success_rate = self._success_count / total if total > 0 else 0.0

            return {
                "service_name": self.service_name,
                "success_count": self._success_count,
                "failure_count": self._failure_count,
                "success_rate": success_rate,
                "window_start": self._window_start.isoformat(),
            }
