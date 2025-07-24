"""Performance analysis for message processing."""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from ipc_router.infrastructure.logging import get_logger

logger = get_logger(__name__)


@dataclass
class PerformanceMetric:
    """Performance metric data point."""

    timestamp: datetime
    value: float
    method: str | None = None
    service_name: str | None = None


@dataclass
class PerformanceStats:
    """Performance statistics."""

    metric_name: str
    count: int
    mean: float
    min: float
    max: float
    p50: float
    p95: float
    p99: float
    window_seconds: float


class MessagePerformanceAnalyzer:
    """Analyzes message processing performance."""

    def __init__(
        self,
        window_size: int = 1000,
        time_window_seconds: float = 300.0,  # 5 minutes
    ) -> None:
        """Initialize performance analyzer.

        Args:
            window_size: Maximum number of data points to keep
            time_window_seconds: Time window for analysis
        """
        self.window_size = window_size
        self.time_window_seconds = time_window_seconds

        # Store metrics by type
        self._metrics: dict[str, deque[PerformanceMetric]] = defaultdict(
            lambda: deque(maxlen=window_size)
        )

        # Track method-specific performance
        self._method_metrics: dict[str, dict[str, deque[PerformanceMetric]]] = defaultdict(
            lambda: defaultdict(lambda: deque(maxlen=window_size))
        )

        # Lock for thread safety
        self._lock = asyncio.Lock()

    async def record_processing_time(
        self,
        service_name: str,
        method: str,
        duration_seconds: float,
    ) -> None:
        """Record message processing time.

        Args:
            service_name: Service name
            method: Method name
            duration_seconds: Processing duration in seconds
        """
        async with self._lock:
            metric = PerformanceMetric(
                timestamp=datetime.now(UTC),
                value=duration_seconds,
                method=method,
                service_name=service_name,
            )

            # Store in general metrics
            self._metrics["processing_time"].append(metric)

            # Store in method-specific metrics
            key = f"{service_name}.{method}"
            self._method_metrics["processing_time"][key].append(metric)

        logger.debug(
            "Recorded processing time",
            extra={
                "service_name": service_name,
                "method": method,
                "duration_seconds": duration_seconds,
            },
        )

    async def record_acknowledgment_time(
        self,
        service_name: str,
        method: str,
        duration_seconds: float,
    ) -> None:
        """Record acknowledgment wait time.

        Args:
            service_name: Service name
            method: Method name
            duration_seconds: Acknowledgment wait time in seconds
        """
        async with self._lock:
            metric = PerformanceMetric(
                timestamp=datetime.now(UTC),
                value=duration_seconds,
                method=method,
                service_name=service_name,
            )

            # Store in general metrics
            self._metrics["acknowledgment_time"].append(metric)

            # Store in method-specific metrics
            key = f"{service_name}.{method}"
            self._method_metrics["acknowledgment_time"][key].append(metric)

    async def record_retry_count(
        self,
        service_name: str,
        method: str,
        retry_count: int,
    ) -> None:
        """Record retry count for a message.

        Args:
            service_name: Service name
            method: Method name
            retry_count: Number of retries
        """
        async with self._lock:
            metric = PerformanceMetric(
                timestamp=datetime.now(UTC),
                value=float(retry_count),
                method=method,
                service_name=service_name,
            )

            self._metrics["retry_count"].append(metric)

            key = f"{service_name}.{method}"
            self._method_metrics["retry_count"][key].append(metric)

    async def get_stats(
        self,
        metric_name: str,
        service_method: str | None = None,
    ) -> PerformanceStats | None:
        """Get performance statistics for a metric.

        Args:
            metric_name: Name of the metric
            service_method: Optional service.method filter

        Returns:
            Performance statistics or None if no data
        """
        async with self._lock:
            # Get the appropriate metrics
            if service_method:
                metrics = self._method_metrics.get(metric_name, {}).get(service_method, deque())
            else:
                metrics = self._metrics.get(metric_name, deque())

            if not metrics:
                return None

            # Filter by time window
            cutoff_time = datetime.now(UTC) - timedelta(seconds=self.time_window_seconds)
            recent_metrics = [m for m in metrics if m.timestamp > cutoff_time]

            if not recent_metrics:
                return None

            # Calculate statistics
            values = sorted([m.value for m in recent_metrics])
            count = len(values)

            return PerformanceStats(
                metric_name=metric_name,
                count=count,
                mean=sum(values) / count,
                min=values[0],
                max=values[-1],
                p50=self._percentile(values, 0.5),
                p95=self._percentile(values, 0.95),
                p99=self._percentile(values, 0.99),
                window_seconds=self.time_window_seconds,
            )

    async def get_performance_report(self) -> dict[str, Any]:
        """Get comprehensive performance report.

        Returns:
            Performance report with all metrics
        """
        report: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "window_seconds": self.time_window_seconds,
            "overall_metrics": {},
            "method_metrics": {},
            "performance_issues": [],
        }

        # Get overall metrics
        for metric_name in ["processing_time", "acknowledgment_time", "retry_count"]:
            stats = await self.get_stats(metric_name)
            if stats:
                report["overall_metrics"][metric_name] = {
                    "count": stats.count,
                    "mean": stats.mean,
                    "min": stats.min,
                    "max": stats.max,
                    "p50": stats.p50,
                    "p95": stats.p95,
                    "p99": stats.p99,
                }

        # Get method-specific metrics
        async with self._lock:
            for metric_name, method_data in self._method_metrics.items():
                for service_method in method_data:
                    stats = await self.get_stats(metric_name, service_method)
                    if stats:
                        if service_method not in report["method_metrics"]:
                            report["method_metrics"][service_method] = {}

                        report["method_metrics"][service_method][metric_name] = {
                            "count": stats.count,
                            "mean": stats.mean,
                            "p95": stats.p95,
                            "p99": stats.p99,
                        }

        # Identify performance issues
        issues = await self._identify_performance_issues()
        report["performance_issues"] = issues

        return report

    async def _identify_performance_issues(self) -> list[dict[str, Any]]:
        """Identify potential performance issues.

        Returns:
            List of identified issues
        """
        issues = []

        # Check for slow processing times
        processing_stats = await self.get_stats("processing_time")
        if processing_stats and processing_stats.p95 > 1.0:  # > 1 second
            issues.append(
                {
                    "type": "slow_processing",
                    "severity": "high",
                    "message": f"High processing time: p95={processing_stats.p95:.3f}s",
                    "metrics": {
                        "p95": processing_stats.p95,
                        "p99": processing_stats.p99,
                    },
                }
            )

        # Check for high retry rates
        retry_stats = await self.get_stats("retry_count")
        if retry_stats and retry_stats.mean > 1.0:
            issues.append(
                {
                    "type": "high_retry_rate",
                    "severity": "medium",
                    "message": f"High retry rate: avg={retry_stats.mean:.2f}",
                    "metrics": {
                        "mean": retry_stats.mean,
                        "max": retry_stats.max,
                    },
                }
            )

        # Check for slow acknowledgments
        ack_stats = await self.get_stats("acknowledgment_time")
        if ack_stats and ack_stats.p95 > 5.0:  # > 5 seconds
            issues.append(
                {
                    "type": "slow_acknowledgment",
                    "severity": "medium",
                    "message": f"Slow acknowledgment: p95={ack_stats.p95:.3f}s",
                    "metrics": {
                        "p95": ack_stats.p95,
                        "p99": ack_stats.p99,
                    },
                }
            )

        return issues

    @staticmethod
    def _percentile(sorted_values: list[float], percentile: float) -> float:
        """Calculate percentile from sorted values.

        Args:
            sorted_values: Sorted list of values
            percentile: Percentile to calculate (0.0-1.0)

        Returns:
            Percentile value
        """
        if not sorted_values:
            return 0.0

        index = int(percentile * (len(sorted_values) - 1))
        return sorted_values[index]

    async def cleanup_old_metrics(self) -> int:
        """Clean up metrics older than the time window.

        Returns:
            Number of metrics cleaned up
        """
        async with self._lock:
            cutoff_time = datetime.now(UTC) - timedelta(seconds=self.time_window_seconds)
            total_cleaned = 0

            # Clean general metrics
            for metric_deque in self._metrics.values():
                old_count = len(metric_deque)
                # Keep only recent metrics
                while metric_deque and metric_deque[0].timestamp < cutoff_time:
                    metric_deque.popleft()
                total_cleaned += old_count - len(metric_deque)

            # Clean method-specific metrics
            for method_dict in self._method_metrics.values():
                for metric_deque in method_dict.values():
                    old_count = len(metric_deque)
                    while metric_deque and metric_deque[0].timestamp < cutoff_time:
                        metric_deque.popleft()
                    total_cleaned += old_count - len(metric_deque)

        if total_cleaned > 0:
            logger.info(
                "Cleaned up old metrics",
                extra={"metrics_cleaned": total_cleaned},
            )

        return total_cleaned
