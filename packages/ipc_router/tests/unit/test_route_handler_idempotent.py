"""Unit tests for RouteRequestHandler with idempotent handling."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from ipc_router.application.models.routing_models import RouteResponse
from ipc_router.application.services import RoutingService
from ipc_router.domain.entities.message import Message, MessageState
from ipc_router.infrastructure.messaging.handlers import RouteRequestHandler

pytestmark = pytest.mark.asyncio


class TestRouteRequestHandlerIdempotent:
    """Test RouteRequestHandler with idempotent functionality."""

    @pytest.fixture
    def mock_nats_client(self) -> AsyncMock:
        """Create a mock NATS client."""
        client = AsyncMock()
        client.subscribe = AsyncMock()
        client.unsubscribe = AsyncMock()
        client.publish = AsyncMock()
        return client

    @pytest.fixture
    def mock_routing_service(self) -> AsyncMock:
        """Create a mock routing service."""
        service = AsyncMock(spec=RoutingService)
        # Default successful routing response
        service.route_request.return_value = RouteResponse(
            success=True,
            instance_id="instance-123",
            trace_id="trace-123",
            duration_ms=10.0,
        )
        return service

    @pytest.fixture
    def mock_message_store(self) -> AsyncMock:
        """Create a mock message store."""
        return AsyncMock()

    @pytest.fixture
    def route_handler_with_idempotency(
        self,
        mock_nats_client: AsyncMock,
        mock_routing_service: AsyncMock,
        mock_message_store: AsyncMock,
    ) -> RouteRequestHandler:
        """Create a RouteRequestHandler with idempotent handling enabled."""
        return RouteRequestHandler(
            nats_client=mock_nats_client,
            routing_service=mock_routing_service,
            message_store=mock_message_store,
            route_subject="ipc.route.request",
        )

    @pytest.fixture
    def route_handler_without_idempotency(
        self, mock_nats_client: AsyncMock, mock_routing_service: AsyncMock
    ) -> RouteRequestHandler:
        """Create a RouteRequestHandler without idempotent handling."""
        return RouteRequestHandler(
            nats_client=mock_nats_client,
            routing_service=mock_routing_service,
            message_store=None,
            route_subject="ipc.route.request",
        )

    @pytest.fixture
    def sample_request_data(self) -> dict:
        """Create sample request data."""
        return {
            "service_name": "test-service",
            "message_id": str(uuid.uuid4()),
            "method": "test_method",
            "params": {"key": "value"},
            "timeout": 5.0,
            "trace_id": "trace-123",
        }

    @pytest.fixture
    def sample_message(self, sample_request_data: dict) -> Message:
        """Create a sample message."""
        return Message(
            message_id=sample_request_data["message_id"],
            service_name=sample_request_data["service_name"],
            resource_id=None,
            method=sample_request_data["method"],
            params=sample_request_data["params"],
            state=MessageState.PENDING,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            retry_count=0,
            ack_deadline=datetime.now(UTC) + timedelta(seconds=30),
            trace_id=sample_request_data["trace_id"],
        )

    async def test_idempotent_handling_new_message(
        self,
        route_handler_with_idempotency: RouteRequestHandler,
        mock_message_store: AsyncMock,
        mock_routing_service: AsyncMock,
        mock_nats_client: AsyncMock,
        sample_request_data: dict,
        sample_message: Message,
    ) -> None:
        """Test handling a new message with idempotency enabled."""
        # Setup
        mock_message_store.is_duplicate.return_value = False
        mock_message_store.get_message.return_value = sample_message
        reply_subject = "reply.123"

        # Execute
        await route_handler_with_idempotency._handle_route_request(
            sample_request_data, reply_subject
        )

        # Assert
        mock_message_store.is_duplicate.assert_called_once_with(sample_request_data["message_id"])
        mock_routing_service.route_request.assert_called_once()
        # Should proceed to forward the request
        assert mock_nats_client.publish.call_count >= 1

    async def test_idempotent_handling_duplicate_message(
        self,
        route_handler_with_idempotency: RouteRequestHandler,
        mock_message_store: AsyncMock,
        mock_routing_service: AsyncMock,
        mock_nats_client: AsyncMock,
        sample_request_data: dict,
        sample_message: Message,
    ) -> None:
        """Test handling a duplicate message with cached response."""
        # Setup
        cached_response = RouteResponse(
            success=True,
            result={"cached": "result"},
            instance_id="instance-123",
            trace_id="trace-123",
            duration_ms=5.0,
        )
        sample_message.state = MessageState.ACKNOWLEDGED
        sample_message.response = cached_response

        mock_message_store.is_duplicate.return_value = True
        mock_message_store.get_message.return_value = sample_message
        reply_subject = "reply.123"

        # Execute
        # The DuplicateMessageError should be caught inside _handle_route_request
        await route_handler_with_idempotency._handle_route_request(
            sample_request_data, reply_subject
        )

        # Assert
        mock_message_store.is_duplicate.assert_called_once_with(sample_request_data["message_id"])
        # Should not call routing service for duplicate
        mock_routing_service.route_request.assert_not_called()
        # Should send cached response
        mock_nats_client.publish.assert_called_once()
        call_args = mock_nats_client.publish.call_args[0]
        assert call_args[0] == reply_subject
        # Verify response was sent (either as RouteResponse.model_dump or directly)
        response_data = call_args[1]
        if isinstance(response_data, dict):
            assert response_data.get("result") == {"cached": "result"}
            assert response_data.get("success") is True

    async def test_no_idempotency_when_disabled(
        self,
        route_handler_without_idempotency: RouteRequestHandler,
        mock_routing_service: AsyncMock,
        mock_nats_client: AsyncMock,
        sample_request_data: dict,
    ) -> None:
        """Test that idempotency is not applied when message_store is None."""
        # Setup
        reply_subject = "reply.123"

        # Execute
        await route_handler_without_idempotency._handle_route_request(
            sample_request_data, reply_subject
        )

        # Assert
        # Should process normally without checking for duplicates
        mock_routing_service.route_request.assert_called_once()
        assert mock_nats_client.publish.call_count >= 1

    async def test_handle_request_without_message_id(
        self,
        route_handler_with_idempotency: RouteRequestHandler,
        mock_message_store: AsyncMock,
        mock_routing_service: AsyncMock,
        sample_request_data: dict,
    ) -> None:
        """Test handling request without message_id."""
        # Setup
        request_data = sample_request_data.copy()
        del request_data["message_id"]
        reply_subject = "reply.123"

        # Execute
        await route_handler_with_idempotency._handle_route_request(request_data, reply_subject)

        # Assert
        # Should process without idempotency check
        mock_message_store.is_duplicate.assert_not_called()
        mock_routing_service.route_request.assert_called_once()

    async def test_error_during_idempotent_processing(
        self,
        route_handler_with_idempotency: RouteRequestHandler,
        mock_message_store: AsyncMock,
        mock_nats_client: AsyncMock,
        sample_request_data: dict,
        sample_message: Message,
    ) -> None:
        """Test error handling during idempotent processing."""
        # Setup
        mock_message_store.is_duplicate.return_value = False
        mock_message_store.get_message.return_value = sample_message
        # Make routing service fail
        mock_routing_service = route_handler_with_idempotency._routing_service
        mock_routing_service.route_request.side_effect = ValueError("Processing failed")
        reply_subject = "reply.123"

        # Execute
        await route_handler_with_idempotency._handle_route_request(
            sample_request_data, reply_subject
        )

        # Assert
        # Should update message state to failed
        mock_message_store.update_message_state.assert_called_once_with(
            sample_request_data["message_id"], MessageState.FAILED.value, None, "Processing failed"
        )
        # Should send error response
        assert mock_nats_client.publish.called
        call_args = mock_nats_client.publish.call_args[0]
        assert call_args[0] == reply_subject
        response_data = call_args[1]
        assert not response_data["success"]
        assert response_data["error"]["type"] == "ValueError"

    async def test_duplicate_without_cached_response(
        self,
        route_handler_with_idempotency: RouteRequestHandler,
        mock_message_store: AsyncMock,
        mock_routing_service: AsyncMock,
        sample_request_data: dict,
        sample_message: Message,
    ) -> None:
        """Test handling duplicate message without cached response."""
        # Setup
        sample_message.response = None  # No cached response
        mock_message_store.is_duplicate.return_value = True
        mock_message_store.get_message.return_value = sample_message
        reply_subject = "reply.123"

        # Execute
        await route_handler_with_idempotency._handle_route_request(
            sample_request_data, reply_subject
        )

        # Assert
        # Should reprocess the request
        mock_routing_service.route_request.assert_called_once()

    async def test_concurrent_duplicate_requests(
        self,
        route_handler_with_idempotency: RouteRequestHandler,
        mock_message_store: AsyncMock,
        mock_routing_service: AsyncMock,
        mock_nats_client: AsyncMock,
        sample_request_data: dict,
        sample_message: Message,
    ) -> None:
        """Test handling concurrent duplicate requests."""
        # Setup
        call_count = 0

        async def is_duplicate_side_effect(msg_id: str) -> bool:
            nonlocal call_count
            call_count += 1
            return call_count > 1

        mock_message_store.is_duplicate.side_effect = is_duplicate_side_effect
        mock_message_store.get_message.return_value = sample_message
        reply_subject = "reply.123"

        # First request should process normally
        await route_handler_with_idempotency._handle_route_request(
            sample_request_data, reply_subject
        )
        assert mock_routing_service.route_request.call_count == 1

        # Second request should be detected as duplicate
        sample_message.state = MessageState.ACKNOWLEDGED
        sample_message.response = RouteResponse(
            success=True,
            result={"cached": "result"},
            instance_id="instance-123",
            trace_id="trace-123",
            duration_ms=5.0,
        )

        # Reset mock
        mock_nats_client.publish.reset_mock()

        await route_handler_with_idempotency._handle_route_request(
            sample_request_data, reply_subject
        )

        # Should send cached response
        assert mock_routing_service.route_request.call_count == 1  # Still 1
        mock_nats_client.publish.assert_called_once()
        response_data = mock_nats_client.publish.call_args[0][1]
        assert response_data["result"] == {"cached": "result"}
