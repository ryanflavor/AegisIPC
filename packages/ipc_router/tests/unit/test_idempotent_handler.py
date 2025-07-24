"""Unit tests for idempotent handler decorator."""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from ipc_router.application.decorators import idempotent_handler
from ipc_router.domain.entities.message import Message, MessageState
from ipc_router.domain.exceptions import DuplicateMessageError

pytestmark = pytest.mark.asyncio


class TestIdempotentHandler:
    """Test cases for idempotent handler decorator."""

    @pytest.fixture
    def mock_message_store(self) -> AsyncMock:
        """Create a mock message store."""
        return AsyncMock()

    @pytest.fixture
    def sample_message(self) -> Message:
        """Create a sample message."""
        return Message(
            message_id="test-msg-123",
            service_name="test-service",
            resource_id=None,
            method="test_method",
            params={"key": "value"},
            state=MessageState.PENDING,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            retry_count=0,
            ack_deadline=datetime.now(UTC) + timedelta(seconds=30),
            trace_id="trace-123",
        )

    async def test_process_new_message_successfully(
        self, mock_message_store: AsyncMock, sample_message: Message
    ) -> None:
        """Test processing a new message successfully."""
        # Setup
        mock_message_store.is_duplicate.return_value = False
        mock_message_store.get_message.return_value = sample_message

        @idempotent_handler(
            message_store=mock_message_store,
            message_id_getter=lambda req: req.get("message_id"),
        )
        async def handler(request: dict[str, Any]) -> dict[str, Any]:
            return {"result": "success", "data": request["data"]}

        # Execute
        request = {"message_id": "test-msg-123", "data": "test-data"}
        result = await handler(request)

        # Assert
        assert result == {"result": "success", "data": "test-data"}
        mock_message_store.is_duplicate.assert_called_once_with("test-msg-123")
        assert mock_message_store.update_message_state.call_count == 1
        mock_message_store.store_message.assert_called_once()

    async def test_return_cached_response_for_duplicate(
        self, mock_message_store: AsyncMock, sample_message: Message
    ) -> None:
        """Test returning cached response for duplicate message."""
        # Setup
        cached_response = {"result": "cached", "data": "previous"}
        sample_message.state = MessageState.ACKNOWLEDGED
        sample_message.response = cached_response

        mock_message_store.is_duplicate.return_value = True
        mock_message_store.get_message.return_value = sample_message

        @idempotent_handler(
            message_store=mock_message_store,
            message_id_getter=lambda req: req.get("message_id"),
        )
        async def handler(request: dict[str, Any]) -> dict[str, Any]:
            return {"result": "new", "data": "should not see this"}

        # Execute
        request = {"message_id": "test-msg-123", "data": "test-data"}

        with pytest.raises(DuplicateMessageError) as exc_info:
            await handler(request)

        # Assert
        assert exc_info.value.message_id == "test-msg-123"
        assert exc_info.value.cached_response == cached_response
        mock_message_store.is_duplicate.assert_called_once_with("test-msg-123")

    async def test_reprocess_duplicate_without_cached_response(
        self, mock_message_store: AsyncMock, sample_message: Message
    ) -> None:
        """Test reprocessing duplicate message without cached response."""
        # Setup
        sample_message.response = None
        mock_message_store.is_duplicate.return_value = True
        mock_message_store.get_message.return_value = sample_message

        @idempotent_handler(
            message_store=mock_message_store,
            message_id_getter=lambda req: req.get("message_id"),
        )
        async def handler(request: dict[str, Any]) -> dict[str, Any]:
            return {"result": "reprocessed", "data": request["data"]}

        # Execute
        request = {"message_id": "test-msg-123", "data": "test-data"}
        result = await handler(request)

        # Assert
        assert result == {"result": "reprocessed", "data": "test-data"}
        mock_message_store.is_duplicate.assert_called_once_with("test-msg-123")
        assert mock_message_store.update_message_state.call_count == 1

    async def test_handle_no_message_id(self, mock_message_store: AsyncMock) -> None:
        """Test handling request without message_id."""

        # Setup
        @idempotent_handler(
            message_store=mock_message_store,
            message_id_getter=lambda req: req.get("message_id"),
        )
        async def handler(request: dict[str, Any]) -> dict[str, Any]:
            return {"result": "success", "data": request["data"]}

        # Execute
        request = {"data": "test-data"}  # No message_id
        result = await handler(request)

        # Assert
        assert result == {"result": "success", "data": "test-data"}
        mock_message_store.is_duplicate.assert_not_called()

    async def test_handle_processing_failure(
        self, mock_message_store: AsyncMock, sample_message: Message
    ) -> None:
        """Test handling failure during message processing."""
        # Setup
        mock_message_store.is_duplicate.return_value = False
        mock_message_store.get_message.return_value = sample_message

        @idempotent_handler(
            message_store=mock_message_store,
            message_id_getter=lambda req: req.get("message_id"),
        )
        async def handler(request: dict[str, Any]) -> dict[str, Any]:
            raise ValueError("Processing failed")

        # Execute
        request = {"message_id": "test-msg-123", "data": "test-data"}

        with pytest.raises(ValueError, match="Processing failed"):
            await handler(request)

        # Assert
        mock_message_store.is_duplicate.assert_called_once_with("test-msg-123")
        mock_message_store.update_message_state.assert_called_once_with(
            "test-msg-123", MessageState.FAILED.value, None, "Processing failed"
        )

    async def test_sync_function_raises_error(self, mock_message_store: AsyncMock) -> None:
        """Test decorator raises error for sync functions."""

        # Setup
        def sync_func(request: dict[str, Any]) -> dict[str, Any]:
            return {"result": "sync"}

        # Assert that decorator raises TypeError for sync function
        with pytest.raises(
            TypeError, match="idempotent_handler can only be applied to async functions"
        ):
            idempotent_handler(
                message_store=mock_message_store,
                message_id_getter=lambda req: None,
            )(sync_func)

    async def test_complex_message_id_getter(
        self, mock_message_store: AsyncMock, sample_message: Message
    ) -> None:
        """Test using complex message_id getter function."""
        # Setup
        mock_message_store.is_duplicate.return_value = False
        mock_message_store.get_message.return_value = sample_message

        @idempotent_handler(
            message_store=mock_message_store,
            message_id_getter=lambda self, req, **kwargs: req.headers.get("X-Message-ID"),
        )
        async def handler(self: Any, request: Any, **kwargs: Any) -> dict[str, Any]:
            return {"result": "success"}

        # Create mock objects
        mock_self = MagicMock()
        mock_request = MagicMock()
        mock_request.headers = {"X-Message-ID": "test-msg-123"}

        # Execute
        result = await handler(mock_self, mock_request, extra="data")

        # Assert
        assert result == {"result": "success"}
        mock_message_store.is_duplicate.assert_called_once_with("test-msg-123")

    async def test_concurrent_duplicate_requests(
        self, mock_message_store: AsyncMock, sample_message: Message
    ) -> None:
        """Test handling concurrent duplicate requests."""
        # Setup
        call_count = 0

        async def is_duplicate_side_effect(msg_id: str) -> bool:
            nonlocal call_count
            call_count += 1
            # First call returns False, subsequent return True
            return call_count > 1

        mock_message_store.is_duplicate.side_effect = is_duplicate_side_effect
        mock_message_store.get_message.return_value = sample_message

        @idempotent_handler(
            message_store=mock_message_store,
            message_id_getter=lambda req: req.get("message_id"),
        )
        async def handler(request: dict[str, Any]) -> dict[str, Any]:
            return {"result": "success", "call": call_count}

        # Execute
        request = {"message_id": "test-msg-123", "data": "test-data"}

        # First call should succeed
        result1 = await handler(request)
        assert result1 == {"result": "success", "call": 1}

        # Second call should be detected as duplicate
        sample_message.state = MessageState.ACKNOWLEDGED
        sample_message.response = result1

        with pytest.raises(DuplicateMessageError) as exc_info:
            await handler(request)

        assert exc_info.value.cached_response == result1
