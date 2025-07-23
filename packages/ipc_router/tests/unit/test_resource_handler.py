"""Unit tests for resource handler."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from ipc_router.application.models import (
    ResourceMetadata,
)
from ipc_router.application.services import ResourceService
from ipc_router.domain.entities import Resource
from ipc_router.domain.exceptions import (
    ResourceConflictError,
    ResourceNotFoundError,
    ValidationError,
)
from ipc_router.infrastructure.messaging.handlers.resource_handler import ResourceHandler


@pytest.fixture
def mock_resource_service() -> AsyncMock:
    """Create a mock resource service."""
    return AsyncMock(spec=ResourceService)


@pytest.fixture
def mock_nats_client() -> AsyncMock:
    """Create a mock NATS client."""
    return AsyncMock()


@pytest.fixture
def resource_handler(
    mock_nats_client: AsyncMock, mock_resource_service: AsyncMock
) -> ResourceHandler:
    """Create a resource handler with mocked dependencies."""
    return ResourceHandler(mock_nats_client, mock_resource_service)


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


@pytest.fixture
def sample_resource(sample_metadata: ResourceMetadata) -> Resource:
    """Create a sample resource."""
    return Resource(
        resource_id="user-123",
        owner_instance_id="user-service-1",
        service_name="user-service",
        registered_at=datetime.now(UTC),
        metadata=sample_metadata,
    )


class TestResourceHandler:
    """Test cases for ResourceHandler."""

    @pytest.mark.asyncio
    async def test_start_subscribes_to_subjects(
        self, resource_handler: ResourceHandler, mock_nats_client: AsyncMock
    ) -> None:
        """Test that start subscribes to the correct subjects."""
        await resource_handler.start()

        # Verify subscriptions
        calls = mock_nats_client.subscribe.call_args_list
        assert len(calls) == 2

        # Check registration subscription
        assert calls[0][1]["subject"] == "ipc.resource.register"
        assert calls[0][1]["queue"] == "resource-registry"

        # Check release subscription
        assert calls[1][1]["subject"] == "ipc.resource.release"
        assert calls[1][1]["queue"] == "resource-registry"

    @pytest.mark.asyncio
    async def test_stop_unsubscribes_from_subjects(
        self, resource_handler: ResourceHandler, mock_nats_client: AsyncMock
    ) -> None:
        """Test that stop unsubscribes from the correct subjects."""
        await resource_handler.stop()

        # Verify unsubscriptions
        calls = mock_nats_client.unsubscribe.call_args_list
        assert len(calls) == 2
        assert calls[0][0][0] == "ipc.resource.register"
        assert calls[1][0][0] == "ipc.resource.release"

    @pytest.mark.asyncio
    async def test_handle_registration_success(
        self,
        resource_handler: ResourceHandler,
        mock_nats_client: AsyncMock,
        mock_resource_service: AsyncMock,
        sample_metadata: ResourceMetadata,
    ) -> None:
        """Test successful resource registration."""
        # Create separate resources for each ID
        resource1 = Resource(
            resource_id="user-123",
            owner_instance_id="user-service-1",
            service_name="user-service",
            registered_at=datetime.now(UTC),
            metadata=sample_metadata,
        )
        resource2 = Resource(
            resource_id="user-456",
            owner_instance_id="user-service-1",
            service_name="user-service",
            registered_at=datetime.now(UTC),
            metadata=sample_metadata,
        )

        # Mock returns different resources for each call
        mock_resource_service.register_resource.side_effect = [resource1, resource2]

        data = {
            "service_name": "user-service",
            "instance_id": "user-service-1",
            "resource_ids": ["user-123", "user-456"],
            "force": False,
            "metadata": {
                "user-123": sample_metadata.model_dump(),
            },
            "trace_id": "trace-abc-123",
        }

        await resource_handler._handle_registration(data, "reply-subject")

        # Verify service was called
        assert mock_resource_service.register_resource.call_count == 2

        # Verify response was published
        mock_nats_client.publish.assert_called_once()
        call_args = mock_nats_client.publish.call_args[1]
        assert call_args["subject"] == "reply-subject"

        response_data = call_args["data"]
        assert response_data["success"] is True
        assert len(response_data["registered"]) == 2
        assert "user-123" in response_data["registered"]
        assert "user-456" in response_data["registered"]
        assert response_data["conflicts"] == {}
        assert response_data["trace_id"] == "trace-abc-123"

    @pytest.mark.asyncio
    async def test_handle_registration_with_conflicts(
        self,
        resource_handler: ResourceHandler,
        mock_nats_client: AsyncMock,
        mock_resource_service: AsyncMock,
        sample_resource: Resource,
    ) -> None:
        """Test resource registration with conflicts."""
        # First resource succeeds
        mock_resource_service.register_resource.side_effect = [
            sample_resource,
            ResourceConflictError(
                resource_id="user-456",
                current_owner="user-service-2",
            ),
        ]

        data = {
            "service_name": "user-service",
            "instance_id": "user-service-1",
            "resource_ids": ["user-123", "user-456"],
            "force": False,
            "metadata": {},
            "trace_id": "trace-abc-123",
        }

        await resource_handler._handle_registration(data, "reply-subject")

        # Verify response
        mock_nats_client.publish.assert_called_once()
        call_args = mock_nats_client.publish.call_args[1]
        response_data = call_args["data"]

        assert response_data["success"] is False
        assert "user-123" in response_data["registered"]
        assert response_data["conflicts"]["user-456"] == "user-service-2"

    @pytest.mark.asyncio
    async def test_handle_registration_with_force(
        self,
        resource_handler: ResourceHandler,
        mock_nats_client: AsyncMock,
        mock_resource_service: AsyncMock,
        sample_resource: Resource,
    ) -> None:
        """Test resource registration with force=True ignores conflicts."""
        # Both resources succeed because force=True
        mock_resource_service.register_resource.return_value = sample_resource

        data = {
            "service_name": "user-service",
            "instance_id": "user-service-1",
            "resource_ids": ["user-123", "user-456"],
            "force": True,
            "metadata": {},
            "trace_id": "trace-abc-123",
        }

        await resource_handler._handle_registration(data, "reply-subject")

        # Verify both resources were registered with force=True
        calls = mock_resource_service.register_resource.call_args_list
        assert len(calls) == 2
        assert calls[0][1]["force"] is True
        assert calls[1][1]["force"] is True

        # Verify successful response
        mock_nats_client.publish.assert_called_once()
        response_data = mock_nats_client.publish.call_args[1]["data"]
        assert response_data["success"] is True
        assert len(response_data["registered"]) == 2

    @pytest.mark.asyncio
    async def test_handle_registration_missing_reply_subject(
        self,
        resource_handler: ResourceHandler,
        mock_nats_client: AsyncMock,
    ) -> None:
        """Test registration request without reply subject is ignored."""
        data = {
            "service_name": "user-service",
            "instance_id": "user-service-1",
            "resource_ids": ["user-123"],
            "trace_id": "trace-abc-123",
        }

        await resource_handler._handle_registration(data, None)

        # Verify no response was sent
        mock_nats_client.publish.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_registration_validation_error(
        self,
        resource_handler: ResourceHandler,
        mock_nats_client: AsyncMock,
    ) -> None:
        """Test registration with invalid data."""
        # Invalid data missing required fields
        invalid_data = {
            "service_name": "user-service",
            # Missing instance_id and resource_ids
            "trace_id": "trace-abc-123",
        }

        await resource_handler._handle_registration(invalid_data, "reply-subject")

        # Verify error response
        mock_nats_client.publish.assert_called_once()
        call_args = mock_nats_client.publish.call_args[1]
        response_data = call_args["data"]

        assert response_data["success"] is False
        assert response_data["error"]["code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_handle_release_success(
        self,
        resource_handler: ResourceHandler,
        mock_nats_client: AsyncMock,
        mock_resource_service: AsyncMock,
    ) -> None:
        """Test successful resource release."""
        mock_resource_service.release_resource.return_value = True

        data = {
            "service_name": "user-service",
            "instance_id": "user-service-1",
            "resource_ids": ["user-123", "user-456"],
            "trace_id": "trace-abc-123",
        }

        await resource_handler._handle_release(data, "reply-subject")

        # Verify service was called
        assert mock_resource_service.release_resource.call_count == 2

        # Verify response
        mock_nats_client.publish.assert_called_once()
        response_data = mock_nats_client.publish.call_args[1]["data"]

        assert response_data["success"] is True
        assert "user-123" in response_data["released"]
        assert "user-456" in response_data["released"]
        assert response_data["errors"] == {}

    @pytest.mark.asyncio
    async def test_handle_release_with_errors(
        self,
        resource_handler: ResourceHandler,
        mock_nats_client: AsyncMock,
        mock_resource_service: AsyncMock,
    ) -> None:
        """Test resource release with some failures."""
        # First succeeds, second fails
        mock_resource_service.release_resource.side_effect = [
            True,
            ResourceNotFoundError("Resource not found"),
        ]

        data = {
            "service_name": "user-service",
            "instance_id": "user-service-1",
            "resource_ids": ["user-123", "user-456"],
            "trace_id": "trace-abc-123",
        }

        await resource_handler._handle_release(data, "reply-subject")

        # Verify response
        mock_nats_client.publish.assert_called_once()
        response_data = mock_nats_client.publish.call_args[1]["data"]

        assert response_data["success"] is False
        assert "user-123" in response_data["released"]
        assert response_data["errors"]["user-456"] == "Resource not found"

    @pytest.mark.asyncio
    async def test_handle_release_validation_error_per_resource(
        self,
        resource_handler: ResourceHandler,
        mock_nats_client: AsyncMock,
        mock_resource_service: AsyncMock,
    ) -> None:
        """Test resource release with validation error for specific resource."""
        # First succeeds, second has validation error
        mock_resource_service.release_resource.side_effect = [
            True,
            ValidationError("Invalid resource ID format"),
        ]

        data = {
            "service_name": "user-service",
            "instance_id": "user-service-1",
            "resource_ids": ["user-123", "invalid-resource"],
            "trace_id": "trace-abc-123",
        }

        await resource_handler._handle_release(data, "reply-subject")

        # Verify response
        mock_nats_client.publish.assert_called_once()
        response_data = mock_nats_client.publish.call_args[1]["data"]

        assert response_data["success"] is False
        assert "user-123" in response_data["released"]
        assert "Validation error:" in response_data["errors"]["invalid-resource"]

    @pytest.mark.asyncio
    async def test_handle_release_missing_reply_subject(
        self,
        resource_handler: ResourceHandler,
        mock_nats_client: AsyncMock,
    ) -> None:
        """Test release request without reply subject is ignored."""
        data = {
            "service_name": "user-service",
            "instance_id": "user-service-1",
            "resource_ids": ["user-123"],
            "trace_id": "trace-abc-123",
        }

        await resource_handler._handle_release(data, None)

        # Verify no response was sent
        mock_nats_client.publish.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_error_response(
        self,
        resource_handler: ResourceHandler,
        mock_nats_client: AsyncMock,
    ) -> None:
        """Test sending error response."""
        await resource_handler._send_error_response(
            reply_subject="reply-subject",
            error_code="TEST_ERROR",
            message="Test error message",
            details={"detail": "value"},
        )

        mock_nats_client.publish.assert_called_once_with(
            subject="reply-subject",
            data={
                "success": False,
                "error": {
                    "code": "TEST_ERROR",
                    "message": "Test error message",
                    "details": {"detail": "value"},
                },
            },
        )

    @pytest.mark.asyncio
    async def test_send_error_response_handles_publish_failure(
        self,
        resource_handler: ResourceHandler,
        mock_nats_client: AsyncMock,
    ) -> None:
        """Test error response handles publish failures gracefully."""
        mock_nats_client.publish.side_effect = Exception("Network error")

        # Should not raise exception
        await resource_handler._send_error_response(
            reply_subject="reply-subject",
            error_code="TEST_ERROR",
            message="Test error message",
        )

        # Verify publish was attempted
        mock_nats_client.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_registration_unexpected_error(
        self,
        resource_handler: ResourceHandler,
        mock_nats_client: AsyncMock,
        mock_resource_service: AsyncMock,
    ) -> None:
        """Test registration handles unexpected errors."""
        mock_resource_service.register_resource.side_effect = Exception("Unexpected error")

        data = {
            "service_name": "user-service",
            "instance_id": "user-service-1",
            "resource_ids": ["user-123"],
            "metadata": {},
            "trace_id": "trace-abc-123",
        }

        await resource_handler._handle_registration(data, "reply-subject")

        # Verify error response
        mock_nats_client.publish.assert_called_once()
        response_data = mock_nats_client.publish.call_args[1]["data"]

        assert response_data["success"] is False
        assert response_data["error"]["code"] == "INTERNAL_ERROR"

    @pytest.mark.asyncio
    async def test_handle_release_unexpected_error(
        self,
        resource_handler: ResourceHandler,
        mock_nats_client: AsyncMock,
        mock_resource_service: AsyncMock,
    ) -> None:
        """Test release handles unexpected errors."""
        mock_resource_service.release_resource.side_effect = Exception("Unexpected error")

        data = {
            "service_name": "user-service",
            "instance_id": "user-service-1",
            "resource_ids": ["user-123"],
            "trace_id": "trace-abc-123",
        }

        await resource_handler._handle_release(data, "reply-subject")

        # Verify error response
        mock_nats_client.publish.assert_called_once()
        response_data = mock_nats_client.publish.call_args[1]["data"]

        assert response_data["success"] is False
        assert response_data["error"]["code"] == "INTERNAL_ERROR"
