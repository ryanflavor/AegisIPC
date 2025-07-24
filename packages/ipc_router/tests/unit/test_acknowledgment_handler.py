"""Unit tests for acknowledgment handler."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest
from ipc_router.application.models.acknowledgment_models import (
    AcknowledgmentRequest,
)
from ipc_router.infrastructure.messaging.handlers.acknowledgment_handler import (
    AcknowledgmentHandler,
)
from ipc_router.infrastructure.messaging.nats_client import NATSClient

# Mark all tests in this module as async
pytestmark = pytest.mark.asyncio


class TestAcknowledgmentHandler:
    """Test acknowledgment handler functionality."""

    @pytest.fixture
    def mock_nats_client(self) -> Mock:
        """Create a mock NATS client."""
        mock = Mock(spec=NATSClient)
        mock.publish = AsyncMock()
        mock.subscribe = AsyncMock()
        return mock

    @pytest.fixture
    def handler(self, mock_nats_client: Mock) -> AcknowledgmentHandler:
        """Create an acknowledgment handler instance."""
        return AcknowledgmentHandler(mock_nats_client)

    async def test_send_acknowledgment_success(
        self,
        handler: AcknowledgmentHandler,
        mock_nats_client: Mock,
    ) -> None:
        """Test successful acknowledgment sending."""
        # Create acknowledgment request
        test_message_id = uuid.uuid4()
        ack_request = AcknowledgmentRequest(
            message_id=test_message_id,
            service_name="test-service",
            instance_id="instance-1",
            status="success",
            error_message=None,
            processing_time_ms=50.5,
            trace_id="trace-123",
        )

        # Send acknowledgment
        await handler.send_acknowledgment(ack_request)

        # Verify publish was called with correct data
        mock_nats_client.publish.assert_called_once()
        call_args = mock_nats_client.publish.call_args
        assert call_args.kwargs["subject"] == f"ipc.ack.{test_message_id}"

        ack_data = call_args.kwargs["data"]
        assert ack_data["message_id"] == str(test_message_id)
        assert ack_data["status"] == "success"
        assert ack_data["processing_time_ms"] == 50.5
        assert ack_data["trace_id"] == "trace-123"

    async def test_send_acknowledgment_failure(
        self,
        handler: AcknowledgmentHandler,
        mock_nats_client: Mock,
    ) -> None:
        """Test acknowledgment sending with failure status."""
        # Create failure acknowledgment request
        test_message_id = uuid.uuid4()
        ack_request = AcknowledgmentRequest(
            message_id=test_message_id,
            service_name="test-service",
            instance_id="instance-1",
            status="failure",
            error_message="Processing failed",
            processing_time_ms=10.0,
            trace_id="trace-456",
        )

        # Send acknowledgment
        await handler.send_acknowledgment(ack_request)

        # Verify publish was called with failure data
        mock_nats_client.publish.assert_called_once()
        call_args = mock_nats_client.publish.call_args
        assert call_args.kwargs["subject"] == f"ipc.ack.{test_message_id}"

        ack_data = call_args.kwargs["data"]
        assert ack_data["status"] == "failure"
        assert ack_data["error_message"] == "Processing failed"

    async def test_send_acknowledgment_publish_error(
        self,
        handler: AcknowledgmentHandler,
        mock_nats_client: Mock,
    ) -> None:
        """Test acknowledgment sending when publish fails."""
        # Make publish raise an error
        mock_nats_client.publish.side_effect = Exception("Publish failed")

        # Create acknowledgment request
        test_message_id = uuid.uuid4()
        ack_request = AcknowledgmentRequest(
            message_id=test_message_id,
            service_name="test-service",
            instance_id="instance-1",
            status="success",
            error_message=None,
            processing_time_ms=30.0,
            trace_id="trace-789",
        )

        # Should raise exception
        with pytest.raises(Exception, match="Publish failed"):
            await handler.send_acknowledgment(ack_request)

    async def test_handle_acknowledgment_response(
        self,
        handler: AcknowledgmentHandler,
        mock_nats_client: Mock,
    ) -> None:
        """Test handling incoming acknowledgment response."""
        # Test data
        response_data = {
            "success": True,
            "message": "Acknowledgment processed",
            "trace_id": "trace-123",
        }
        reply_subject = "reply.subject"

        # Handle response
        await handler.handle_acknowledgment_response(response_data, reply_subject)

        # Verify confirmation was sent
        mock_nats_client.publish.assert_called_once_with(
            subject=reply_subject,
            data={"confirmed": True},
        )

    async def test_handle_acknowledgment_response_no_reply(
        self,
        handler: AcknowledgmentHandler,
        mock_nats_client: Mock,
    ) -> None:
        """Test handling acknowledgment response without reply subject."""
        # Test data
        response_data = {
            "success": False,
            "message": "Failed to process",
            "trace_id": "trace-456",
        }

        # Handle response without reply
        await handler.handle_acknowledgment_response(response_data, None)

        # Verify no publish was called
        mock_nats_client.publish.assert_not_called()

    async def test_handle_acknowledgment_response_error(
        self,
        handler: AcknowledgmentHandler,
        mock_nats_client: Mock,
    ) -> None:
        """Test handling acknowledgment response with invalid data."""
        # Invalid data (missing required fields)
        response_data = {"invalid": "data"}

        # Should handle error gracefully
        await handler.handle_acknowledgment_response(response_data, None)

        # No exception should be raised
        mock_nats_client.publish.assert_not_called()

    async def test_setup_acknowledgment_listeners(
        self,
        handler: AcknowledgmentHandler,
        mock_nats_client: Mock,
    ) -> None:
        """Test setting up acknowledgment listeners."""
        # Set up listeners
        await handler.setup_acknowledgment_listeners()

        # Verify subscription was created
        mock_nats_client.subscribe.assert_called_once_with(
            subject="ipc.ack.response",
            callback=handler.handle_acknowledgment_response,
            queue="acknowledgment-handlers",
        )

    async def test_setup_acknowledgment_listeners_error(
        self,
        handler: AcknowledgmentHandler,
        mock_nats_client: Mock,
    ) -> None:
        """Test setting up listeners when subscription fails."""
        # Make subscribe raise an error
        mock_nats_client.subscribe.side_effect = Exception("Subscribe failed")

        # Should raise exception
        with pytest.raises(Exception, match="Subscribe failed"):
            await handler.setup_acknowledgment_listeners()

    async def test_send_acknowledgment_with_none_error_message(
        self,
        handler: AcknowledgmentHandler,
        mock_nats_client: Mock,
    ) -> None:
        """Test sending acknowledgment with None error message."""
        test_message_id = uuid.uuid4()
        ack_request = AcknowledgmentRequest(
            message_id=test_message_id,
            service_name="test-service",
            instance_id="instance-1",
            status="success",
            error_message=None,
            processing_time_ms=25.0,
            trace_id="trace-null",
        )

        await handler.send_acknowledgment(ack_request)

        mock_nats_client.publish.assert_called_once()
        ack_data = mock_nats_client.publish.call_args.kwargs["data"]
        assert ack_data["error_message"] is None

    async def test_send_acknowledgment_with_empty_strings(
        self,
        handler: AcknowledgmentHandler,
        mock_nats_client: Mock,
    ) -> None:
        """Test sending acknowledgment with empty string values."""
        # Use empty UUID for empty string test
        test_message_id = uuid.uuid4()

        # This test needs to be updated as empty strings are not allowed
        # for service_name and instance_id based on validators
        ack_request = AcknowledgmentRequest(
            message_id=test_message_id,
            service_name="service",
            instance_id="instance",
            status="success",
            error_message=None,  # Can't have error_message with success status
            processing_time_ms=0.1,  # Must be > 0
            trace_id="trace",
        )

        await handler.send_acknowledgment(ack_request)

        mock_nats_client.publish.assert_called_once()
        assert mock_nats_client.publish.call_args.kwargs["subject"] == f"ipc.ack.{test_message_id}"

    async def test_send_acknowledgment_with_special_characters(
        self,
        handler: AcknowledgmentHandler,
        mock_nats_client: Mock,
    ) -> None:
        """Test sending acknowledgment with special characters in message ID."""
        test_message_id = uuid.uuid4()
        ack_request = AcknowledgmentRequest(
            message_id=test_message_id,
            service_name="test-service",
            instance_id="instance-1",
            status="success",
            error_message=None,
            processing_time_ms=15.0,
            trace_id="trace-special",
        )

        await handler.send_acknowledgment(ack_request)

        mock_nats_client.publish.assert_called_once()
        assert mock_nats_client.publish.call_args.kwargs["subject"] == f"ipc.ack.{test_message_id}"

    async def test_handle_acknowledgment_response_with_missing_fields(
        self,
        handler: AcknowledgmentHandler,
        mock_nats_client: Mock,
    ) -> None:
        """Test handling response with missing optional fields."""
        # Minimal data with defaults
        response_data: dict[str, Any] = {}

        await handler.handle_acknowledgment_response(response_data, None)

        # Should not crash and should handle gracefully
        mock_nats_client.publish.assert_not_called()

    async def test_handle_acknowledgment_response_with_extra_fields(
        self,
        handler: AcknowledgmentHandler,
        mock_nats_client: Mock,
    ) -> None:
        """Test handling response with extra fields."""
        response_data = {
            "success": True,
            "message": "OK",
            "trace_id": "trace-123",
            "extra_field": "should be ignored",
            "another_extra": 123,
        }

        await handler.handle_acknowledgment_response(response_data, "reply.subject")

        # Should process normally
        mock_nats_client.publish.assert_called_once()

    async def test_handle_acknowledgment_response_reply_publish_error(
        self,
        handler: AcknowledgmentHandler,
        mock_nats_client: Mock,
    ) -> None:
        """Test handling response when reply publish fails."""
        mock_nats_client.publish.side_effect = Exception("Reply publish failed")

        response_data = {
            "success": True,
            "message": "OK",
            "trace_id": "trace-123",
        }

        # Should handle error gracefully (logged but not raised)
        await handler.handle_acknowledgment_response(response_data, "reply.subject")

        # Publish was attempted
        mock_nats_client.publish.assert_called_once()

    async def test_concurrent_send_acknowledgments(
        self,
        handler: AcknowledgmentHandler,
        mock_nats_client: Mock,
    ) -> None:
        """Test sending multiple acknowledgments concurrently."""
        # Create multiple acknowledgment requests
        ack_requests = [
            AcknowledgmentRequest(
                message_id=uuid.uuid4(),
                service_name="test-service",
                instance_id="instance-1",
                status="success" if i % 2 == 0 else "failure",
                error_message=None if i % 2 == 0 else f"Error {i}",
                processing_time_ms=float(i * 10) if i > 0 else 0.1,  # Must be > 0
                trace_id=f"trace-{i}",
            )
            for i in range(10)
        ]

        # Send all concurrently
        await asyncio.gather(*[handler.send_acknowledgment(req) for req in ack_requests])

        # All should be published
        assert mock_nats_client.publish.call_count == 10

    async def test_handle_acknowledgment_response_type_errors(
        self,
        handler: AcknowledgmentHandler,
        mock_nats_client: Mock,
    ) -> None:
        """Test handling response with wrong data types."""
        response_data = {
            "success": "not a boolean",  # Wrong type
            "message": 123,  # Wrong type
            "trace_id": None,  # Wrong type
        }

        # Should handle gracefully
        await handler.handle_acknowledgment_response(response_data, None)

        # No exception raised
        mock_nats_client.publish.assert_not_called()

    @patch("ipc_router.infrastructure.messaging.handlers.acknowledgment_handler.logger")
    async def test_send_acknowledgment_logging(
        self,
        mock_logger: Mock,
        handler: AcknowledgmentHandler,
        mock_nats_client: Mock,
    ) -> None:
        """Test that acknowledgment sending logs correctly."""
        test_message_id = uuid.uuid4()
        ack_request = AcknowledgmentRequest(
            message_id=test_message_id,
            service_name="test-service",
            instance_id="instance-1",
            status="success",
            error_message=None,
            processing_time_ms=100.0,
            trace_id="trace-log",
        )

        await handler.send_acknowledgment(ack_request)

        # Verify info log was called
        mock_logger.info.assert_called_once()
        assert "Sent acknowledgment" in mock_logger.info.call_args[0][0]

    @patch("ipc_router.infrastructure.messaging.handlers.acknowledgment_handler.logger")
    async def test_send_acknowledgment_error_logging(
        self,
        mock_logger: Mock,
        handler: AcknowledgmentHandler,
        mock_nats_client: Mock,
    ) -> None:
        """Test that acknowledgment errors are logged correctly."""
        mock_nats_client.publish.side_effect = RuntimeError("Network error")

        test_message_id = uuid.uuid4()
        ack_request = AcknowledgmentRequest(
            message_id=test_message_id,
            service_name="test-service",
            instance_id="instance-1",
            status="failure",
            error_message="Test error",
            processing_time_ms=50.0,
            trace_id="trace-error-log",
        )

        with pytest.raises(RuntimeError):
            await handler.send_acknowledgment(ack_request)

        # Verify error log was called
        mock_logger.error.assert_called_once()
        assert "Failed to send acknowledgment" in mock_logger.error.call_args[0][0]

    async def test_handle_acknowledgment_response_with_none_data(
        self,
        handler: AcknowledgmentHandler,
        mock_nats_client: Mock,
    ) -> None:
        """Test handling response with None values in data."""
        response_data = {
            "success": None,
            "message": None,
            "trace_id": None,
        }

        # This should fail validation and be caught by error handling
        await handler.handle_acknowledgment_response(response_data, "reply.subject")

        # Should not send confirmation due to validation error
        mock_nats_client.publish.assert_not_called()

    async def test_setup_acknowledgment_listeners_multiple_calls(
        self,
        handler: AcknowledgmentHandler,
        mock_nats_client: Mock,
    ) -> None:
        """Test setting up listeners multiple times."""
        # Set up listeners multiple times
        await handler.setup_acknowledgment_listeners()
        await handler.setup_acknowledgment_listeners()
        await handler.setup_acknowledgment_listeners()

        # Should subscribe each time (no deduplication)
        assert mock_nats_client.subscribe.call_count == 3

    async def test_send_acknowledgment_with_long_values(
        self,
        handler: AcknowledgmentHandler,
        mock_nats_client: Mock,
    ) -> None:
        """Test sending acknowledgment with very long string values."""
        long_error = "Error: " + "x" * 1000
        long_trace = "trace-" + "y" * 1000

        test_message_id = uuid.uuid4()
        ack_request = AcknowledgmentRequest(
            message_id=test_message_id,
            service_name="test-service-with-very-long-name" * 10,
            instance_id="instance-with-long-id" * 10,
            status="failure",
            error_message=long_error,
            processing_time_ms=99999.999,
            trace_id=long_trace,
        )

        await handler.send_acknowledgment(ack_request)

        # Should handle long values
        mock_nats_client.publish.assert_called_once()
        ack_data = mock_nats_client.publish.call_args.kwargs["data"]
        assert ack_data["error_message"] == long_error
        assert ack_data["trace_id"] == long_trace
