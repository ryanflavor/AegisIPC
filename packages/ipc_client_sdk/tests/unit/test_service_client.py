"""Unit tests for ServiceClient."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from ipc_client_sdk.clients import ServiceClient
from ipc_client_sdk.models import ServiceRegistrationResponse


@pytest.fixture
def mock_nats_client() -> AsyncMock:
    """Create a mock NATS client."""
    mock = AsyncMock()
    mock.is_connected = True
    return mock


@pytest.fixture
def service_client(mock_nats_client: AsyncMock) -> ServiceClient:
    """Create a ServiceClient with mocked NATS."""
    with patch("ipc_client_sdk.clients.service_client.NATSClient") as mock_class:
        mock_class.return_value = mock_nats_client
        client = ServiceClient(nats_url="nats://localhost:4222")
        return client


class TestServiceClient:
    """Tests for ServiceClient."""

    def test_initialization(self) -> None:
        """Test ServiceClient initialization."""
        client = ServiceClient(
            nats_url="nats://test:4222",
            instance_id="test_instance",
            timeout=10.0,
        )

        assert client._nats_url == "nats://test:4222"
        assert client._instance_id == "test_instance"
        assert client._timeout == 10.0
        assert client._nats_client is not None

    def test_initialization_defaults(self) -> None:
        """Test ServiceClient with default values."""
        client = ServiceClient()

        assert client._nats_url == "nats://localhost:4222"
        assert client._instance_id.startswith("instance_")
        assert client._timeout == 5.0

    @pytest.mark.asyncio
    async def test_connect(
        self,
        service_client: ServiceClient,
        mock_nats_client: AsyncMock,
    ) -> None:
        """Test connecting to NATS."""
        await service_client.connect()

        mock_nats_client.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect(
        self,
        service_client: ServiceClient,
        mock_nats_client: AsyncMock,
    ) -> None:
        """Test disconnecting from NATS."""
        await service_client.disconnect()

        mock_nats_client.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_manager(
        self,
        mock_nats_client: AsyncMock,
    ) -> None:
        """Test using ServiceClient as context manager."""
        with patch("ipc_client_sdk.clients.service_client.NATSClient") as mock_class:
            mock_class.return_value = mock_nats_client

            async with ServiceClient() as client:
                assert client._nats_client is mock_nats_client
                mock_nats_client.connect.assert_called_once()

            mock_nats_client.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_register_success(
        self,
        service_client: ServiceClient,
        mock_nats_client: AsyncMock,
    ) -> None:
        """Test successful service registration."""
        # Mock response
        now = datetime.now(UTC)
        mock_response = {
            "envelope": {
                "success": True,
                "request_id": "req_123",
                "timestamp": now.isoformat(),
            },
            "data": {
                "success": True,
                "service_name": "test-service",
                "instance_id": service_client._instance_id,
                "registered_at": now.isoformat(),
                "message": "Service instance registered successfully",
            },
        }
        mock_nats_client.request.return_value = mock_response

        # Call register
        response = await service_client.register(
            service_name="test-service",
            metadata={"version": "1.0.0"},
        )

        # Verify
        assert isinstance(response, ServiceRegistrationResponse)
        assert response.success is True
        assert response.service_name == "test-service"
        assert response.instance_id == service_client._instance_id
        assert response.message == "Service instance registered successfully"

        # Check request was made correctly
        mock_nats_client.request.assert_called_once()
        call_args = mock_nats_client.request.call_args
        assert call_args[0][0] == "ipc.service.register"
        assert call_args[0][1]["service_name"] == "test-service"
        assert call_args[0][1]["instance_id"] == service_client._instance_id
        assert call_args[0][1]["metadata"] == {"version": "1.0.0"}

    @pytest.mark.asyncio
    async def test_register_custom_instance_id(
        self,
        service_client: ServiceClient,
        mock_nats_client: AsyncMock,
    ) -> None:
        """Test registration with custom instance ID."""
        # Mock response
        now = datetime.now(UTC)
        mock_response = {
            "envelope": {
                "success": True,
                "request_id": "req_123",
                "timestamp": now.isoformat(),
            },
            "data": {
                "success": True,
                "service_name": "test-service",
                "instance_id": "custom_instance",
                "registered_at": now.isoformat(),
                "message": "Success",
            },
        }
        mock_nats_client.request.return_value = mock_response

        # Call register with custom instance ID
        response = await service_client.register(
            service_name="test-service",
            instance_id="custom_instance",
        )

        # Verify custom instance ID was used
        assert response.instance_id == "custom_instance"
        call_args = mock_nats_client.request.call_args
        assert call_args[0][1]["instance_id"] == "custom_instance"

    @pytest.mark.asyncio
    async def test_register_error_response(
        self,
        service_client: ServiceClient,
        mock_nats_client: AsyncMock,
    ) -> None:
        """Test handling error response from server."""
        # Mock error response
        mock_response = {
            "envelope": {
                "success": False,
                "error_code": "CONFLICT",
                "message": "Service instance already registered",
                "request_id": "req_123",
                "timestamp": datetime.now(UTC).isoformat(),
            },
        }
        mock_nats_client.request.return_value = mock_response

        # Call register and expect exception
        with pytest.raises(Exception) as exc_info:
            await service_client.register(service_name="test-service")

        assert "Service instance already registered" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_register_timeout(
        self,
        service_client: ServiceClient,
        mock_nats_client: AsyncMock,
    ) -> None:
        """Test registration timeout."""
        # Mock timeout
        mock_nats_client.request.return_value = None

        # Call register and expect exception
        with pytest.raises(TimeoutError):
            await service_client.register(service_name="test-service")

    @pytest.mark.asyncio
    async def test_register_not_connected(
        self,
        service_client: ServiceClient,
        mock_nats_client: AsyncMock,
    ) -> None:
        """Test registration when not connected."""
        mock_nats_client.is_connected = False

        with pytest.raises(RuntimeError) as exc_info:
            await service_client.register(service_name="test-service")

        assert "Not connected to NATS" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_heartbeat_success(
        self,
        service_client: ServiceClient,
        mock_nats_client: AsyncMock,
    ) -> None:
        """Test sending heartbeat."""
        # First register the service
        service_client._registered_services.add("test-service")

        # Mock heartbeat response
        mock_nats_client.publish = AsyncMock()

        # Send heartbeat
        await service_client.heartbeat(service_name="test-service")

        # Verify
        mock_nats_client.publish.assert_called_once()
        call_args = mock_nats_client.publish.call_args
        assert call_args[0][0] == "ipc.service.heartbeat"
        assert call_args[0][1]["service_name"] == "test-service"
        assert call_args[0][1]["instance_id"] == service_client._instance_id

    @pytest.mark.asyncio
    async def test_heartbeat_not_registered(
        self,
        service_client: ServiceClient,
        mock_nats_client: AsyncMock,
    ) -> None:
        """Test heartbeat for unregistered service."""
        with pytest.raises(ValueError) as exc_info:
            await service_client.heartbeat(service_name="unknown-service")

        assert "Service 'unknown-service' is not registered" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_start_heartbeat_task(
        self,
        service_client: ServiceClient,
        mock_nats_client: AsyncMock,
    ) -> None:
        """Test starting heartbeat background task."""
        # Register service first
        service_client._registered_services.add("test-service")

        # Mock heartbeat
        heartbeat_called = False

        async def mock_heartbeat(service_name: str) -> None:
            nonlocal heartbeat_called
            heartbeat_called = True

        with patch.object(service_client, "heartbeat", mock_heartbeat):
            # Start heartbeat with very short interval
            task = await service_client.start_heartbeat(
                service_name="test-service",
                interval=0.1,
            )

            # Wait a bit for heartbeat to be called
            await asyncio.sleep(0.2)

            # Cancel task
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

            assert heartbeat_called

    @pytest.mark.asyncio
    async def test_unregister_success(
        self,
        service_client: ServiceClient,
        mock_nats_client: AsyncMock,
    ) -> None:
        """Test unregistering a service."""
        # Register service first
        service_client._registered_services.add("test-service")

        # Mock response
        mock_response = {
            "envelope": {
                "success": True,
                "request_id": "req_123",
                "timestamp": datetime.now(UTC).isoformat(),
            },
        }
        mock_nats_client.request.return_value = mock_response

        # Unregister
        await service_client.unregister(service_name="test-service")

        # Verify
        assert "test-service" not in service_client._registered_services
        mock_nats_client.request.assert_called_once()
        call_args = mock_nats_client.request.call_args
        assert call_args[0][0] == "ipc.service.unregister"
        assert call_args[0][1]["service_name"] == "test-service"
        assert call_args[0][1]["instance_id"] == service_client._instance_id

    @pytest.mark.asyncio
    async def test_unregister_not_registered(
        self,
        service_client: ServiceClient,
        mock_nats_client: AsyncMock,
    ) -> None:
        """Test unregistering unknown service."""
        with pytest.raises(ValueError) as exc_info:
            await service_client.unregister(service_name="unknown-service")

        assert "Service 'unknown-service' is not registered" in str(exc_info.value)

    def test_is_connected_property(
        self,
        service_client: ServiceClient,
        mock_nats_client: AsyncMock,
    ) -> None:
        """Test is_connected property."""
        mock_nats_client.is_connected = True
        assert service_client.is_connected is True

        mock_nats_client.is_connected = False
        assert service_client.is_connected is False


class TestServiceClientConfig:
    """Tests for ServiceClientConfig dataclass."""

    def test_default_config(self) -> None:
        """Test default configuration values."""
        from ipc_client_sdk.clients.service_client import ServiceClientConfig

        config = ServiceClientConfig()

        assert config.nats_servers == "nats://localhost:4222"
        assert config.timeout == 5.0
        assert config.max_reconnect_attempts == 10
        assert config.reconnect_time_wait == 2
        assert config.retry_attempts == 3
        assert config.retry_delay == 0.5

    def test_custom_config(self) -> None:
        """Test custom configuration values."""
        from ipc_client_sdk.clients.service_client import ServiceClientConfig

        config = ServiceClientConfig(
            nats_servers=["nats://server1:4222", "nats://server2:4222"],
            timeout=10.0,
            max_reconnect_attempts=5,
            reconnect_time_wait=1,
            retry_attempts=2,
            retry_delay=1.0,
        )

        assert config.nats_servers == ["nats://server1:4222", "nats://server2:4222"]
        assert config.timeout == 10.0
        assert config.max_reconnect_attempts == 5
        assert config.reconnect_time_wait == 1
        assert config.retry_attempts == 2
        assert config.retry_delay == 1.0


class TestServiceRegistrationError:
    """Tests for ServiceRegistrationError exception."""

    def test_basic_error(self) -> None:
        """Test basic error creation."""
        from ipc_client_sdk.clients.service_client import ServiceRegistrationError

        error = ServiceRegistrationError("Test error")

        assert str(error) == "Test error"
        assert error.error_code is None
        assert error.details == {}

    def test_error_with_code_and_details(self) -> None:
        """Test error with code and details."""
        from ipc_client_sdk.clients.service_client import ServiceRegistrationError

        details = {"service_name": "test", "instance_id": "123"}
        error = ServiceRegistrationError(
            "Registration failed",
            error_code="CONFLICT",
            details=details,
        )

        assert str(error) == "Registration failed"
        assert error.error_code == "CONFLICT"
        assert error.details == details

    def test_error_inheritance(self) -> None:
        """Test that error inherits from Exception."""
        from ipc_client_sdk.clients.service_client import ServiceRegistrationError

        error = ServiceRegistrationError("Test")
        assert isinstance(error, Exception)


class TestNATSClient:
    """Tests for NATSClient wrapper."""

    def test_initialization(self) -> None:
        """Test NATSClient initialization."""
        from ipc_client_sdk.clients.service_client import NATSClient

        client = NATSClient("nats://test:4222")

        assert client.nats_url == "nats://test:4222"
        assert client._nc is None
        assert client._connected is False
        assert not client.is_connected

    @pytest.mark.asyncio
    async def test_connect_success(self) -> None:
        """Test successful connection to NATS."""
        from ipc_client_sdk.clients.service_client import NATSClient

        client = NATSClient("nats://test:4222")

        with patch("ipc_client_sdk.clients.service_client.nats.connect") as mock_connect:
            mock_nc = AsyncMock()
            mock_connect.return_value = mock_nc

            await client.connect()

            assert client._nc is mock_nc
            assert client._connected is True
            assert client.is_connected is True
            mock_connect.assert_called_once_with(servers=["nats://test:4222"])

    @pytest.mark.asyncio
    async def test_connect_already_connected(self) -> None:
        """Test connecting when already connected."""
        from ipc_client_sdk.clients.service_client import NATSClient

        client = NATSClient("nats://test:4222")
        client._connected = True

        with patch("ipc_client_sdk.clients.service_client.nats.connect") as mock_connect:
            await client.connect()
            mock_connect.assert_not_called()

    @pytest.mark.asyncio
    async def test_connect_failure(self) -> None:
        """Test connection failure."""
        from ipc_client_sdk.clients.service_client import NATSClient, ServiceRegistrationError

        client = NATSClient("nats://test:4222")

        with patch("ipc_client_sdk.clients.service_client.nats.connect") as mock_connect:
            mock_connect.side_effect = Exception("Connection failed")

            with pytest.raises(ServiceRegistrationError) as exc_info:
                await client.connect()

            assert "Failed to connect to NATS: Connection failed" in str(exc_info.value)
            assert not client.is_connected

    @pytest.mark.asyncio
    async def test_disconnect_success(self) -> None:
        """Test successful disconnection."""
        from ipc_client_sdk.clients.service_client import NATSClient

        client = NATSClient("nats://test:4222")
        mock_nc = AsyncMock()
        client._nc = mock_nc
        client._connected = True

        await client.disconnect()

        mock_nc.close.assert_called_once()
        assert not client._connected

    @pytest.mark.asyncio
    async def test_disconnect_not_connected(self) -> None:
        """Test disconnect when not connected."""
        from ipc_client_sdk.clients.service_client import NATSClient

        client = NATSClient("nats://test:4222")

        await client.disconnect()  # Should not raise

        assert not client._connected

    @pytest.mark.asyncio
    async def test_request_success(self) -> None:
        """Test successful NATS request."""
        from ipc_client_sdk.clients.service_client import NATSClient

        client = NATSClient("nats://test:4222")
        mock_nc = AsyncMock()
        client._nc = mock_nc
        client._connected = True

        # Mock response
        from unittest.mock import MagicMock

        mock_response = MagicMock()
        mock_response.data = b"test_response_data"
        mock_nc.request.return_value = mock_response

        with (
            patch("ipc_client_sdk.clients.service_client.msgpack.packb") as mock_packb,
            patch("ipc_client_sdk.clients.service_client.msgpack.unpackb") as mock_unpackb,
        ):
            mock_packb.return_value = b"packed_data"
            mock_unpackb.return_value = {"success": True}

            payload = {"test": "data"}
            result = await client.request("test.subject", payload, timeout=10.0)

            assert result == {"success": True}
            mock_packb.assert_called_once_with(payload, use_bin_type=True)
            mock_nc.request.assert_called_once_with("test.subject", b"packed_data", timeout=10.0)
            mock_unpackb.assert_called_once_with(mock_response.data, raw=False)

    @pytest.mark.asyncio
    async def test_request_not_connected(self) -> None:
        """Test request when not connected."""
        from ipc_client_sdk.clients.service_client import NATSClient, ServiceRegistrationError

        client = NATSClient("nats://test:4222")

        with pytest.raises(ServiceRegistrationError) as exc_info:
            await client.request("test.subject", {"data": "test"})

        assert "Not connected to NATS" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_request_timeout(self) -> None:
        """Test request timeout."""
        from ipc_client_sdk.clients.service_client import NATSClient

        client = NATSClient("nats://test:4222")
        mock_nc = AsyncMock()
        client._nc = mock_nc
        client._connected = True

        mock_nc.request.side_effect = TimeoutError("Timeout")

        with patch("ipc_client_sdk.clients.service_client.msgpack.packb") as mock_packb:
            mock_packb.return_value = b"packed_data"

            result = await client.request("test.subject", {"data": "test"})
            assert result is None

    @pytest.mark.asyncio
    async def test_publish_success(self) -> None:
        """Test successful publish."""
        from ipc_client_sdk.clients.service_client import NATSClient

        client = NATSClient("nats://test:4222")
        mock_nc = AsyncMock()
        client._nc = mock_nc
        client._connected = True

        with patch("ipc_client_sdk.clients.service_client.msgpack.packb") as mock_packb:
            mock_packb.return_value = b"packed_data"

            payload = {"event": "heartbeat"}
            await client.publish("test.subject", payload)

            mock_packb.assert_called_once_with(payload, use_bin_type=True)
            mock_nc.publish.assert_called_once_with("test.subject", b"packed_data")

    @pytest.mark.asyncio
    async def test_publish_not_connected(self) -> None:
        """Test publish when not connected."""
        from ipc_client_sdk.clients.service_client import NATSClient, ServiceRegistrationError

        client = NATSClient("nats://test:4222")

        with pytest.raises(ServiceRegistrationError) as exc_info:
            await client.publish("test.subject", {"data": "test"})

        assert "Not connected to NATS" in str(exc_info.value)


class TestServiceClientAdvanced:
    """Advanced tests for ServiceClient edge cases."""

    @pytest.mark.asyncio
    async def test_disconnect_with_heartbeat_tasks(self) -> None:
        """Test disconnect cancels heartbeat tasks."""
        client = ServiceClient()
        mock_nats_client = AsyncMock()
        client._nats_client = mock_nats_client

        # Add a mock heartbeat task
        from unittest.mock import MagicMock

        mock_task = AsyncMock()
        mock_task.cancel = MagicMock()
        client._heartbeat_tasks["test-service"] = mock_task

        # Mock asyncio.gather to simulate task completion
        async def mock_gather(*args: Any, **kwargs: Any) -> list[Any]:
            return [None]

        with patch("asyncio.gather", side_effect=mock_gather) as mock_gather_patch:
            await client.disconnect()

            mock_task.cancel.assert_called_once()
            mock_gather_patch.assert_called_once_with(mock_task, return_exceptions=True)
            assert len(client._heartbeat_tasks) == 0

    @pytest.mark.asyncio
    async def test_unregister_with_heartbeat_task(self) -> None:
        """Test unregister cancels associated heartbeat task."""
        client = ServiceClient()
        mock_nats_client = AsyncMock()
        client._nats_client = mock_nats_client
        mock_nats_client.is_connected = True

        # Register service and add heartbeat task
        client._registered_services.add("test-service")
        from unittest.mock import MagicMock

        mock_task = AsyncMock()
        mock_task.cancel = MagicMock()
        client._heartbeat_tasks["test-service"] = mock_task

        # Mock response
        mock_response = {
            "envelope": {"success": True},
        }
        mock_nats_client.request.return_value = mock_response

        await client.unregister("test-service")

        # Verify task was cancelled and removed
        mock_task.cancel.assert_called_once()
        assert "test-service" not in client._heartbeat_tasks
        assert "test-service" not in client._registered_services

    @pytest.mark.asyncio
    async def test_start_heartbeat_not_registered(self) -> None:
        """Test start heartbeat for unregistered service."""
        client = ServiceClient()

        with pytest.raises(ValueError) as exc_info:
            await client.start_heartbeat("unknown-service")

        assert "Service 'unknown-service' is not registered" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_register_with_none_metadata(self) -> None:
        """Test registration with None metadata is converted to empty dict."""
        client = ServiceClient()
        mock_nats_client = AsyncMock()
        client._nats_client = mock_nats_client
        mock_nats_client.is_connected = True

        # Mock response
        mock_response = {
            "envelope": {"success": True},
            "data": {
                "success": True,
                "service_name": "test-service",
                "instance_id": client._instance_id,
                "registered_at": datetime.now(UTC).isoformat(),
                "message": "Success",
            },
        }
        mock_nats_client.request.return_value = mock_response

        await client.register("test-service", metadata=None)

        # Verify empty dict was used for metadata
        call_args = mock_nats_client.request.call_args
        assert call_args[0][1]["metadata"] == {}

    @pytest.mark.asyncio
    async def test_heartbeat_task_cancellation_handling(self) -> None:
        """Test heartbeat task handles cancellation gracefully."""
        client = ServiceClient()
        mock_nats_client = AsyncMock()
        client._nats_client = mock_nats_client

        # Register service
        client._registered_services.add("test-service")

        # Mock heartbeat to track calls and then cancel
        heartbeat_calls = 0

        async def mock_heartbeat(service_name: str) -> None:
            nonlocal heartbeat_calls
            heartbeat_calls += 1
            if heartbeat_calls >= 2:
                raise asyncio.CancelledError()

        with patch.object(client, "heartbeat", mock_heartbeat):
            task = await client.start_heartbeat("test-service", interval=0.01)

            # Wait for task to be cancelled
            with contextlib.suppress(asyncio.CancelledError):
                await task

            assert heartbeat_calls >= 2
            assert task.cancelled() or task.done()
