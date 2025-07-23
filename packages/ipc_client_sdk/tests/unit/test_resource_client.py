"""Unit tests for resource management in ServiceClient."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from ipc_client_sdk.clients.service_client import (
    ResourceConflictError,
    ResourceNotFoundError,
    ServiceClient,
)
from ipc_client_sdk.models import (
    ResourceMetadata,
)


@pytest.fixture
def mock_nats_client() -> MagicMock:
    """Create a mock NATS client."""
    mock = MagicMock()
    mock.is_connected = True
    mock.connect = AsyncMock()
    mock.disconnect = AsyncMock()
    mock.request = AsyncMock()
    mock.publish = AsyncMock()
    return mock


@pytest_asyncio.fixture
async def service_client(mock_nats_client: MagicMock) -> ServiceClient:
    """Create a service client with mocked NATS."""
    with patch("ipc_client_sdk.clients.service_client.NATSClient") as mock_cls:
        mock_cls.return_value = mock_nats_client
        client = ServiceClient(nats_url="nats://test:4222")
        await client.connect()
        return client


@pytest.fixture
def sample_metadata() -> ResourceMetadata:
    """Create sample resource metadata."""
    return ResourceMetadata(
        resource_type="user_session",
        version=1,
        tags=["active", "premium"],
        attributes={"region": "us-west", "tier": "gold"},
        created_by="auth-service",
        last_modified=datetime.now(UTC),
        ttl_seconds=3600,
        priority=10,
    )


class TestResourceOperations:
    """Test resource management operations in ServiceClient."""

    @pytest.mark.asyncio
    async def test_register_resource_success(
        self,
        service_client: ServiceClient,
        mock_nats_client: MagicMock,
        sample_metadata: ResourceMetadata,
    ) -> None:
        """Test successful resource registration."""
        # Mock successful response
        mock_nats_client.request.return_value = {
            "success": True,
            "registered": ["resource-1", "resource-2"],
            "conflicts": {},
            "trace_id": "trace-123",
        }

        # Register resources
        result = await service_client.register_resource(
            service_name="test-service",
            resource_ids=["resource-1", "resource-2"],
            metadata={"resource-1": sample_metadata},
        )

        # Verify request was sent
        mock_nats_client.request.assert_called_once()
        call_args = mock_nats_client.request.call_args
        assert call_args[0][0] == "ipc.resource.register"

        request_data = call_args[0][1]
        assert request_data["service_name"] == "test-service"
        assert request_data["resource_ids"] == ["resource-1", "resource-2"]
        assert "resource-1" in request_data["metadata"]

        # Verify response
        assert result.success is True
        assert result.registered == ["resource-1", "resource-2"]
        assert result.conflicts == {}

        # Verify resources are tracked
        tracked = service_client.get_registered_resources("test-service")
        assert "resource-1" in tracked["test-service"]
        assert "resource-2" in tracked["test-service"]

    @pytest.mark.asyncio
    async def test_register_resource_with_conflicts(
        self,
        service_client: ServiceClient,
        mock_nats_client: MagicMock,
    ) -> None:
        """Test resource registration with conflicts."""
        # Mock response with conflicts
        mock_nats_client.request.return_value = {
            "success": False,
            "registered": ["resource-1"],
            "conflicts": {"resource-2": "other-instance"},
            "trace_id": "trace-123",
        }

        # Attempt registration
        with pytest.raises(ResourceConflictError) as exc_info:
            await service_client.register_resource(
                service_name="test-service",
                resource_ids=["resource-1", "resource-2"],
            )

        # Verify exception details
        error = exc_info.value
        assert "conflicts detected" in str(error)
        assert error.conflicts == {"resource-2": "other-instance"}
        assert error.registered == ["resource-1"]

        # Verify partially registered resources are tracked
        tracked = service_client.get_registered_resources("test-service")
        assert "resource-1" in tracked["test-service"]
        assert "resource-2" not in tracked["test-service"]

    @pytest.mark.asyncio
    async def test_register_resource_with_force(
        self,
        service_client: ServiceClient,
        mock_nats_client: MagicMock,
    ) -> None:
        """Test resource registration with force flag."""
        # Mock successful response
        mock_nats_client.request.return_value = {
            "success": True,
            "registered": ["resource-1", "resource-2"],
            "conflicts": {},
            "trace_id": "trace-123",
        }

        # Register with force
        result = await service_client.register_resource(
            service_name="test-service",
            resource_ids=["resource-1", "resource-2"],
            force=True,
        )

        # Verify force flag was sent
        request_data = mock_nats_client.request.call_args[0][1]
        assert request_data["force"] is True

        # Verify success
        assert result.success is True
        assert len(result.registered) == 2

    @pytest.mark.asyncio
    async def test_register_resource_validation_error(
        self,
        service_client: ServiceClient,
        mock_nats_client: MagicMock,
    ) -> None:
        """Test resource registration with validation error."""
        # Mock error response
        mock_nats_client.request.return_value = {
            "success": False,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Resource ID cannot be empty",
            },
        }

        # Attempt registration
        with pytest.raises(ValueError) as exc_info:
            await service_client.register_resource(
                service_name="test-service",
                resource_ids=[""],  # Invalid resource ID
            )

        # Check for Pydantic validation error format
        assert "validation error" in str(
            exc_info.value
        ).lower() or "Resource ID cannot be empty" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_register_resource_timeout(
        self,
        service_client: ServiceClient,
        mock_nats_client: MagicMock,
    ) -> None:
        """Test resource registration timeout."""
        # Mock timeout
        mock_nats_client.request.return_value = None

        # Attempt registration
        with pytest.raises(TimeoutError) as exc_info:
            await service_client.register_resource(
                service_name="test-service",
                resource_ids=["resource-1"],
            )

        assert "timed out" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_release_resource_success(
        self,
        service_client: ServiceClient,
        mock_nats_client: MagicMock,
    ) -> None:
        """Test successful resource release."""
        # First register resources
        service_client._registered_resources["test-service"] = {"resource-1", "resource-2"}

        # Mock successful release response
        mock_nats_client.request.return_value = {
            "success": True,
            "released": ["resource-1", "resource-2"],
            "errors": {},
            "trace_id": "trace-123",
        }

        # Release resources
        result = await service_client.release_resource(
            service_name="test-service",
            resource_ids=["resource-1", "resource-2"],
        )

        # Verify request
        mock_nats_client.request.assert_called_once()
        call_args = mock_nats_client.request.call_args
        assert call_args[0][0] == "ipc.resource.release"

        # Verify response
        assert result.success is True
        assert result.released == ["resource-1", "resource-2"]
        assert result.errors == {}

        # Verify resources are no longer tracked
        tracked = service_client.get_registered_resources("test-service")
        assert len(tracked["test-service"]) == 0

    @pytest.mark.asyncio
    async def test_release_resource_partial_success(
        self,
        service_client: ServiceClient,
        mock_nats_client: MagicMock,
    ) -> None:
        """Test resource release with partial success."""
        # First register resources
        service_client._registered_resources["test-service"] = {"resource-1", "resource-2"}

        # Mock partial success response
        mock_nats_client.request.return_value = {
            "success": False,
            "released": ["resource-1"],
            "errors": {"resource-2": "Resource not owned by instance"},
            "trace_id": "trace-123",
        }

        # Release resources
        result = await service_client.release_resource(
            service_name="test-service",
            resource_ids=["resource-1", "resource-2"],
        )

        # Verify partial success
        assert result.success is False
        assert result.released == ["resource-1"]
        assert "resource-2" in result.errors

        # Verify only released resources are removed from tracking
        tracked = service_client.get_registered_resources("test-service")
        assert "resource-1" not in tracked["test-service"]
        assert "resource-2" in tracked["test-service"]

    @pytest.mark.asyncio
    async def test_release_resource_not_connected(
        self,
        service_client: ServiceClient,
        mock_nats_client: MagicMock,
    ) -> None:
        """Test resource release when not connected."""
        # Simulate disconnected state
        mock_nats_client.is_connected = False

        # Attempt release
        with pytest.raises(RuntimeError) as exc_info:
            await service_client.release_resource(
                service_name="test-service",
                resource_ids=["resource-1"],
            )

        assert "Not connected to NATS" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_call_with_resource_id(
        self,
        service_client: ServiceClient,
        mock_nats_client: MagicMock,
    ) -> None:
        """Test service call with resource ID for routing."""
        # Mock successful response
        mock_nats_client.request.return_value = {
            "success": True,
            "result": {"data": "test-result"},
        }

        # Call with resource ID
        result = await service_client.call(
            service_name="test-service",
            method="process",
            params={"action": "update"},
            resource_id="resource-123",
        )

        # Verify request includes resource_id
        request_data = mock_nats_client.request.call_args[0][1]
        assert request_data["resource_id"] == "resource-123"
        assert request_data["service_name"] == "test-service"
        assert request_data["method"] == "process"

        # Verify result
        assert result == {"data": "test-result"}

    @pytest.mark.asyncio
    async def test_call_resource_not_found(
        self,
        service_client: ServiceClient,
        mock_nats_client: MagicMock,
    ) -> None:
        """Test service call when resource is not found."""
        # Mock resource not found error
        mock_nats_client.request.return_value = {
            "success": False,
            "error": {
                "code": 404,
                "message": "Resource 'resource-123' not found",
            },
        }

        # Attempt call with resource ID
        with pytest.raises(ResourceNotFoundError) as exc_info:
            await service_client.call(
                service_name="test-service",
                method="process",
                resource_id="resource-123",
            )

        error = exc_info.value
        assert "resource-123" in str(error)
        assert error.resource_id == "resource-123"

    @pytest.mark.asyncio
    async def test_get_registered_resources(
        self,
        service_client: ServiceClient,
    ) -> None:
        """Test getting registered resources."""
        # Set up some registered resources
        service_client._registered_resources = {
            "service-1": {"resource-1", "resource-2"},
            "service-2": {"resource-3"},
        }

        # Get all resources
        all_resources = service_client.get_registered_resources()
        assert len(all_resources) == 2
        assert "resource-1" in all_resources["service-1"]
        assert "resource-3" in all_resources["service-2"]

        # Get resources for specific service
        service1_resources = service_client.get_registered_resources("service-1")
        assert len(service1_resources) == 1
        assert "resource-1" in service1_resources["service-1"]

        # Get resources for non-existent service
        empty_resources = service_client.get_registered_resources("non-existent")
        assert len(empty_resources["non-existent"]) == 0

    @pytest.mark.asyncio
    async def test_register_resource_custom_instance_id(
        self,
        service_client: ServiceClient,
        mock_nats_client: MagicMock,
    ) -> None:
        """Test resource registration with custom instance ID."""
        # Mock successful response
        mock_nats_client.request.return_value = {
            "success": True,
            "registered": ["resource-1"],
            "conflicts": {},
            "trace_id": "trace-123",
        }

        # Register with custom instance ID
        await service_client.register_resource(
            service_name="test-service",
            resource_ids=["resource-1"],
            instance_id="custom-instance-123",
        )

        # Verify custom instance ID was used
        request_data = mock_nats_client.request.call_args[0][1]
        assert request_data["instance_id"] == "custom-instance-123"
