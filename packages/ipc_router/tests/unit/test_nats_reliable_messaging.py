"""Unit tests for NATS reliable messaging functionality."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest
from ipc_router.domain.exceptions import AcknowledgmentTimeoutError
from ipc_router.infrastructure.messaging.nats_client import NATSClient
from nats.js.api import PubAck, RetentionPolicy


class TestNATSClientReliableMessaging:
    """Test NATS client reliable messaging features."""

    @pytest.fixture
    def nats_client(self) -> NATSClient:
        """Create a NATS client instance."""
        return NATSClient(servers="nats://localhost:4222", name="test-client")

    @pytest.fixture
    def mock_nc(self) -> Mock:
        """Create a mock NATS connection."""
        mock = AsyncMock()
        mock.is_connected = True
        return mock

    @pytest.fixture
    def mock_js(self) -> Mock:
        """Create a mock JetStream context."""
        mock = AsyncMock()
        return mock

    async def test_request_with_ack_success(
        self,
        nats_client: NATSClient,
        mock_nc: Mock,
    ) -> None:
        """Test successful request with acknowledgment."""
        # Set up the client
        nats_client._nc = mock_nc
        nats_client._connected = True

        # Mock the request method to return response
        response_data = {"result": "success"}
        with patch.object(nats_client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = response_data

            # Mock subscribe for acknowledgment
            ack_callback = None

            async def capture_subscribe(subject: str, callback: Any, queue: Any = None) -> None:
                nonlocal ack_callback
                if subject.startswith("ipc.ack."):
                    ack_callback = callback

            with (
                patch.object(nats_client, "subscribe", side_effect=capture_subscribe),
                patch.object(nats_client, "unsubscribe", new_callable=AsyncMock),
            ):
                # Start the request
                request_task = asyncio.create_task(
                    nats_client.request_with_ack(
                        subject="test.service",
                        data={"test": "data"},
                        message_id="test-msg-123",
                        timeout=5.0,
                        ack_timeout=5.0,
                    )
                )

                # Give some time for subscription
                await asyncio.sleep(0.1)

                # Simulate acknowledgment
                assert ack_callback is not None
                await ack_callback(
                    {
                        "status": "success",
                        "processing_time_ms": 50.5,
                    },
                    None,
                )

                # Get the result
                result = await request_task
                assert result == response_data

    async def test_request_with_ack_timeout(
        self,
        nats_client: NATSClient,
        mock_nc: Mock,
    ) -> None:
        """Test request with acknowledgment timeout."""
        # Set up the client
        nats_client._nc = mock_nc
        nats_client._connected = True

        # Mock the request method to return response
        response_data = {"result": "success"}
        with patch.object(nats_client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = response_data

            # Mock subscribe but don't send ack
            with (
                patch.object(nats_client, "subscribe", new_callable=AsyncMock),
                patch.object(nats_client, "unsubscribe", new_callable=AsyncMock),
            ):
                # Request should timeout waiting for ack
                with pytest.raises(AcknowledgmentTimeoutError) as exc_info:
                    await nats_client.request_with_ack(
                        subject="test.service",
                        data={"test": "data"},
                        message_id="test-msg-123",
                        timeout=5.0,
                        ack_timeout=0.1,  # Short timeout for test
                    )

                assert exc_info.value.message_id == "test-msg-123"
                assert exc_info.value.service_name == "test.service"

    async def test_request_with_ack_failure(
        self,
        nats_client: NATSClient,
        mock_nc: Mock,
    ) -> None:
        """Test request with failed acknowledgment."""
        # Set up the client
        nats_client._nc = mock_nc
        nats_client._connected = True

        # Mock the request method to return response
        response_data = {"result": "success"}
        with patch.object(nats_client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = response_data

            # Mock subscribe for acknowledgment
            ack_callback = None

            async def capture_subscribe(subject: str, callback: Any, queue: Any = None) -> None:
                nonlocal ack_callback
                if subject.startswith("ipc.ack."):
                    ack_callback = callback

            with (
                patch.object(nats_client, "subscribe", side_effect=capture_subscribe),
                patch.object(nats_client, "unsubscribe", new_callable=AsyncMock),
            ):
                # Start the request
                request_task = asyncio.create_task(
                    nats_client.request_with_ack(
                        subject="test.service",
                        data={"test": "data"},
                        message_id="test-msg-123",
                        timeout=5.0,
                        ack_timeout=5.0,
                    )
                )

                # Give some time for subscription
                await asyncio.sleep(0.1)

                # Simulate failed acknowledgment
                assert ack_callback is not None
                await ack_callback(
                    {
                        "status": "failure",
                        "error_message": "Processing failed",
                    },
                    None,
                )

                # Should raise the ack error
                with pytest.raises(Exception, match="Acknowledgment failed: Processing failed"):
                    await request_task

    async def test_jetstream_initialization(
        self,
        nats_client: NATSClient,
        mock_nc: Mock,
        mock_js: Mock,
    ) -> None:
        """Test JetStream initialization."""
        # Mock JetStream methods
        mock_nc.jetstream.return_value = mock_js
        mock_js.add_stream = AsyncMock()

        # Set up the client
        nats_client._nc = mock_nc

        # Initialize JetStream
        await nats_client._initialize_jetstream()

        # Verify JetStream was created
        assert nats_client._js == mock_js
        mock_nc.jetstream.assert_called_once()
        mock_js.add_stream.assert_called_once()

        # Check stream config
        stream_config = mock_js.add_stream.call_args[0][0]
        assert stream_config.name == "IPC_MESSAGES"
        assert "ipc.messages.*" in stream_config.subjects
        assert "ipc.ack.*" in stream_config.subjects
        assert stream_config.retention == RetentionPolicy.WORK_QUEUE

    async def test_publish_with_jetstream(
        self,
        nats_client: NATSClient,
        mock_js: Mock,
    ) -> None:
        """Test publishing with JetStream."""
        # Set up JetStream
        nats_client._js = mock_js

        # Mock publish response
        pub_ack = PubAck(stream="IPC_MESSAGES", seq=1, duplicate=False)
        mock_js.publish = AsyncMock(return_value=pub_ack)

        # Publish message
        await nats_client.publish_with_jetstream(
            subject="ipc.messages.test",
            data={"test": "data"},
            message_id="test-msg-123",
            headers={"X-Custom": "header"},
        )

        # Verify publish was called
        mock_js.publish.assert_called_once()
        call_args = mock_js.publish.call_args
        assert call_args.kwargs["subject"] == "ipc.messages.test"
        assert call_args.kwargs["headers"]["Nats-Msg-Id"] == "test-msg-123"
        assert call_args.kwargs["headers"]["X-Custom"] == "header"

    async def test_publish_with_jetstream_fallback(
        self,
        nats_client: NATSClient,
        mock_nc: Mock,
    ) -> None:
        """Test publishing falls back to regular publish when JetStream not available."""
        # Set up without JetStream
        nats_client._nc = mock_nc
        nats_client._connected = True
        nats_client._js = None

        # Mock regular publish
        with patch.object(nats_client, "publish", new_callable=AsyncMock) as mock_publish:
            # Publish message
            await nats_client.publish_with_jetstream(
                subject="ipc.messages.test",
                data={"test": "data"},
                message_id="test-msg-123",
            )

            # Verify regular publish was called
            mock_publish.assert_called_once_with(
                subject="ipc.messages.test",
                data={"test": "data"},
                headers=None,
            )

    async def test_has_jetstream_property(
        self,
        nats_client: NATSClient,
        mock_js: Mock,
    ) -> None:
        """Test has_jetstream property."""
        # Initially no JetStream
        assert not nats_client.has_jetstream

        # With JetStream
        nats_client._js = mock_js
        assert nats_client.has_jetstream

        # After disconnect
        nats_client._js = None
        assert not nats_client.has_jetstream
