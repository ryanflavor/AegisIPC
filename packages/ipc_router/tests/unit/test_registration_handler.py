"""Unit tests for registration handler."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from ipc_client_sdk.models import ServiceRegistrationResponse
from ipc_router.domain.exceptions import ConflictError
from ipc_router.infrastructure.messaging.handlers.registration_handler import (
    RegistrationHandler,
)


@pytest.fixture
def mock_service_registry() -> AsyncMock:
    """Create a mock service registry."""
    mock_registry = AsyncMock()
    return mock_registry


@pytest.fixture
def mock_nats_client() -> AsyncMock:
    """Create a mock NATS client."""
    return AsyncMock()


@pytest.fixture
def registration_handler(
    mock_nats_client: AsyncMock, mock_service_registry: AsyncMock
) -> RegistrationHandler:
    """Create a registration handler with mocked dependencies."""
    return RegistrationHandler(mock_nats_client, mock_service_registry)


@pytest.fixture
def mock_registration_response() -> ServiceRegistrationResponse:
    """Create a mock registration response."""
    return ServiceRegistrationResponse(
        success=True,
        service_name="test-service",
        instance_id="instance-1",
        registered_at=datetime.now(UTC),
        message="Service registered successfully",
    )


class TestRegistrationHandler:
    """Test cases for RegistrationHandler."""

    @pytest.mark.asyncio
    async def test_handle_registration_success(
        self,
        registration_handler: RegistrationHandler,
        mock_nats_client: AsyncMock,
        mock_service_registry: AsyncMock,
        mock_registration_response: ServiceRegistrationResponse,
    ) -> None:
        """Test successful service registration."""
        mock_service_registry.register_service.return_value = mock_registration_response

        data = {
            "service_name": "test-service",
            "instance_id": "instance-1",
            "metadata": {"version": "1.0", "endpoint": "http://localhost:8080"},
        }

        # Test the _handle_registration method directly
        await registration_handler._handle_registration(data, "reply-subject")

        # Verify service registry was called with ServiceRegistrationRequest
        mock_service_registry.register_service.assert_called_once()
        call_args = mock_service_registry.register_service.call_args[0][0]
        assert call_args.service_name == "test-service"
        assert call_args.instance_id == "instance-1"
        assert call_args.metadata == {"version": "1.0", "endpoint": "http://localhost:8080"}

        # Verify response was published
        mock_nats_client.publish.assert_called_once_with(
            subject="reply-subject",
            data={
                "success": True,
                "service_name": "test-service",
                "instance_id": "instance-1",
                "registered_at": mock_registration_response.registered_at.isoformat(),
                "message": "Service registered successfully",
            },
        )

    @pytest.mark.asyncio
    async def test_handle_registration_invalid_data(
        self,
        registration_handler: RegistrationHandler,
        mock_nats_client: AsyncMock,
        mock_service_registry: AsyncMock,
    ) -> None:
        """Test registration with invalid message data (missing fields)."""
        # Invalid data missing required fields
        invalid_data = {"service_name": "test-service"}  # Missing instance_id

        await registration_handler._handle_registration(invalid_data, "reply-subject")

        # Service registry should not be called
        mock_service_registry.register_service.assert_not_called()

        # Error response should be sent
        mock_nats_client.publish.assert_called_once()
        call_args = mock_nats_client.publish.call_args[1]["data"]
        assert call_args["success"] is False
        assert "error" in call_args

    @pytest.mark.asyncio
    async def test_handle_registration_missing_fields(
        self,
        registration_handler: RegistrationHandler,
        mock_nats_client: AsyncMock,
        mock_service_registry: AsyncMock,
    ) -> None:
        """Test registration with missing required fields."""
        # Missing instance_id
        data = {"service_name": "test-service"}

        await registration_handler._handle_registration(data, "reply-subject")

        # Service registry should not be called
        mock_service_registry.register_service.assert_not_called()

        # Error response should be sent via _send_error_response
        mock_nats_client.publish.assert_called_once()
        call_args = mock_nats_client.publish.call_args[1]["data"]
        assert call_args["success"] is False
        assert "error" in call_args

    @pytest.mark.asyncio
    async def test_handle_registration_service_error(
        self,
        registration_handler: RegistrationHandler,
        mock_nats_client: AsyncMock,
        mock_service_registry: AsyncMock,
    ) -> None:
        """Test registration when service registry raises an error."""
        mock_service_registry.register_service.side_effect = RuntimeError(
            "Database connection failed"
        )

        data = {
            "service_name": "test-service",
            "instance_id": "instance-1",
            "metadata": {"version": "1.0"},
        }

        await registration_handler._handle_registration(data, "reply-subject")

        # Error response should be sent
        mock_nats_client.publish.assert_called_once()
        call_args = mock_nats_client.publish.call_args[1]["data"]
        assert call_args["success"] is False
        assert "error" in call_args
        assert call_args["error"]["code"] == "INTERNAL_ERROR"

    @pytest.mark.asyncio
    async def test_handle_registration_no_reply_subject(
        self,
        registration_handler: RegistrationHandler,
        mock_nats_client: AsyncMock,
        mock_service_registry: AsyncMock,
    ) -> None:
        """Test registration when message has no reply subject."""
        data = {
            "service_name": "test-service",
            "instance_id": "instance-1",
            "metadata": {"version": "1.0"},
        }

        # When reply_subject is None, method should return early
        await registration_handler._handle_registration(data, None)

        # Service should not be registered
        mock_service_registry.register_service.assert_not_called()

        # No response should be sent
        mock_nats_client.publish.assert_not_called()

    @pytest.mark.asyncio
    async def test_start_handler(
        self,
        registration_handler: RegistrationHandler,
        mock_nats_client: AsyncMock,
        mock_service_registry: AsyncMock,
    ) -> None:
        """Test handler start lifecycle."""
        # Start the handler
        await registration_handler.start()

        # Verify subscription was created with correct parameters
        mock_nats_client.subscribe.assert_called_once_with(
            subject="ipc.service.register",
            callback=registration_handler._handle_registration,
            queue="service-registry",
        )

    @pytest.mark.asyncio
    async def test_send_error_response(
        self,
        registration_handler: RegistrationHandler,
        mock_nats_client: AsyncMock,
    ) -> None:
        """Test error response sending."""
        await registration_handler._send_error_response(
            reply_subject="test-reply",
            error_code="TEST_ERROR",
            message="Test error message",
            details={"additional": "info"},
        )

        mock_nats_client.publish.assert_called_once_with(
            subject="test-reply",
            data={
                "success": False,
                "error": {
                    "code": "TEST_ERROR",
                    "message": "Test error message",
                    "details": {"additional": "info"},
                },
            },
        )

    @pytest.mark.asyncio
    async def test_handle_registration_with_role(
        self,
        registration_handler: RegistrationHandler,
        mock_service_registry: AsyncMock,
        mock_nats_client: AsyncMock,
    ) -> None:
        """Test registration with role specified."""
        # Mock registration response with role
        mock_response = ServiceRegistrationResponse(
            success=True,
            service_name="test-service",
            instance_id="instance-1",
            role="ACTIVE",
            registered_at=datetime.now(UTC),
            message="Service registered successfully as ACTIVE",
        )
        mock_service_registry.register_service.return_value = mock_response

        # Test data with role
        test_data = {
            "service_name": "test-service",
            "instance_id": "instance-1",
            "role": "active",
            "metadata": {"resource_id": "res_123"},
        }

        await registration_handler._handle_registration(test_data, "test-reply")

        # Verify service registry was called
        mock_service_registry.register_service.assert_called_once()
        called_request = mock_service_registry.register_service.call_args[0][0]
        assert called_request.role == "active"

        # Verify response includes role
        mock_nats_client.publish.assert_called_once()
        response_data = mock_nats_client.publish.call_args[1]["data"]
        assert response_data["role"] == "ACTIVE"
        assert response_data["success"] is True

    @pytest.mark.asyncio
    async def test_handle_registration_default_role(
        self,
        registration_handler: RegistrationHandler,
        mock_service_registry: AsyncMock,
        mock_nats_client: AsyncMock,
    ) -> None:
        """Test registration defaults to STANDBY role when not specified."""
        # Mock registration response with default role
        mock_response = ServiceRegistrationResponse(
            success=True,
            service_name="test-service",
            instance_id="instance-1",
            role="STANDBY",
            registered_at=datetime.now(UTC),
            message="Service registered successfully as STANDBY",
        )
        mock_service_registry.register_service.return_value = mock_response

        # Test data without role
        test_data = {
            "service_name": "test-service",
            "instance_id": "instance-1",
            "metadata": {},
        }

        await registration_handler._handle_registration(test_data, "test-reply")

        # Verify service registry was called
        mock_service_registry.register_service.assert_called_once()
        called_request = mock_service_registry.register_service.call_args[0][0]
        assert called_request.role == "standby"  # Should default to standby

        # Verify response includes default role
        mock_nats_client.publish.assert_called_once()
        response_data = mock_nats_client.publish.call_args[1]["data"]
        assert response_data["role"] == "STANDBY"

    @pytest.mark.asyncio
    async def test_handle_registration_role_conflict(
        self,
        registration_handler: RegistrationHandler,
        mock_service_registry: AsyncMock,
        mock_nats_client: AsyncMock,
    ) -> None:
        """Test handling of role conflict errors."""
        # Mock service registry to raise ConflictError
        mock_service_registry.register_service.side_effect = ConflictError(
            "Resource res_123 already has an active instance: service1/instance1"
        )

        test_data = {
            "service_name": "test-service",
            "instance_id": "instance-2",
            "role": "active",
            "metadata": {"resource_id": "res_123"},
        }

        await registration_handler._handle_registration(test_data, "test-reply")

        # Verify error response was sent
        mock_nats_client.publish.assert_called_once()
        response_data = mock_nats_client.publish.call_args[1]["data"]
        assert response_data["success"] is False
        assert response_data["error"]["code"] == "ROLE_CONFLICT"
        assert "already has an active instance" in response_data["error"]["message"]
