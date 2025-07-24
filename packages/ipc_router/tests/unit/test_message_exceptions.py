"""Unit tests for message-related exceptions."""

from __future__ import annotations

from ipc_router.domain.exceptions import (
    AcknowledgmentTimeoutError,
    DuplicateMessageError,
    MessageExpiredError,
    MessageStorageError,
)


class TestDuplicateMessageError:
    """Test cases for DuplicateMessageError."""

    def test_duplicate_message_error_without_cached_response(self) -> None:
        """Test DuplicateMessageError without cached response."""
        error = DuplicateMessageError(message_id="msg_123")

        assert str(error) == "Message 'msg_123' has already been processed"
        assert error.error_code == "DUPLICATE_MESSAGE"
        assert error.details["message_id"] == "msg_123"
        assert error.details["has_cached_response"] is False
        assert error.cached_response is None

    def test_duplicate_message_error_with_cached_response(self) -> None:
        """Test DuplicateMessageError with cached response."""
        cached_data = {"result": "success", "data": [1, 2, 3]}
        error = DuplicateMessageError(message_id="msg_456", cached_response=cached_data)

        assert str(error) == "Message 'msg_456' has already been processed"
        assert error.error_code == "DUPLICATE_MESSAGE"
        assert error.details["message_id"] == "msg_456"
        assert error.details["has_cached_response"] is True
        assert error.cached_response == cached_data

    def test_duplicate_message_error_with_additional_details(self) -> None:
        """Test DuplicateMessageError with additional details."""
        error = DuplicateMessageError(
            message_id="msg_789",
            cached_response={"data": "test"},
            details={"service": "test-service", "method": "test_method"},
        )

        assert error.details["message_id"] == "msg_789"
        assert error.details["has_cached_response"] is True
        assert error.details["service"] == "test-service"
        assert error.details["method"] == "test_method"


class TestMessageExpiredError:
    """Test cases for MessageExpiredError."""

    def test_message_expired_error_basic(self) -> None:
        """Test MessageExpiredError with basic information."""
        error = MessageExpiredError(
            message_id="msg_001",
            expired_at="2024-01-15T10:00:00Z",
            created_at="2024-01-15T09:30:00Z",
        )

        assert str(error) == "Message 'msg_001' has expired"
        assert error.error_code == "MESSAGE_EXPIRED"
        assert error.details["message_id"] == "msg_001"
        assert error.details["expired_at"] == "2024-01-15T10:00:00Z"
        assert error.details["created_at"] == "2024-01-15T09:30:00Z"

    def test_message_expired_error_with_additional_details(self) -> None:
        """Test MessageExpiredError with additional details."""
        error = MessageExpiredError(
            message_id="msg_002",
            expired_at="2024-01-15T10:00:00Z",
            created_at="2024-01-15T09:00:00Z",
            details={"ttl_seconds": 3600, "service": "test-service"},
        )

        assert error.details["message_id"] == "msg_002"
        assert error.details["ttl_seconds"] == 3600
        assert error.details["service"] == "test-service"


class TestAcknowledgmentTimeoutError:
    """Test cases for AcknowledgmentTimeoutError."""

    def test_acknowledgment_timeout_error_basic(self) -> None:
        """Test AcknowledgmentTimeoutError with basic information."""
        error = AcknowledgmentTimeoutError(
            message_id="msg_timeout_001",
            service_name="test-service",
            timeout_seconds=30.0,
        )

        expected_msg = (
            "Acknowledgment timeout for message 'msg_timeout_001' to service "
            "'test-service' after 30.0 seconds"
        )
        assert str(error) == expected_msg
        assert error.error_code == "ACKNOWLEDGMENT_TIMEOUT"
        assert error.details["message_id"] == "msg_timeout_001"
        assert error.details["service_name"] == "test-service"
        assert error.details["timeout_seconds"] == 30.0
        assert error.details["retry_count"] == 0

    def test_acknowledgment_timeout_error_with_retry_count(self) -> None:
        """Test AcknowledgmentTimeoutError with retry count."""
        error = AcknowledgmentTimeoutError(
            message_id="msg_timeout_002",
            service_name="another-service",
            timeout_seconds=60.0,
            retry_count=2,
        )

        assert error.details["retry_count"] == 2

    def test_acknowledgment_timeout_error_with_additional_details(self) -> None:
        """Test AcknowledgmentTimeoutError with additional details."""
        error = AcknowledgmentTimeoutError(
            message_id="msg_timeout_003",
            service_name="test-service",
            timeout_seconds=45.0,
            retry_count=1,
            details={"instance_id": "inst_123", "method": "process"},
        )

        assert error.details["retry_count"] == 1
        assert error.details["instance_id"] == "inst_123"
        assert error.details["method"] == "process"


class TestMessageStorageError:
    """Test cases for MessageStorageError."""

    def test_message_storage_error_basic_operation(self) -> None:
        """Test MessageStorageError with just operation."""
        error = MessageStorageError(operation="store")

        assert str(error) == "Message storage operation 'store' failed"
        assert error.error_code == "MESSAGE_STORAGE_ERROR"
        assert error.details["operation"] == "store"
        assert error.details["message_id"] is None
        assert error.details["reason"] is None

    def test_message_storage_error_with_message_id(self) -> None:
        """Test MessageStorageError with message ID."""
        error = MessageStorageError(
            operation="retrieve",
            message_id="msg_storage_001",
        )

        expected_msg = "Message storage operation 'retrieve' failed for message 'msg_storage_001'"
        assert str(error) == expected_msg
        assert error.details["message_id"] == "msg_storage_001"

    def test_message_storage_error_with_reason(self) -> None:
        """Test MessageStorageError with reason."""
        error = MessageStorageError(
            operation="update",
            reason="Database connection lost",
        )

        expected_msg = "Message storage operation 'update' failed: Database connection lost"
        assert str(error) == expected_msg
        assert error.details["reason"] == "Database connection lost"

    def test_message_storage_error_complete(self) -> None:
        """Test MessageStorageError with all fields."""
        error = MessageStorageError(
            operation="delete",
            message_id="msg_storage_002",
            reason="Permission denied",
        )

        expected_msg = (
            "Message storage operation 'delete' failed for message "
            "'msg_storage_002': Permission denied"
        )
        assert str(error) == expected_msg
        assert error.details["operation"] == "delete"
        assert error.details["message_id"] == "msg_storage_002"
        assert error.details["reason"] == "Permission denied"

    def test_message_storage_error_with_additional_details(self) -> None:
        """Test MessageStorageError with additional details."""
        error = MessageStorageError(
            operation="store",
            message_id="msg_storage_003",
            reason="Disk full",
            details={"storage_backend": "redis", "retry_attempts": 3},
        )

        assert error.details["storage_backend"] == "redis"
        assert error.details["retry_attempts"] == 3
