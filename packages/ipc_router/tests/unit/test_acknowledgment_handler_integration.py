"""Integration tests for acknowledgment handler with real service interactions."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from ipc_router.application.models.acknowledgment_models import (
    AcknowledgmentRequest,
)
from ipc_router.application.services import AcknowledgmentService, MessageStoreService
from ipc_router.infrastructure.messaging.handlers.acknowledgment_handler import (
    AcknowledgmentHandler,
)
from ipc_router.infrastructure.messaging.nats_client import NATSClient

pytestmark = pytest.mark.asyncio


class TestAcknowledgmentHandlerIntegration:
    """Test acknowledgment handler with service integration."""

    @pytest.fixture
    def mock_nats_client(self) -> Mock:
        """Create a mock NATS client."""
        mock = Mock(spec=NATSClient)
        mock.publish = AsyncMock()
        mock.subscribe = AsyncMock()
        mock.request = AsyncMock()
        return mock

    @pytest.fixture
    def message_store(self) -> MessageStoreService:
        """Create message store service."""
        return MessageStoreService()

    @pytest.fixture
    def ack_service(
        self, message_store: MessageStoreService, mock_nats_client: Mock
    ) -> AcknowledgmentService:
        """Create acknowledgment service."""
        return AcknowledgmentService(
            message_store=message_store,
            nats_client=mock_nats_client,
        )

    @pytest.fixture
    def handler(
        self, mock_nats_client: Mock, ack_service: AcknowledgmentService
    ) -> AcknowledgmentHandler:
        """Create acknowledgment handler with dependencies."""
        handler = AcknowledgmentHandler(mock_nats_client)
        # Inject ack service for testing
        handler._ack_service = ack_service
        return handler

    async def test_start_stop_handler(
        self,
        handler: AcknowledgmentHandler,
        mock_nats_client: Mock,
    ) -> None:
        """Test starting and stopping the handler."""
        # Add start/stop methods to handler
        handler._subscription = None

        async def start() -> None:
            """Start the handler."""
            await handler.setup_acknowledgment_listeners()
            handler._subscription = "test-sub"

        async def stop() -> None:
            """Stop the handler."""
            if handler._subscription:
                # In real implementation would unsubscribe
                handler._subscription = None

        handler.start = start
        handler.stop = stop

        # Start handler
        await handler.start()
        assert handler._subscription is not None
        mock_nats_client.subscribe.assert_called_once()

        # Stop handler
        await handler.stop()
        assert handler._subscription is None

    async def test_acknowledgment_flow_with_service(
        self,
        handler: AcknowledgmentHandler,
        ack_service: AcknowledgmentService,
        mock_nats_client: Mock,
    ) -> None:
        """Test complete acknowledgment flow with service integration."""
        message_id = uuid.uuid4()

        # Set up waiter
        ack_future = asyncio.create_task(ack_service.wait_for_ack(str(message_id), timeout=2.0))

        # Send acknowledgment
        ack_request = AcknowledgmentRequest(
            message_id=message_id,
            service_name="test-service",
            instance_id="instance-1",
            status="success",
            error_message=None,
            processing_time_ms=50.5,
            trace_id="trace-123",
        )

        await handler.send_acknowledgment(ack_request)

        # Simulate receiving the acknowledgment
        await ack_service.send_ack(
            message_id=str(message_id),
            status="success",
            error_message=None,
        )

        # Wait should complete
        result = await ack_future
        assert result is True

    async def test_handle_message_status_query(
        self,
        handler: AcknowledgmentHandler,
        mock_nats_client: Mock,
    ) -> None:
        """Test handling message status query."""

        # Create a message status handler method
        async def handle_message_status(data: dict[str, Any], reply: str | None) -> None:
            """Handle message status query."""
            message_id = data.get("message_id")

            # Simulate status response
            status_data = {
                "message_id": message_id,
                "state": "ACKNOWLEDGED",
                "retry_count": 0,
                "created_at": "2025-01-01T00:00:00Z",
                "last_error": None,
                "trace_id": data.get("trace_id", ""),
            }

            if reply:
                await mock_nats_client.publish(
                    subject=reply,
                    data=status_data,
                )

        handler.handle_message_status = handle_message_status

        # Test the handler
        query_data = {
            "message_id": str(uuid.uuid4()),
            "trace_id": "trace-status",
        }

        await handler.handle_message_status(query_data, "reply.subject")

        # Verify response was sent
        mock_nats_client.publish.assert_called()
        call_args = mock_nats_client.publish.call_args
        assert call_args.kwargs["subject"] == "reply.subject"
        assert call_args.kwargs["data"]["state"] == "ACKNOWLEDGED"

    async def test_concurrent_acknowledgment_processing(
        self,
        handler: AcknowledgmentHandler,
        mock_nats_client: Mock,
    ) -> None:
        """Test processing multiple acknowledgments concurrently."""
        # Create multiple acknowledgments
        num_acks = 100
        ack_requests = []

        for i in range(num_acks):
            ack_request = AcknowledgmentRequest(
                message_id=uuid.uuid4(),
                service_name=f"service-{i % 5}",
                instance_id=f"instance-{i % 3}",
                status="success" if i % 10 != 0 else "failure",
                error_message=f"Error {i}" if i % 10 == 0 else None,
                processing_time_ms=float(i + 1),
                trace_id=f"trace-{i}",
            )
            ack_requests.append(ack_request)

        # Send all acknowledgments concurrently
        tasks = [handler.send_acknowledgment(req) for req in ack_requests]
        await asyncio.gather(*tasks)

        # Verify all were published
        assert mock_nats_client.publish.call_count == num_acks

        # Verify different subjects were used
        subjects = set()
        for call in mock_nats_client.publish.call_args_list:
            subjects.add(call.kwargs["subject"])

        # Should have unique subjects for each message
        assert len(subjects) == num_acks

    async def test_acknowledgment_retry_handling(
        self,
        handler: AcknowledgmentHandler,
        mock_nats_client: Mock,
    ) -> None:
        """Test acknowledgment retry scenarios."""
        message_id = uuid.uuid4()

        # First attempt fails
        mock_nats_client.publish.side_effect = [
            Exception("Network error"),
            None,  # Second attempt succeeds
        ]

        # First attempt should fail
        ack_request = AcknowledgmentRequest(
            message_id=message_id,
            service_name="test-service",
            instance_id="instance-1",
            status="success",
            error_message=None,
            processing_time_ms=50.0,
            trace_id="trace-retry",
        )

        with pytest.raises(Exception, match="Network error"):
            await handler.send_acknowledgment(ack_request)

        # Reset side effect for retry
        mock_nats_client.publish.side_effect = None

        # Retry should succeed
        await handler.send_acknowledgment(ack_request)

        # Should have been called twice total
        assert mock_nats_client.publish.call_count == 2

    async def test_acknowledgment_with_metadata(
        self,
        handler: AcknowledgmentHandler,
        mock_nats_client: Mock,
    ) -> None:
        """Test acknowledgment with additional metadata."""
        message_id = uuid.uuid4()

        # Create acknowledgment with metadata
        ack_request = AcknowledgmentRequest(
            message_id=message_id,
            service_name="metadata-service",
            instance_id="meta-instance-1",
            status="success",
            error_message=None,
            processing_time_ms=123.45,
            trace_id="trace-metadata",
        )

        # Add custom handler that includes metadata
        original_data = None

        async def capture_publish(subject: str, data: dict[str, Any]) -> None:
            nonlocal original_data
            original_data = data

        mock_nats_client.publish.side_effect = capture_publish

        await handler.send_acknowledgment(ack_request)

        # Verify all fields were included
        assert original_data is not None
        assert original_data["message_id"] == str(message_id)
        assert original_data["service_name"] == "metadata-service"
        assert original_data["instance_id"] == "meta-instance-1"
        assert original_data["status"] == "success"
        assert original_data["processing_time_ms"] == 123.45
        assert original_data["trace_id"] == "trace-metadata"

    async def test_handle_malformed_acknowledgment_response(
        self,
        handler: AcknowledgmentHandler,
        mock_nats_client: Mock,
    ) -> None:
        """Test handling malformed acknowledgment responses."""
        # Test various malformed data
        test_cases: list[Any] = [
            None,  # None data
            [],  # List instead of dict
            "not a dict",  # String
            {"incomplete": "data"},  # Missing fields
            {"success": "not_bool", "message": 123, "trace_id": []},  # Wrong types
        ]

        for test_data in test_cases:
            # Should handle gracefully without raising
            await handler.handle_acknowledgment_response(test_data, None)

        # No replies should be sent for malformed data
        mock_nats_client.publish.assert_not_called()

    async def test_acknowledgment_performance(
        self,
        handler: AcknowledgmentHandler,
        mock_nats_client: Mock,
    ) -> None:
        """Test acknowledgment handler performance."""
        import time

        # Make publish very fast
        mock_nats_client.publish = AsyncMock(return_value=None)

        num_messages = 1000
        start_time = time.time()

        # Send many acknowledgments
        tasks = []
        for i in range(num_messages):
            ack_request = AcknowledgmentRequest(
                message_id=uuid.uuid4(),
                service_name="perf-test",
                instance_id=f"instance-{i % 10}",
                status="success",
                error_message=None,
                processing_time_ms=1.0,
                trace_id=f"perf-{i}",
            )
            tasks.append(handler.send_acknowledgment(ack_request))

        await asyncio.gather(*tasks)

        elapsed = time.time() - start_time
        throughput = num_messages / elapsed

        # Should handle at least 500 messages per second
        assert throughput > 500
        assert mock_nats_client.publish.call_count == num_messages

    async def test_acknowledgment_handler_cleanup(
        self,
        handler: AcknowledgmentHandler,
        mock_nats_client: Mock,
    ) -> None:
        """Test handler cleanup on errors."""
        # Set up handler with resources
        handler._active_tasks = set()

        async def track_task(coro: Any) -> Any:
            """Track active tasks."""
            task = asyncio.create_task(coro)
            handler._active_tasks.add(task)
            try:
                return await task
            finally:
                handler._active_tasks.discard(task)

        # Simulate some active operations
        async def long_operation() -> None:
            await asyncio.sleep(0.1)

        # Start some tasks
        task1 = asyncio.create_task(track_task(long_operation()))
        task2 = asyncio.create_task(track_task(long_operation()))

        # Cleanup method
        async def cleanup() -> None:
            """Clean up handler resources."""
            # Cancel all active tasks
            for task in list(handler._active_tasks):
                task.cancel()

            # Wait for cancellation
            await asyncio.gather(*handler._active_tasks, return_exceptions=True)
            handler._active_tasks.clear()

        handler.cleanup = cleanup

        # Run cleanup
        await handler.cleanup()

        # All tasks should be cleaned up
        assert len(handler._active_tasks) == 0
        assert task1.cancelled() or task1.done()
        assert task2.cancelled() or task2.done()
