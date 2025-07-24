"""Unit tests for Message entity."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from ipc_router.domain.entities import Message, MessageState


class TestMessageEntity:
    """Test cases for Message entity."""

    @pytest.fixture
    def valid_message_data(self) -> dict:
        """Provide valid message data for testing."""
        now = datetime.now(UTC)
        return {
            "message_id": "msg_12345678",
            "service_name": "test-service",
            "method": "test_method",
            "params": {"key": "value"},
            "state": MessageState.PENDING,
            "created_at": now,
            "updated_at": now,
            "ack_deadline": now + timedelta(seconds=30),
            "trace_id": "trace_123",
        }

    def test_message_creation_with_valid_data(self, valid_message_data: dict) -> None:
        """Test creating a message with valid data."""
        message = Message(**valid_message_data)

        assert message.message_id == "msg_12345678"
        assert message.service_name == "test-service"
        assert message.method == "test_method"
        assert message.params == {"key": "value"}
        assert message.state == MessageState.PENDING
        assert message.trace_id == "trace_123"
        assert message.resource_id is None
        assert message.retry_count == 0
        assert message.last_error is None
        assert message.response is None

    def test_message_creation_with_resource_id(self, valid_message_data: dict) -> None:
        """Test creating a message with resource ID."""
        valid_message_data["resource_id"] = "resource_123"
        message = Message(**valid_message_data)

        assert message.resource_id == "resource_123"

    def test_message_validation_empty_message_id(self, valid_message_data: dict) -> None:
        """Test that empty message ID raises ValueError."""
        valid_message_data["message_id"] = ""

        with pytest.raises(ValueError, match="Message ID cannot be empty"):
            Message(**valid_message_data)

    def test_message_validation_empty_service_name(self, valid_message_data: dict) -> None:
        """Test that empty service name raises ValueError."""
        valid_message_data["service_name"] = ""

        with pytest.raises(ValueError, match="Service name cannot be empty"):
            Message(**valid_message_data)

    def test_message_validation_empty_method(self, valid_message_data: dict) -> None:
        """Test that empty method raises ValueError."""
        valid_message_data["method"] = ""

        with pytest.raises(ValueError, match="Method name cannot be empty"):
            Message(**valid_message_data)

    def test_message_validation_empty_trace_id(self, valid_message_data: dict) -> None:
        """Test that empty trace ID raises ValueError."""
        valid_message_data["trace_id"] = ""

        with pytest.raises(ValueError, match="Trace ID cannot be empty"):
            Message(**valid_message_data)

    def test_timezone_normalization(self, valid_message_data: dict) -> None:
        """Test that timestamps without timezone are normalized to UTC."""
        # Use naive datetimes
        now = datetime.now()
        valid_message_data["created_at"] = now
        valid_message_data["updated_at"] = now
        valid_message_data["ack_deadline"] = now + timedelta(seconds=30)

        message = Message(**valid_message_data)

        assert message.created_at.tzinfo == UTC
        assert message.updated_at.tzinfo == UTC
        assert message.ack_deadline.tzinfo == UTC

    def test_is_expired_not_expired(self, valid_message_data: dict) -> None:
        """Test is_expired returns False for non-expired message."""
        future_deadline = datetime.now(UTC) + timedelta(hours=1)
        valid_message_data["ack_deadline"] = future_deadline
        message = Message(**valid_message_data)

        assert not message.is_expired()

    def test_is_expired_expired(self, valid_message_data: dict) -> None:
        """Test is_expired returns True for expired message."""
        past_deadline = datetime.now(UTC) - timedelta(hours=1)
        valid_message_data["ack_deadline"] = past_deadline
        message = Message(**valid_message_data)

        assert message.is_expired()

    def test_can_retry_valid(self, valid_message_data: dict) -> None:
        """Test can_retry returns True for eligible message."""
        message = Message(**valid_message_data)

        assert message.can_retry()
        assert message.can_retry(max_retries=5)

    def test_can_retry_max_retries_exceeded(self, valid_message_data: dict) -> None:
        """Test can_retry returns False when retry limit exceeded."""
        valid_message_data["retry_count"] = 3
        message = Message(**valid_message_data)

        assert not message.can_retry(max_retries=3)
        assert message.can_retry(max_retries=4)

    def test_can_retry_expired(self, valid_message_data: dict) -> None:
        """Test can_retry returns False for expired message."""
        past_deadline = datetime.now(UTC) - timedelta(hours=1)
        valid_message_data["ack_deadline"] = past_deadline
        message = Message(**valid_message_data)

        assert not message.can_retry()

    def test_can_retry_wrong_state(self, valid_message_data: dict) -> None:
        """Test can_retry returns False for non-pending states."""
        for state in [MessageState.ACKNOWLEDGED, MessageState.FAILED, MessageState.EXPIRED]:
            valid_message_data["state"] = state
            message = Message(**valid_message_data)
            assert not message.can_retry()

    def test_increment_retry(self, valid_message_data: dict) -> None:
        """Test increment_retry updates retry count and timestamp."""
        message = Message(**valid_message_data)
        original_updated_at = message.updated_at

        message.increment_retry("Test error")

        assert message.retry_count == 1
        assert message.last_error == "Test error"
        assert message.updated_at > original_updated_at

    def test_increment_retry_without_error(self, valid_message_data: dict) -> None:
        """Test increment_retry without error message."""
        message = Message(**valid_message_data)

        message.increment_retry()

        assert message.retry_count == 1
        assert message.last_error is None

    def test_mark_acknowledged(self, valid_message_data: dict) -> None:
        """Test mark_acknowledged updates state and response."""
        message = Message(**valid_message_data)
        original_updated_at = message.updated_at
        response_data = {"result": "success"}

        message.mark_acknowledged(response_data)

        assert message.state == MessageState.ACKNOWLEDGED
        assert message.response == response_data
        assert message.updated_at > original_updated_at

    def test_mark_acknowledged_without_response(self, valid_message_data: dict) -> None:
        """Test mark_acknowledged without response data."""
        message = Message(**valid_message_data)

        message.mark_acknowledged()

        assert message.state == MessageState.ACKNOWLEDGED
        assert message.response is None

    def test_mark_failed(self, valid_message_data: dict) -> None:
        """Test mark_failed updates state and error."""
        message = Message(**valid_message_data)
        original_updated_at = message.updated_at

        message.mark_failed("Processing failed")

        assert message.state == MessageState.FAILED
        assert message.last_error == "Processing failed"
        assert message.updated_at > original_updated_at

    def test_mark_expired(self, valid_message_data: dict) -> None:
        """Test mark_expired updates state."""
        message = Message(**valid_message_data)
        original_updated_at = message.updated_at

        message.mark_expired()

        assert message.state == MessageState.EXPIRED
        assert message.updated_at > original_updated_at


class TestMessageState:
    """Test cases for MessageState enum."""

    def test_message_state_values(self) -> None:
        """Test MessageState enum has expected values."""
        assert MessageState.PENDING.value == "pending"
        assert MessageState.ACKNOWLEDGED.value == "acknowledged"
        assert MessageState.FAILED.value == "failed"
        assert MessageState.EXPIRED.value == "expired"

    def test_message_state_members(self) -> None:
        """Test MessageState has all expected members."""
        expected_states = {"PENDING", "ACKNOWLEDGED", "FAILED", "EXPIRED"}
        actual_states = {state.name for state in MessageState}
        assert actual_states == expected_states
