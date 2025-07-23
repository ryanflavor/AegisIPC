"""Unit tests for bulk resource operations in ServiceClient."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from ipc_client_sdk.clients.service_client import ServiceClient
from ipc_client_sdk.models import (
    BulkResourceRegistrationResponse,
    BulkResourceReleaseResponse,
    ResourceMetadata,
    ResourceTransferResponse,
)


@pytest.fixture
def resource_metadata() -> ResourceMetadata:
    """Sample resource metadata."""
    return ResourceMetadata(
        resource_type="user_session",
        version=1,
        tags=["active"],
        attributes={"region": "us-west"},
        created_by="test-service",
        last_modified=datetime.now(UTC),
        ttl_seconds=3600,
        priority=5,
    )


@pytest_asyncio.fixture
async def service_client() -> ServiceClient:
    """Create ServiceClient instance with mocked NATS."""
    client = ServiceClient(
        nats_url="nats://localhost:4222",
        instance_id="test-instance",
        timeout=5.0,
    )
    # Mock the NATS client
    client._nats_client = AsyncMock()
    client._nats_client.is_connected = True
    yield client


class TestBulkResourceOperations:
    """Test bulk resource operations in ServiceClient."""

    @pytest.mark.asyncio
    async def test_bulk_register_resource_success(
        self, service_client: ServiceClient, resource_metadata: ResourceMetadata
    ) -> None:
        """Test successful bulk resource registration."""
        # Prepare test data
        resources = [(f"resource-{i}", resource_metadata) for i in range(25)]

        # Mock NATS response
        mock_response = {
            "success": True,
            "total_requested": 25,
            "total_registered": 25,
            "registered": [f"resource-{i}" for i in range(25)],
            "failed": [],
            "batch_results": [
                {
                    "batch_number": 1,
                    "success_count": 25,
                    "failure_count": 0,
                    "duration_ms": 50.5,
                }
            ],
            "trace_id": "trace-123",
        }
        service_client._nats_client.request.return_value = mock_response

        # Execute bulk registration
        response = await service_client.bulk_register_resource(
            service_name="test-service",
            resources=resources,
            batch_size=50,
            continue_on_error=False,
            force=False,
        )

        # Verify response
        assert isinstance(response, BulkResourceRegistrationResponse)
        assert response.total_requested == 25
        assert response.total_registered == 25
        assert len(response.registered) == 25
        assert len(response.failed) == 0

        # Verify resources were tracked
        tracked = service_client.get_registered_resources("test-service")
        assert len(tracked["test-service"]) == 25

        # Verify NATS call
        service_client._nats_client.request.assert_called_once()
        call_args = service_client._nats_client.request.call_args
        assert call_args[0][0] == "ipc.resource.bulk_register"
        assert call_args[1]["timeout"] >= 30.0  # Extended timeout for bulk

    @pytest.mark.asyncio
    async def test_bulk_register_with_progress_callback(
        self, service_client: ServiceClient, resource_metadata: ResourceMetadata
    ) -> None:
        """Test bulk registration with progress callback."""
        # Prepare test data
        resources = [(f"resource-{i}", resource_metadata) for i in range(10)]
        callback_called = False
        callback_result = None

        async def progress_callback(result: BulkResourceRegistrationResponse) -> None:
            nonlocal callback_called, callback_result
            callback_called = True
            callback_result = result

        # Mock NATS response
        mock_response = {
            "success": True,
            "total_requested": 10,
            "total_registered": 10,
            "registered": [f"resource-{i}" for i in range(10)],
            "failed": [],
            "batch_results": [],
            "trace_id": "trace-123",
        }
        service_client._nats_client.request.return_value = mock_response

        # Execute with callback
        response = await service_client.bulk_register_resource(
            service_name="test-service",
            resources=resources,
            progress_callback=progress_callback,
        )

        # Verify callback was called
        assert callback_called
        assert callback_result == response

    @pytest.mark.asyncio
    async def test_bulk_release_resource_success(self, service_client: ServiceClient) -> None:
        """Test successful bulk resource release."""
        # Prepare test data
        resource_ids = [f"resource-{i}" for i in range(20)]

        # Add resources to tracking
        service_client._registered_resources["test-service"] = set(resource_ids)

        # Mock NATS response
        mock_response = {
            "success": True,
            "total_requested": 20,
            "total_released": 20,
            "released": resource_ids,
            "failed": [],
            "batch_results": [
                {
                    "batch_number": 1,
                    "success_count": 20,
                    "failure_count": 0,
                    "duration_ms": 30.0,
                }
            ],
            "rollback_performed": False,
            "trace_id": "trace-123",
        }
        service_client._nats_client.request.return_value = mock_response

        # Execute bulk release
        response = await service_client.bulk_release_resource(
            service_name="test-service",
            resource_ids=resource_ids,
            batch_size=50,
            transactional=True,
        )

        # Verify response
        assert isinstance(response, BulkResourceReleaseResponse)
        assert response.total_requested == 20
        assert response.total_released == 20
        assert not response.rollback_performed

        # Verify resources were untracked
        tracked = service_client.get_registered_resources("test-service")
        assert len(tracked["test-service"]) == 0

        # Verify NATS call
        service_client._nats_client.request.assert_called_once()
        call_args = service_client._nats_client.request.call_args
        assert call_args[0][0] == "ipc.resource.bulk_release"

    @pytest.mark.asyncio
    async def test_bulk_release_with_rollback(self, service_client: ServiceClient) -> None:
        """Test bulk release with rollback."""
        # Prepare test data
        resource_ids = [f"resource-{i}" for i in range(10)]

        # Mock NATS response with rollback
        mock_response = {
            "success": True,
            "total_requested": 10,
            "total_released": 0,  # None released due to rollback
            "released": [],
            "failed": [
                {
                    "resource_id": "resource-5",
                    "reason": "Not owner",
                    "error_code": "NOT_OWNER",
                }
            ],
            "batch_results": [],
            "rollback_performed": True,
            "trace_id": "trace-123",
        }
        service_client._nats_client.request.return_value = mock_response

        # Execute bulk release
        response = await service_client.bulk_release_resource(
            service_name="test-service",
            resource_ids=resource_ids,
            transactional=True,
        )

        # Verify rollback occurred
        assert response.rollback_performed
        assert response.total_released == 0
        assert len(response.failed) == 1

    @pytest.mark.asyncio
    async def test_transfer_resource_success(self, service_client: ServiceClient) -> None:
        """Test successful resource transfer."""
        # Prepare test data
        resource_ids = ["resource-1", "resource-2", "resource-3"]

        # Add resources to tracking (as current owner)
        service_client._registered_resources["test-service"] = set(resource_ids)

        # Mock NATS response
        mock_response = {
            "success": True,
            "transferred": resource_ids,
            "failed": {},
            "transfer_id": "transfer-xyz-789",
            "trace_id": "trace-123",
        }
        service_client._nats_client.request.return_value = mock_response

        # Execute transfer
        response = await service_client.transfer_resource(
            service_name="test-service",
            resource_ids=resource_ids,
            to_instance_id="other-instance",
            verify_ownership=True,
            reason="Load balancing",
        )

        # Verify response
        assert isinstance(response, ResourceTransferResponse)
        assert response.transferred == resource_ids
        assert response.transfer_id == "transfer-xyz-789"

        # Verify resources were untracked (transferred away)
        tracked = service_client.get_registered_resources("test-service")
        assert len(tracked["test-service"]) == 0

        # Verify NATS call
        service_client._nats_client.request.assert_called_once()
        call_args = service_client._nats_client.request.call_args
        assert call_args[0][0] == "ipc.resource.transfer"
        request_data = call_args[0][1]
        assert request_data["to_instance_id"] == "other-instance"
        assert request_data["reason"] == "Load balancing"

    @pytest.mark.asyncio
    async def test_transfer_resource_permission_denied(self, service_client: ServiceClient) -> None:
        """Test resource transfer with permission denied error."""
        # Mock NATS error response
        mock_response = {
            "success": False,
            "error": {
                "code": "FORBIDDEN",
                "message": "Not authorized to transfer resources",
            },
        }
        service_client._nats_client.request.return_value = mock_response

        # Execute transfer and expect permission error
        with pytest.raises(PermissionError) as exc_info:
            await service_client.transfer_resource(
                service_name="test-service",
                resource_ids=["resource-1"],
                to_instance_id="other-instance",
            )

        assert "Permission denied" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_bulk_register_with_retry_success(
        self, service_client: ServiceClient, resource_metadata: ResourceMetadata
    ) -> None:
        """Test bulk registration with retry mechanism."""
        # Prepare test data
        resources = [(f"resource-{i}", resource_metadata) for i in range(5)]

        # Mock first two calls to fail, third to succeed
        mock_responses = [
            None,  # Timeout
            None,  # Timeout
            {
                "success": True,
                "total_requested": 5,
                "total_registered": 5,
                "registered": [f"resource-{i}" for i in range(5)],
                "failed": [],
                "batch_results": [],
                "trace_id": "trace-123",
            },
        ]
        service_client._nats_client.request.side_effect = mock_responses

        # Execute with retry
        with patch("asyncio.sleep"):  # Skip actual sleep in tests
            response = await service_client.bulk_register_with_retry(
                service_name="test-service",
                resources=resources,
                max_retries=2,
                retry_delay=0.1,
                retry_multiplier=2.0,
            )

        # Verify success after retries
        assert response.total_registered == 5
        assert service_client._nats_client.request.call_count == 3

    @pytest.mark.asyncio
    async def test_bulk_register_with_retry_all_fail(
        self, service_client: ServiceClient, resource_metadata: ResourceMetadata
    ) -> None:
        """Test bulk registration retry with all attempts failing."""
        # Prepare test data
        resources = [(f"resource-{i}", resource_metadata) for i in range(5)]

        # Mock all calls to fail
        service_client._nats_client.request.return_value = None

        # Execute with retry and expect timeout
        with patch("asyncio.sleep"), pytest.raises(TimeoutError):  # Skip actual sleep in tests
            await service_client.bulk_register_with_retry(
                service_name="test-service",
                resources=resources,
                max_retries=2,
                retry_delay=0.1,
            )

        # Verify all attempts were made
        assert service_client._nats_client.request.call_count == 3

    @pytest.mark.asyncio
    async def test_bulk_operations_validation_error(self, service_client: ServiceClient) -> None:
        """Test bulk operations with validation errors."""
        # Mock NATS validation error response
        mock_response = {
            "success": False,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Invalid batch size",
            },
        }
        service_client._nats_client.request.return_value = mock_response

        # Test bulk register validation error
        with pytest.raises(ValueError) as exc_info:
            await service_client.bulk_register_resource(
                service_name="test-service",
                resources=[],
                batch_size=10000,  # Invalid
            )
        # Check for Pydantic validation error format
        assert "validation error" in str(exc_info.value).lower() or "cannot be empty" in str(
            exc_info.value
        )

        # Test bulk release validation error
        with pytest.raises(ValueError) as exc_info:
            await service_client.bulk_release_resource(
                service_name="test-service",
                resource_ids=[],  # Empty list
            )
        # Check for Pydantic validation error format
        assert "validation error" in str(exc_info.value).lower() or "cannot be empty" in str(
            exc_info.value
        )

    @pytest.mark.asyncio
    async def test_not_connected_errors(self, service_client: ServiceClient) -> None:
        """Test operations fail when not connected."""
        # Mock disconnected state
        service_client._nats_client.is_connected = False

        # Test bulk register
        with pytest.raises(RuntimeError) as exc_info:
            await service_client.bulk_register_resource(
                service_name="test-service",
                resources=[],
            )
        assert "Not connected to NATS" in str(exc_info.value)

        # Test bulk release
        with pytest.raises(RuntimeError) as exc_info:
            await service_client.bulk_release_resource(
                service_name="test-service",
                resource_ids=["resource-1"],
            )
        assert "Not connected to NATS" in str(exc_info.value)

        # Test transfer
        with pytest.raises(RuntimeError) as exc_info:
            await service_client.transfer_resource(
                service_name="test-service",
                resource_ids=["resource-1"],
                to_instance_id="other-instance",
            )
        assert "Not connected to NATS" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_timeout_handling(
        self, service_client: ServiceClient, resource_metadata: ResourceMetadata
    ) -> None:
        """Test timeout handling in bulk operations."""
        # Mock timeout
        service_client._nats_client.request.return_value = None

        # Test bulk register timeout
        with pytest.raises(TimeoutError) as exc_info:
            await service_client.bulk_register_resource(
                service_name="test-service",
                resources=[(f"resource-{i}", resource_metadata) for i in range(5)],
            )
        assert "timed out" in str(exc_info.value)

        # Test bulk release timeout
        with pytest.raises(TimeoutError) as exc_info:
            await service_client.bulk_release_resource(
                service_name="test-service",
                resource_ids=["resource-1"],
            )
        assert "timed out" in str(exc_info.value)

        # Test transfer timeout
        with pytest.raises(TimeoutError) as exc_info:
            await service_client.transfer_resource(
                service_name="test-service",
                resource_ids=["resource-1"],
                to_instance_id="other-instance",
            )
        assert "timed out" in str(exc_info.value)
