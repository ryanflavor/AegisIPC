"""Unit tests for ServiceClient reliable messaging functionality."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import msgpack
import pytest
from ipc_client_sdk.clients.service_client import (
    AcknowledgmentTimeoutError,
    ReliableDeliveryConfig,
    ServiceClient,
)


class TestServiceClientReliableMessaging:
    """Test ServiceClient reliable messaging features."""

    @pytest.fixture
    def service_client(self) -> ServiceClient:
        """Create a ServiceClient instance."""
        return ServiceClient(nats_url="nats://localhost:4222")

    @pytest.fixture
    def mock_nats_client(self) -> Mock:
        """Create a mock NATS client."""
        mock = Mock()
        mock.is_connected = True
        mock.request = AsyncMock()
        mock.publish = AsyncMock()
        mock._nc = Mock()
        mock._nc.subscribe = AsyncMock()
        return mock

    async def test_call_with_message_id(
        self,
        service_client: ServiceClient,
        mock_nats_client: Mock,
    ) -> None:
        """Test that call method generates message_id."""
        service_client._nats_client = mock_nats_client

        # Mock successful response
        mock_nats_client.request.return_value = {
            "success": True,
            "result": {"data": "test"},
        }

        # Make a call
        result = await service_client.call(
            service_name="test-service",
            method="test_method",
            params={"key": "value"},
        )

        # Verify request was made with message_id
        mock_nats_client.request.assert_called_once()
        call_args = mock_nats_client.request.call_args
        request_data = call_args.args[1]

        assert "message_id" in request_data
        assert len(request_data["message_id"]) == 36  # UUID format
        assert result == {"data": "test"}

    async def test_call_reliable_success(
        self,
        service_client: ServiceClient,
        mock_nats_client: Mock,
    ) -> None:
        """Test successful reliable call with acknowledgment."""
        service_client._nats_client = mock_nats_client

        # Mock successful response
        mock_nats_client.request.return_value = {
            "success": True,
            "result": {"data": "reliable_test"},
        }

        # Mock subscription for acknowledgment
        mock_subscription = Mock()
        mock_subscription.unsubscribe = AsyncMock()
        mock_nats_client._nc.subscribe.return_value = mock_subscription

        # Capture the ack handler
        ack_handler = None

        async def capture_subscribe(subject: str, cb: Any) -> Mock:
            nonlocal ack_handler
            if subject.startswith("ipc.ack."):
                ack_handler = cb
            return mock_subscription

        mock_nats_client._nc.subscribe.side_effect = capture_subscribe

        # Start the reliable call
        call_task = asyncio.create_task(
            service_client.call_reliable(
                service_name="test-service",
                method="test_method",
                params={"key": "value"},
                delivery_config=ReliableDeliveryConfig(
                    require_ack=True,
                    ack_timeout=5.0,
                ),
            )
        )

        # Give some time for subscription
        await asyncio.sleep(0.1)

        # Simulate acknowledgment
        assert ack_handler is not None
        ack_msg = Mock()
        ack_msg.data = msgpack.packb({"status": "success"})
        await ack_handler(ack_msg)

        # Get the result
        result = await call_task
        assert result == {"data": "reliable_test"}

        # Verify subscription was cleaned up
        mock_subscription.unsubscribe.assert_called_once()

    async def test_call_reliable_ack_timeout(
        self,
        service_client: ServiceClient,
        mock_nats_client: Mock,
    ) -> None:
        """Test reliable call with acknowledgment timeout."""
        service_client._nats_client = mock_nats_client

        # Mock successful response
        mock_nats_client.request.return_value = {
            "success": True,
            "result": {"data": "test"},
        }

        # Mock subscription but don't send ack
        mock_subscription = Mock()
        mock_subscription.unsubscribe = AsyncMock()
        mock_nats_client._nc.subscribe.return_value = mock_subscription

        # Test should timeout waiting for ack
        with pytest.raises(AcknowledgmentTimeoutError) as exc_info:
            await service_client.call_reliable(
                service_name="test-service",
                method="test_method",
                params={"key": "value"},
                delivery_config=ReliableDeliveryConfig(
                    require_ack=True,
                    ack_timeout=0.1,  # Short timeout for test
                ),
            )

        assert "Acknowledgment timeout" in str(exc_info.value)
        assert exc_info.value.service_name == "test-service"

    async def test_call_reliable_retry_on_timeout(
        self,
        service_client: ServiceClient,
        mock_nats_client: Mock,
    ) -> None:
        """Test reliable call retries on timeout."""
        service_client._nats_client = mock_nats_client

        # First two calls timeout, third succeeds
        mock_nats_client.request.side_effect = [
            None,  # First timeout
            None,  # Second timeout
            {"success": True, "result": {"data": "success"}},  # Success
        ]

        # Mock subscription
        mock_subscription = Mock()
        mock_subscription.unsubscribe = AsyncMock()
        mock_nats_client._nc.subscribe.return_value = mock_subscription

        # Make reliable call with retries
        result = await service_client.call_reliable(
            service_name="test-service",
            method="test_method",
            params={"key": "value"},
            delivery_config=ReliableDeliveryConfig(
                require_ack=False,  # No ack for simplicity
                max_retries=2,
                retry_delay=0.1,
            ),
        )

        assert result == {"data": "success"}
        assert mock_nats_client.request.call_count == 3

    async def test_call_reliable_without_ack(
        self,
        service_client: ServiceClient,
        mock_nats_client: Mock,
    ) -> None:
        """Test reliable call without acknowledgment requirement."""
        service_client._nats_client = mock_nats_client

        # Mock successful response
        mock_nats_client.request.return_value = {
            "success": True,
            "result": {"data": "no_ack_test"},
        }

        # Make reliable call without ack
        result = await service_client.call_reliable(
            service_name="test-service",
            method="test_method",
            params={"key": "value"},
            delivery_config=ReliableDeliveryConfig(
                require_ack=False,
            ),
        )

        assert result == {"data": "no_ack_test"}
        # Should not create any subscriptions
        mock_nats_client._nc.subscribe.assert_not_called()

    async def test_send_acknowledgment(
        self,
        service_client: ServiceClient,
        mock_nats_client: Mock,
    ) -> None:
        """Test sending acknowledgment."""
        service_client._nats_client = mock_nats_client

        # Send acknowledgment
        await service_client.send_acknowledgment(
            message_id="test-msg-123",
            service_name="test-service",
            status="success",
            processing_time_ms=50.5,
        )

        # Verify publish was called
        mock_nats_client.publish.assert_called_once()
        call_args = mock_nats_client.publish.call_args
        assert call_args.args[0] == "ipc.ack.test-msg-123"

        ack_data = call_args.args[1]
        assert ack_data["message_id"] == "test-msg-123"
        assert ack_data["status"] == "success"
        assert ack_data["processing_time_ms"] == 50.5

    async def test_send_acknowledgment_failure(
        self,
        service_client: ServiceClient,
        mock_nats_client: Mock,
    ) -> None:
        """Test sending failure acknowledgment."""
        service_client._nats_client = mock_nats_client

        # Send failure acknowledgment
        await service_client.send_acknowledgment(
            message_id="test-msg-456",
            service_name="test-service",
            status="failure",
            error_message="Processing failed",
            processing_time_ms=10.0,
        )

        # Verify publish was called with failure data
        mock_nats_client.publish.assert_called_once()
        call_args = mock_nats_client.publish.call_args
        ack_data = call_args.args[1]
        assert ack_data["status"] == "failure"
        assert ack_data["error_message"] == "Processing failed"

    async def test_query_message_status(
        self,
        service_client: ServiceClient,
        mock_nats_client: Mock,
    ) -> None:
        """Test querying message status."""
        service_client._nats_client = mock_nats_client

        # Mock status response
        mock_nats_client.request.return_value = {
            "message_id": "test-msg-123",
            "state": "acknowledged",
            "retry_count": 0,
            "created_at": "2025-07-23T10:00:00Z",
        }

        # Query status
        status = await service_client.query_message_status("test-msg-123")

        # Verify request
        mock_nats_client.request.assert_called_once()
        call_args = mock_nats_client.request.call_args
        assert call_args.args[0] == "ipc.message.status"
        assert call_args.args[1]["message_id"] == "test-msg-123"

        assert status["state"] == "acknowledged"

    async def test_query_message_status_timeout(
        self,
        service_client: ServiceClient,
        mock_nats_client: Mock,
    ) -> None:
        """Test message status query timeout."""
        service_client._nats_client = mock_nats_client

        # Mock timeout
        mock_nats_client.request.return_value = None

        # Query should timeout
        with pytest.raises(TimeoutError, match="Message status query timed out"):
            await service_client.query_message_status("test-msg-789")

    async def test_reliable_delivery_config_defaults(self) -> None:
        """Test ReliableDeliveryConfig default values."""
        config = ReliableDeliveryConfig()

        assert config.require_ack is True
        assert config.ack_timeout == 30.0
        assert config.max_retries == 3
        assert config.retry_delay == 1.0
        assert config.retry_multiplier == 2.0

    async def test_reliable_delivery_exponential_backoff(
        self,
        service_client: ServiceClient,
        mock_nats_client: Mock,
    ) -> None:
        """Test exponential backoff in reliable delivery."""
        service_client._nats_client = mock_nats_client

        # All calls timeout to test retry delays
        mock_nats_client.request.return_value = None

        # Track sleep calls
        sleep_delays = []

        async def mock_sleep(delay: float) -> None:
            sleep_delays.append(delay)

        with patch("asyncio.sleep", side_effect=mock_sleep), pytest.raises(TimeoutError):
            await service_client.call_reliable(
                service_name="test-service",
                method="test_method",
                delivery_config=ReliableDeliveryConfig(
                    require_ack=False,
                    max_retries=3,
                    retry_delay=1.0,
                    retry_multiplier=2.0,
                ),
            )

        # Verify exponential backoff
        assert len(sleep_delays) == 3
        assert sleep_delays[0] == 1.0
        assert sleep_delays[1] == 2.0
        assert sleep_delays[2] == 4.0
