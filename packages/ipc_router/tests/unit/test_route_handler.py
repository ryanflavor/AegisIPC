"""Unit tests for RouteHandler."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from ipc_router.application.models.routing_models import RouteResponse
from ipc_router.application.services import RoutingService
from ipc_router.infrastructure.messaging.handlers import RouteRequestHandler as RouteHandler


class TestRouteHandler:
    """Test RouteHandler functionality."""

    @pytest.fixture
    def mock_nats_client(self) -> AsyncMock:
        """Create a mock NATS client."""
        client = AsyncMock()
        client.subscribe = AsyncMock()
        client.unsubscribe = AsyncMock()
        return client

    @pytest.fixture
    def mock_routing_service(self) -> AsyncMock:
        """Create a mock routing service."""
        service = AsyncMock(spec=RoutingService)
        return service

    @pytest.fixture
    def route_handler(
        self, mock_nats_client: AsyncMock, mock_routing_service: AsyncMock
    ) -> RouteHandler:
        """Create a RouteHandler instance."""
        return RouteHandler(
            nats_client=mock_nats_client,
            routing_service=mock_routing_service,
            route_subject="ipc.route.request",
        )

    @pytest.mark.asyncio
    async def test_start_subscribes_to_subject(
        self, route_handler: RouteHandler, mock_nats_client: AsyncMock
    ) -> None:
        """Test that start subscribes to the correct subject."""
        await route_handler.start()

        mock_nats_client.subscribe.assert_called_once_with(
            "ipc.route.request", callback=route_handler._handle_route_request
        )

    @pytest.mark.asyncio
    async def test_stop_unsubscribes(
        self, route_handler: RouteHandler, mock_nats_client: AsyncMock
    ) -> None:
        """Test that stop unsubscribes from NATS."""
        # Start first to create subscription
        await route_handler.start()

        # Stop handler
        await route_handler.stop()

        mock_nats_client.unsubscribe.assert_called_once_with("ipc.route.request")

    @pytest.mark.asyncio
    async def test_stop_when_not_started(
        self, route_handler: RouteHandler, mock_nats_client: AsyncMock
    ) -> None:
        """Test stop when handler was not started."""
        await route_handler.stop()
        # Stop should still call unsubscribe even if not started
        mock_nats_client.unsubscribe.assert_called_once_with("ipc.route.request")

    @pytest.mark.asyncio
    async def test_handle_route_request_success(
        self,
        route_handler: RouteHandler,
        mock_routing_service: AsyncMock,
        mock_nats_client: AsyncMock,
    ) -> None:
        """Test successful route request handling."""
        # Create test data
        request_data = {
            "service_name": "test-service",
            "method": "test_method",
            "params": {"key": "value"},
            "timeout": 30.0,
            "trace_id": "trace-123",
        }

        # Mock routing service response
        mock_response = RouteResponse(
            success=True,
            result={"message": "Request routed successfully"},
            instance_id="instance-1",
            trace_id="trace-123",
        )
        mock_routing_service.route_request.return_value = mock_response

        # Mock forward_request to avoid complexity
        route_handler._forward_request = AsyncMock()

        # Handle request
        await route_handler._handle_route_request(request_data, "reply.subject")

        # Verify routing service was called
        mock_routing_service.route_request.assert_called_once()

        # Verify forward_request was called
        route_handler._forward_request.assert_called_once()
        forward_args = route_handler._forward_request.call_args[0]
        assert forward_args[0].service_name == "test-service"
        assert forward_args[1] == "instance-1"
        assert forward_args[2] == "reply.subject"

    @pytest.mark.asyncio
    async def test_handle_route_request_no_instance_found(
        self,
        route_handler: RouteHandler,
        mock_routing_service: AsyncMock,
        mock_nats_client: AsyncMock,
    ) -> None:
        """Test handling when no instance is found."""
        # Create test data
        request_data = {
            "service_name": "unknown-service",
            "method": "test_method",
            "params": {},
            "timeout": 30.0,
            "trace_id": "trace-456",
        }

        # Mock routing service to return unsuccessful response
        mock_response = RouteResponse(
            success=False,
            error={"type": "ServiceNotFound", "message": "Service not found", "code": 404},
            trace_id="trace-456",
        )
        mock_routing_service.route_request.return_value = mock_response

        # Mock send_response
        route_handler._send_response = AsyncMock()

        # Handle request
        await route_handler._handle_route_request(request_data, "reply.subject")

        # Verify send_response was called with error
        route_handler._send_response.assert_called_once()
        args = route_handler._send_response.call_args[0]
        assert args[0] == "reply.subject"
        assert args[1].success is False

    @pytest.mark.asyncio
    async def test_handle_route_request_invalid_data(
        self,
        route_handler: RouteHandler,
        mock_nats_client: AsyncMock,
    ) -> None:
        """Test handling invalid request data."""
        # Invalid data (not a dict)
        invalid_data = "invalid json data"

        # Mock send_response
        route_handler._send_response = AsyncMock()

        # Handle request
        await route_handler._handle_route_request(invalid_data, "reply.subject")

        # Verify error response was sent
        route_handler._send_response.assert_called_once()
        args = route_handler._send_response.call_args[0]
        assert args[0] == "reply.subject"
        response = args[1]
        assert response.success is False
        assert response.error is not None
        assert response.error["type"] == "TypeError"

    @pytest.mark.asyncio
    async def test_handle_route_request_missing_fields(
        self,
        route_handler: RouteHandler,
        mock_nats_client: AsyncMock,
    ) -> None:
        """Test handling request with missing required fields."""
        # Create test data missing required fields
        request_data = {
            "service_name": "test-service",
            # Missing method, params, timeout, trace_id
        }

        # Mock send_response
        route_handler._send_response = AsyncMock()

        # Handle request
        await route_handler._handle_route_request(request_data, "reply.subject")

        # Verify error response was sent
        route_handler._send_response.assert_called_once()
        args = route_handler._send_response.call_args[0]
        assert args[0] == "reply.subject"
        response = args[1]
        assert response.success is False

    @pytest.mark.asyncio
    async def test_handle_route_request_routing_error(
        self,
        route_handler: RouteHandler,
        mock_routing_service: AsyncMock,
        mock_nats_client: AsyncMock,
    ) -> None:
        """Test handling when routing service raises an error."""
        # Create test data
        request_data = {
            "service_name": "test-service",
            "method": "test_method",
            "params": {"key": "value"},
            "timeout": 30.0,
            "trace_id": "trace-789",
        }

        # Mock routing service to raise error
        mock_routing_service.route_request.side_effect = Exception("Routing failed")

        # Mock send_response
        route_handler._send_response = AsyncMock()

        # Handle request
        await route_handler._handle_route_request(request_data, "reply.subject")

        # Verify error response was sent
        route_handler._send_response.assert_called_once()
        args = route_handler._send_response.call_args[0]
        assert args[0] == "reply.subject"
        response = args[1]
        assert response.success is False
        assert response.error["message"] == "Routing failed"

    @pytest.mark.asyncio
    async def test_handle_route_request_no_reply_subject(
        self,
        route_handler: RouteHandler,
        mock_routing_service: AsyncMock,
        mock_nats_client: AsyncMock,
    ) -> None:
        """Test handling request without reply subject."""
        # Create test data
        request_data = {
            "service_name": "test-service",
            "method": "test_method",
            "params": {},
            "timeout": 30.0,
            "trace_id": "trace-999",
        }

        # Mock routing service response
        mock_response = RouteResponse(
            success=True,
            result={"message": "success"},
            instance_id="instance-1",
            trace_id="trace-999",
        )
        mock_routing_service.route_request.return_value = mock_response

        # Mock forward_request to check it's called even without reply subject
        route_handler._forward_request = AsyncMock()

        # Handle request with None reply subject - should not crash
        await route_handler._handle_route_request(request_data, None)

        # Verify forward_request was still called
        route_handler._forward_request.assert_called_once()

    @pytest.mark.asyncio
    async def test_concurrent_route_requests(
        self,
        route_handler: RouteHandler,
        mock_routing_service: AsyncMock,
        mock_nats_client: AsyncMock,
    ) -> None:
        """Test handling multiple concurrent route requests."""
        # Mock routing service response
        mock_response = RouteResponse(
            success=True,
            instance_id="instance-1",
            trace_id="trace-{i}",
        )
        mock_routing_service.route_request.return_value = mock_response

        # Mock forward_request
        route_handler._forward_request = AsyncMock()

        # Create multiple requests
        requests = []
        for i in range(10):
            request_data = {
                "service_name": "test-service",
                "method": f"method_{i}",
                "params": {"index": i},
                "timeout": 30.0,
                "trace_id": f"trace-{i}",
            }
            requests.append((request_data, f"reply.{i}"))

        # Handle all requests concurrently
        tasks = [route_handler._handle_route_request(data, reply) for data, reply in requests]
        await asyncio.gather(*tasks)

        # Verify all requests were processed
        assert mock_routing_service.route_request.call_count == 10
        assert route_handler._forward_request.call_count == 10

    @pytest.mark.asyncio
    async def test_handle_route_request_with_resource_id(
        self,
        route_handler: RouteHandler,
        mock_routing_service: AsyncMock,
        mock_nats_client: AsyncMock,
    ) -> None:
        """Test routing request with resource_id."""
        # Create test data with resource_id
        request_data = {
            "service_name": "test-service",
            "resource_id": "resource-123",
            "method": "process_resource",
            "params": {"action": "update"},
            "timeout": 30.0,
            "trace_id": "trace-resource",
        }

        # Mock routing service response
        mock_response = RouteResponse(
            success=True,
            instance_id="resource-owner-1",
            trace_id="trace-resource",
        )
        mock_routing_service.route_request.return_value = mock_response

        # Mock forward_request
        route_handler._forward_request = AsyncMock()

        # Handle request
        await route_handler._handle_route_request(request_data, "reply.subject")

        # Verify routing service was called with RouteRequest containing resource_id
        mock_routing_service.route_request.assert_called_once()
        route_request = mock_routing_service.route_request.call_args[0][0]
        assert route_request.resource_id == "resource-123"

        # Verify forward_request was called
        route_handler._forward_request.assert_called_once()
        forward_args = route_handler._forward_request.call_args[0]
        assert forward_args[1] == "resource-owner-1"
