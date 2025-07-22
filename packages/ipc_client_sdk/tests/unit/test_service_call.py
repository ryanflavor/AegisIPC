"""Unit tests for ServiceClient call functionality."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from ipc_client_sdk.clients.service_client import ServiceClient


@pytest.mark.asyncio
class TestServiceClientCall:
    """Test cases for ServiceClient.call method."""

    async def test_call_not_connected(self) -> None:
        """Test calling when not connected raises error."""
        client = ServiceClient()

        with pytest.raises(RuntimeError, match="Not connected to NATS"):
            await client.call("test-service", "test_method")

    async def test_call_successful(self) -> None:
        """Test successful service call."""
        client = ServiceClient()

        # Mock the NATS client
        mock_nats = MagicMock()
        mock_nats.is_connected = True
        mock_nats.request = AsyncMock(
            return_value={
                "success": True,
                "result": {"data": "test_result"},
                "instance_id": "inst-1",
                "trace_id": "trace-123",
            }
        )

        client._nats_client = mock_nats

        # Make call
        result = await client.call(
            "test-service",
            "test_method",
            params={"param1": "value1"},
        )

        assert result == {"data": "test_result"}

        # Verify request was made correctly
        mock_nats.request.assert_called_once()
        call_args = mock_nats.request.call_args
        assert call_args[0][0] == "ipc.route.request"

        request_data = call_args[0][1]
        assert request_data["service_name"] == "test-service"
        assert request_data["method"] == "test_method"
        assert request_data["params"] == {"param1": "value1"}
        assert "trace_id" in request_data

    async def test_call_with_custom_trace_id(self) -> None:
        """Test service call with custom trace ID."""
        client = ServiceClient()

        mock_nats = MagicMock()
        mock_nats.is_connected = True
        mock_nats.request = AsyncMock(
            return_value={
                "success": True,
                "result": "ok",
            }
        )

        client._nats_client = mock_nats

        # Make call with custom trace ID
        await client.call(
            "test-service",
            "test_method",
            trace_id="custom-trace-123",
        )

        # Verify trace ID was used
        request_data = mock_nats.request.call_args[0][1]
        assert request_data["trace_id"] == "custom-trace-123"

    async def test_call_timeout(self) -> None:
        """Test service call timeout."""
        client = ServiceClient(timeout=2.0)

        mock_nats = MagicMock()
        mock_nats.is_connected = True
        mock_nats.request = AsyncMock(return_value=None)

        client._nats_client = mock_nats

        with pytest.raises(TimeoutError, match="timed out"):
            await client.call("test-service", "test_method")

    async def test_call_service_not_found(self) -> None:
        """Test call to non-existent service."""
        client = ServiceClient()

        mock_nats = MagicMock()
        mock_nats.is_connected = True
        mock_nats.request = AsyncMock(
            return_value={
                "success": False,
                "error": {
                    "type": "NotFoundError",
                    "message": "Service 'test-service' not found",
                    "code": 404,
                },
            }
        )

        client._nats_client = mock_nats

        with pytest.raises(ValueError, match="Service 'test-service' not found"):
            await client.call("test-service", "test_method")

    async def test_call_service_unavailable(self) -> None:
        """Test call when service is unavailable."""
        client = ServiceClient()

        mock_nats = MagicMock()
        mock_nats.is_connected = True
        mock_nats.request = AsyncMock(
            return_value={
                "success": False,
                "error": {
                    "type": "ServiceUnavailableError",
                    "message": "No healthy instances",
                    "code": 503,
                },
            }
        )

        client._nats_client = mock_nats

        with pytest.raises(RuntimeError, match="Service 'test-service' unavailable"):
            await client.call("test-service", "test_method")

    async def test_call_instance_timeout(self) -> None:
        """Test call when instance times out."""
        client = ServiceClient()

        mock_nats = MagicMock()
        mock_nats.is_connected = True
        mock_nats.request = AsyncMock(
            return_value={
                "success": False,
                "error": {
                    "type": "InstanceTimeoutError",
                    "message": "Instance timeout",
                    "code": 504,
                },
            }
        )

        client._nats_client = mock_nats

        with pytest.raises(TimeoutError, match="Service 'test-service' timeout"):
            await client.call("test-service", "test_method")

    async def test_call_generic_error(self) -> None:
        """Test call with generic error."""
        client = ServiceClient()

        mock_nats = MagicMock()
        mock_nats.is_connected = True
        mock_nats.request = AsyncMock(
            return_value={
                "success": False,
                "error": {
                    "type": "InternalError",
                    "message": "Something went wrong",
                    "code": 500,
                },
            }
        )

        client._nats_client = mock_nats

        with pytest.raises(Exception, match="InternalError: Something went wrong"):
            await client.call("test-service", "test_method")

    async def test_call_with_custom_timeout(self) -> None:
        """Test call with custom timeout."""
        client = ServiceClient(timeout=5.0)

        mock_nats = MagicMock()
        mock_nats.is_connected = True
        mock_nats.request = AsyncMock(
            return_value={
                "success": True,
                "result": "ok",
            }
        )

        client._nats_client = mock_nats

        # Call with custom timeout
        await client.call(
            "test-service",
            "test_method",
            timeout=10.0,
        )

        # Verify custom timeout was used
        request_data = mock_nats.request.call_args[0][1]
        assert request_data["timeout"] == 10.0

        # Also verify in request call
        assert mock_nats.request.call_args[1]["timeout"] == 10.0
