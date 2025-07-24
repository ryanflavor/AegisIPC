"""Unit tests for message metrics collection."""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
from ipc_router.infrastructure.monitoring import MessageMetricsCollector


class TestMessageMetricsCollector:
    """Test MessageMetricsCollector functionality."""

    @pytest.fixture
    def collector(self) -> MessageMetricsCollector:
        """Create a metrics collector instance."""
        return MessageMetricsCollector("test-service")

    def test_initialization(self, collector: MessageMetricsCollector) -> None:
        """Test metrics collector initialization."""
        assert collector.service_name == "test-service"
        assert collector._success_count == 0
        assert collector._failure_count == 0

    @patch("ipc_router.infrastructure.monitoring.metrics.messages_sent_total")
    def test_record_message_sent(
        self,
        mock_counter: Mock,
        collector: MessageMetricsCollector,
    ) -> None:
        """Test recording message sent."""
        collector.record_message_sent("test_method")

        mock_counter.labels.assert_called_once_with(
            service_name="test-service",
            method="test_method",
        )
        mock_counter.labels.return_value.inc.assert_called_once()

    @patch("ipc_router.infrastructure.monitoring.metrics.messages_acknowledged_total")
    @patch("ipc_router.infrastructure.monitoring.metrics.message_processing_duration")
    @patch("ipc_router.infrastructure.monitoring.metrics.message_delivery_success_rate")
    def test_record_acknowledgment_success(
        self,
        mock_success_rate: Mock,
        mock_duration: Mock,
        mock_ack_counter: Mock,
        collector: MessageMetricsCollector,
    ) -> None:
        """Test recording successful acknowledgment."""
        collector.record_acknowledgment("test_method", "success", 0.05)

        # Check counter was incremented
        mock_ack_counter.labels.assert_called_once_with(
            service_name="test-service",
            method="test_method",
            status="success",
        )
        mock_ack_counter.labels.return_value.inc.assert_called_once()

        # Check duration was recorded
        mock_duration.labels.assert_called_once_with(
            service_name="test-service",
            method="test_method",
        )
        mock_duration.labels.return_value.observe.assert_called_once_with(0.05)

        # Check success rate was updated
        mock_success_rate.labels.assert_called_once_with(
            service_name="test-service",
        )
        mock_success_rate.labels.return_value.set.assert_called_once_with(1.0)

        # Check internal counters
        assert collector._success_count == 1
        assert collector._failure_count == 0

    @patch("ipc_router.infrastructure.monitoring.metrics.messages_acknowledged_total")
    @patch("ipc_router.infrastructure.monitoring.metrics.message_delivery_success_rate")
    def test_record_acknowledgment_failure(
        self,
        mock_success_rate: Mock,
        mock_ack_counter: Mock,
        collector: MessageMetricsCollector,
    ) -> None:
        """Test recording failed acknowledgment."""
        collector.record_acknowledgment("test_method", "failure", 0.1)

        # Check counter was incremented
        mock_ack_counter.labels.assert_called_once_with(
            service_name="test-service",
            method="test_method",
            status="failure",
        )

        # Check success rate was updated
        mock_success_rate.labels.assert_called_once_with(
            service_name="test-service",
        )
        mock_success_rate.labels.return_value.set.assert_called_once_with(0.0)

        # Check internal counters
        assert collector._success_count == 0
        assert collector._failure_count == 1

    @patch("ipc_router.infrastructure.monitoring.metrics.messages_retried_total")
    def test_record_retry(
        self,
        mock_retry_counter: Mock,
        collector: MessageMetricsCollector,
    ) -> None:
        """Test recording message retry."""
        collector.record_retry("test_method", 2)

        mock_retry_counter.labels.assert_called_once_with(
            service_name="test-service",
            method="test_method",
            retry_count="2",
        )
        mock_retry_counter.labels.return_value.inc.assert_called_once()

    @patch("ipc_router.infrastructure.monitoring.metrics.messages_duplicates_total")
    def test_record_duplicate(
        self,
        mock_duplicate_counter: Mock,
        collector: MessageMetricsCollector,
    ) -> None:
        """Test recording duplicate message."""
        collector.record_duplicate("test_method", "msg-123")

        mock_duplicate_counter.labels.assert_called_once_with(
            service_name="test-service",
            method="test_method",
        )
        mock_duplicate_counter.labels.return_value.inc.assert_called_once()

    @patch("ipc_router.infrastructure.monitoring.metrics.acknowledgment_wait_duration")
    def test_record_acknowledgment_wait(
        self,
        mock_wait_histogram: Mock,
        collector: MessageMetricsCollector,
    ) -> None:
        """Test recording acknowledgment wait time."""
        collector.record_acknowledgment_wait("test_method", 2.5)

        mock_wait_histogram.labels.assert_called_once_with(
            service_name="test-service",
            method="test_method",
        )
        mock_wait_histogram.labels.return_value.observe.assert_called_once_with(2.5)

    @patch("ipc_router.infrastructure.monitoring.metrics.acknowledgment_timeout_total")
    @patch("ipc_router.infrastructure.monitoring.metrics.message_delivery_success_rate")
    def test_record_acknowledgment_timeout(
        self,
        mock_success_rate: Mock,
        mock_timeout_counter: Mock,
        collector: MessageMetricsCollector,
    ) -> None:
        """Test recording acknowledgment timeout."""
        collector.record_acknowledgment_timeout("test_method", "msg-456", 30.0)

        mock_timeout_counter.labels.assert_called_once_with(
            service_name="test-service",
            method="test_method",
        )
        mock_timeout_counter.labels.return_value.inc.assert_called_once()

        # Check failure count was incremented
        assert collector._failure_count == 1

    @patch("ipc_router.infrastructure.monitoring.metrics.message_delivery_failures_total")
    @patch("ipc_router.infrastructure.monitoring.metrics.message_delivery_success_rate")
    def test_record_delivery_failure(
        self,
        mock_success_rate: Mock,
        mock_failure_counter: Mock,
        collector: MessageMetricsCollector,
    ) -> None:
        """Test recording delivery failure."""
        collector.record_delivery_failure(
            "test_method",
            "timeout",
            "Request timed out",
        )

        mock_failure_counter.labels.assert_called_once_with(
            service_name="test-service",
            method="test_method",
            failure_type="timeout",
        )
        mock_failure_counter.labels.return_value.inc.assert_called_once()

        # Check failure count was incremented
        assert collector._failure_count == 1

    @patch("ipc_router.infrastructure.monitoring.metrics.message_cache_hit_ratio")
    @patch("ipc_router.infrastructure.monitoring.metrics.message_cache_size")
    def test_update_cache_metrics(
        self,
        mock_cache_size: Mock,
        mock_hit_ratio: Mock,
        collector: MessageMetricsCollector,
    ) -> None:
        """Test updating cache metrics."""
        collector.update_cache_metrics(0.85, 1000)

        mock_hit_ratio.labels.assert_called_once_with(
            service_name="test-service",
        )
        mock_hit_ratio.labels.return_value.set.assert_called_once_with(0.85)

        mock_cache_size.labels.assert_called_once_with(
            service_name="test-service",
        )
        mock_cache_size.labels.return_value.set.assert_called_once_with(1000)

    @patch("ipc_router.infrastructure.monitoring.metrics.message_cache_evictions_total")
    def test_record_cache_eviction(
        self,
        mock_eviction_counter: Mock,
        collector: MessageMetricsCollector,
    ) -> None:
        """Test recording cache eviction."""
        collector.record_cache_eviction("lru")

        mock_eviction_counter.labels.assert_called_once_with(
            service_name="test-service",
            reason="lru",
        )
        mock_eviction_counter.labels.return_value.inc.assert_called_once()

    @patch("ipc_router.infrastructure.monitoring.metrics.jetstream_messages_published")
    def test_record_jetstream_publish_success(
        self,
        mock_js_counter: Mock,
        collector: MessageMetricsCollector,
    ) -> None:
        """Test recording successful JetStream publish."""
        collector.record_jetstream_publish(
            "IPC_MESSAGES",
            "ipc.messages.test",
            True,
        )

        mock_js_counter.labels.assert_called_once_with(
            stream="IPC_MESSAGES",
            subject="ipc.messages.test",
        )
        mock_js_counter.labels.return_value.inc.assert_called_once()

    @patch("ipc_router.infrastructure.monitoring.metrics.jetstream_publish_errors")
    def test_record_jetstream_publish_error(
        self,
        mock_js_error_counter: Mock,
        collector: MessageMetricsCollector,
    ) -> None:
        """Test recording JetStream publish error."""
        collector.record_jetstream_publish(
            "IPC_MESSAGES",
            "ipc.messages.test",
            False,
            "connection_error",
        )

        mock_js_error_counter.labels.assert_called_once_with(
            stream="IPC_MESSAGES",
            error_type="connection_error",
        )
        mock_js_error_counter.labels.return_value.inc.assert_called_once()

    @patch("ipc_router.infrastructure.monitoring.metrics.message_delivery_success_rate")
    def test_success_rate_calculation(
        self,
        mock_success_rate: Mock,
        collector: MessageMetricsCollector,
    ) -> None:
        """Test success rate calculation."""
        # Record some successes and failures
        collector._success_count = 3
        collector._failure_count = 1
        collector._update_success_rate()

        # Should set rate to 0.75 (3/4)
        mock_success_rate.labels.assert_called_once_with(
            service_name="test-service",
        )
        mock_success_rate.labels.return_value.set.assert_called_once_with(0.75)

    def test_get_stats(self, collector: MessageMetricsCollector) -> None:
        """Test getting collector statistics."""
        collector._success_count = 10
        collector._failure_count = 2

        stats = collector.get_stats()

        assert stats["service_name"] == "test-service"
        assert stats["success_count"] == 10
        assert stats["failure_count"] == 2
        assert stats["success_rate"] == 10 / 12  # 0.833...
        assert "window_start" in stats
