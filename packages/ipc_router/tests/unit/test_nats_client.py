"""Unit tests for NATS client infrastructure."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from ipc_router.infrastructure.messaging.nats_client import NATSClient


@pytest.fixture
def nats_config() -> dict[str, Any]:
    """Create a test NATS configuration."""
    return {
        "servers": "nats://localhost:4222",
        "name": "test-client",
        "max_reconnect_attempts": 3,
        "reconnect_time_wait": 1,
    }


@pytest.fixture
def mock_nats_connection() -> AsyncMock:
    """Create a mock NATS connection."""
    mock_conn = AsyncMock()
    mock_conn.is_connected = True
    mock_conn.drain = AsyncMock()
    mock_conn.close = AsyncMock()
    mock_conn.publish = AsyncMock()
    mock_conn.subscribe = AsyncMock()
    mock_conn.request = AsyncMock()
    return mock_conn


class TestNATSClient:
    """Test cases for NATSClient."""

    @pytest.mark.asyncio
    async def test_connect_success(
        self, nats_config: dict[str, Any], mock_nats_connection: AsyncMock
    ) -> None:
        """Test successful connection to NATS."""
        with patch("nats.connect", return_value=mock_nats_connection) as mock_connect:
            client = NATSClient(**nats_config)
            await client.connect()

            mock_connect.assert_called_once_with(
                servers=[nats_config["servers"]],
                name=nats_config["name"],
                max_reconnect_attempts=nats_config["max_reconnect_attempts"],
                reconnect_time_wait=nats_config["reconnect_time_wait"],
                error_cb=client._error_callback,
                disconnected_cb=client._disconnected_callback,
                reconnected_cb=client._reconnected_callback,
                closed_cb=client._closed_callback,
            )
            assert client._nc == mock_nats_connection

    @pytest.mark.asyncio
    async def test_connect_failure(self, nats_config: dict[str, Any]) -> None:
        """Test connection failure handling."""
        with patch("nats.connect", side_effect=Exception("Connection failed")):
            client = NATSClient(**nats_config)
            with pytest.raises(Exception) as exc_info:
                await client.connect()
            assert "Connection failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_disconnect(
        self, nats_config: dict[str, Any], mock_nats_connection: AsyncMock
    ) -> None:
        """Test disconnection from NATS."""
        with patch("nats.connect", return_value=mock_nats_connection):
            client = NATSClient(**nats_config)
            await client.connect()
            await client.disconnect()

            mock_nats_connection.close.assert_called_once()
            assert not client.is_connected

    @pytest.mark.asyncio
    async def test_disconnect_when_not_connected(self, nats_config: dict[str, Any]) -> None:
        """Test disconnection when not connected."""
        client = NATSClient(**nats_config)
        # Should not raise error
        await client.disconnect()

    @pytest.mark.asyncio
    async def test_publish_success(
        self, nats_config: dict[str, Any], mock_nats_connection: AsyncMock
    ) -> None:
        """Test successful message publishing."""
        with patch("nats.connect", return_value=mock_nats_connection):
            client = NATSClient(**nats_config)
            await client.connect()

            subject = "test.subject"
            data = {"test": "data"}
            await client.publish(subject, data)

            # Data should be msgpack encoded
            import msgpack

            expected_data = msgpack.packb(data, use_bin_type=True)
            mock_nats_connection.publish.assert_called_once_with(
                subject=subject, payload=expected_data, headers=None
            )

    @pytest.mark.asyncio
    async def test_publish_when_not_connected(self, nats_config: dict[str, Any]) -> None:
        """Test publishing when not connected."""
        from ipc_router.domain.exceptions import ConnectionError as IPCConnectionError

        client = NATSClient(**nats_config)
        with pytest.raises(IPCConnectionError) as exc_info:
            await client.publish("test.subject", {"test": "data"})
        assert "Not connected" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_subscribe_success(
        self, nats_config: dict[str, Any], mock_nats_connection: AsyncMock
    ) -> None:
        """Test successful subscription."""
        mock_subscription = AsyncMock()
        mock_nats_connection.subscribe.return_value = mock_subscription

        with patch("nats.connect", return_value=mock_nats_connection):
            client = NATSClient(**nats_config)
            await client.connect()

            handler = AsyncMock()
            subject = "test.subject"

            # subscribe method doesn't return anything
            await client.subscribe(subject, handler)

            mock_nats_connection.subscribe.assert_called_once()
            assert subject in client._subscriptions

    @pytest.mark.asyncio
    async def test_subscribe_when_not_connected(self, nats_config: dict[str, Any]) -> None:
        """Test subscription when not connected."""
        from ipc_router.domain.exceptions import ConnectionError as IPCConnectionError

        client = NATSClient(**nats_config)
        handler = AsyncMock()
        with pytest.raises(IPCConnectionError) as exc_info:
            await client.subscribe("test.subject", handler)
        assert "Not connected" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_request_success(
        self, nats_config: dict[str, Any], mock_nats_connection: AsyncMock
    ) -> None:
        """Test successful request/response."""
        import msgpack

        mock_response = MagicMock()
        response_data = {"result": "success"}
        mock_response.data = msgpack.packb(response_data)
        mock_nats_connection.request.return_value = mock_response

        with patch("nats.connect", return_value=mock_nats_connection):
            client = NATSClient(**nats_config)
            await client.connect()

            subject = "test.subject"
            request_data = {"action": "test"}
            response = await client.request(subject, request_data, timeout=5)

            # Request data should be msgpack encoded
            expected_data = msgpack.packb(request_data, use_bin_type=True)
            mock_nats_connection.request.assert_called_once_with(
                subject=subject, payload=expected_data, timeout=5, headers=None
            )
            assert response == response_data

    @pytest.mark.asyncio
    async def test_request_timeout(
        self, nats_config: dict[str, Any], mock_nats_connection: AsyncMock
    ) -> None:
        """Test request timeout handling."""
        mock_nats_connection.request.side_effect = TimeoutError()

        with patch("nats.connect", return_value=mock_nats_connection):
            client = NATSClient(**nats_config)
            await client.connect()

            with pytest.raises(asyncio.TimeoutError):
                await client.request("test.subject", {"test": "data"}, timeout=1)

    @pytest.mark.asyncio
    async def test_request_when_not_connected(self, nats_config: dict[str, Any]) -> None:
        """Test request when not connected."""
        from ipc_router.domain.exceptions import ConnectionError as IPCConnectionError

        client = NATSClient(**nats_config)
        with pytest.raises(IPCConnectionError) as exc_info:
            await client.request("test.subject", {"test": "data"})
        assert "Not connected" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_is_connected(
        self, nats_config: dict[str, Any], mock_nats_connection: AsyncMock
    ) -> None:
        """Test connection status check."""
        client = NATSClient(**nats_config)
        assert not client.is_connected

        with patch("nats.connect", return_value=mock_nats_connection):
            await client.connect()
            assert client.is_connected

            # Test the property directly
            assert client.is_connected

    @pytest.mark.asyncio
    async def test_error_callback(self, nats_config: dict[str, Any]) -> None:
        """Test error callback logging."""
        client = NATSClient(**nats_config)
        error = Exception("Test error")

        # Should not raise, just log
        await client._error_callback(error)

    @pytest.mark.asyncio
    async def test_disconnected_callback(self, nats_config: dict[str, Any]) -> None:
        """Test disconnected callback logging."""
        client = NATSClient(**nats_config)

        # Should not raise, just log
        await client._disconnected_callback()

    @pytest.mark.asyncio
    async def test_reconnected_callback(self, nats_config: dict[str, Any]) -> None:
        """Test reconnected callback logging."""
        client = NATSClient(**nats_config)

        # Should not raise, just log
        await client._reconnected_callback()

    @pytest.mark.asyncio
    async def test_closed_callback(self, nats_config: dict[str, Any]) -> None:
        """Test closed callback logging."""
        client = NATSClient(**nats_config)

        # Should not raise, just log
        await client._closed_callback()
