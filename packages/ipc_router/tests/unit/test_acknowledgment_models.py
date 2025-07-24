"""Unit tests for acknowledgment-related Pydantic models."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from ipc_router.application.models import (
    AcknowledgmentRequest,
    AcknowledgmentResponse,
    AcknowledgmentRetryConfig,
    MessageDeliveryConfig,
    MessageStatusRequest,
    MessageStatusResponse,
)
from pydantic import ValidationError


class TestAcknowledgmentRequest:
    """Test AcknowledgmentRequest model validation and behavior."""

    def test_create_success_acknowledgment(self) -> None:
        """Test creating a successful acknowledgment request."""
        message_id = uuid4()
        request = AcknowledgmentRequest(
            message_id=message_id,
            service_name="user-service",
            instance_id="user-service-1",
            status="success",
            processing_time_ms=45.5,
            trace_id="trace-123",
        )

        assert request.message_id == message_id
        assert request.service_name == "user-service"
        assert request.instance_id == "user-service-1"
        assert request.status == "success"
        assert request.error_message is None
        assert request.processing_time_ms == 45.5
        assert request.trace_id == "trace-123"

    def test_create_failure_acknowledgment(self) -> None:
        """Test creating a failure acknowledgment request."""
        message_id = uuid4()
        request = AcknowledgmentRequest(
            message_id=message_id,
            service_name="user-service",
            instance_id="user-service-1",
            status="failure",
            error_message="Database connection failed",
            processing_time_ms=120.5,
            trace_id="trace-123",
        )

        assert request.status == "failure"
        assert request.error_message == "Database connection failed"

    def test_failure_without_error_message_raises_error(self) -> None:
        """Test that failure status requires error message."""
        with pytest.raises(ValidationError) as exc_info:
            AcknowledgmentRequest(
                message_id=uuid4(),
                service_name="user-service",
                instance_id="user-service-1",
                status="failure",
                processing_time_ms=45.5,
                trace_id="trace-123",
            )

        errors = exc_info.value.errors()
        assert any(
            "Error message must be provided when status is failure" in str(error["msg"])
            for error in errors
        )

    def test_success_with_error_message_raises_error(self) -> None:
        """Test that success status cannot have error message."""
        with pytest.raises(ValidationError) as exc_info:
            AcknowledgmentRequest(
                message_id=uuid4(),
                service_name="user-service",
                instance_id="user-service-1",
                status="success",
                error_message="Should not be here",
                processing_time_ms=45.5,
                trace_id="trace-123",
            )

        errors = exc_info.value.errors()
        assert any(
            "Error message should not be provided when status is success" in str(error["msg"])
            for error in errors
        )

    def test_empty_service_name_raises_error(self) -> None:
        """Test that empty service name is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            AcknowledgmentRequest(
                message_id=uuid4(),
                service_name="",
                instance_id="instance-1",
                status="success",
                processing_time_ms=45.5,
                trace_id="trace-123",
            )

        errors = exc_info.value.errors()
        assert any("Value cannot be empty" in str(error["msg"]) for error in errors)

    def test_negative_processing_time_raises_error(self) -> None:
        """Test that negative processing time is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            AcknowledgmentRequest(
                message_id=uuid4(),
                service_name="service",
                instance_id="instance-1",
                status="success",
                processing_time_ms=-1.0,
                trace_id="trace-123",
            )

        errors = exc_info.value.errors()
        assert any("greater than 0" in str(error["msg"]) for error in errors)


class TestAcknowledgmentResponse:
    """Test AcknowledgmentResponse model."""

    def test_create_response(self) -> None:
        """Test creating acknowledgment response."""
        response = AcknowledgmentResponse(
            success=True,
            message="Acknowledgment received and processed",
            trace_id="trace-123",
        )

        assert response.success is True
        assert response.message == "Acknowledgment received and processed"
        assert response.trace_id == "trace-123"
        assert isinstance(response.timestamp, datetime)

    def test_response_with_custom_timestamp(self) -> None:
        """Test response with custom timestamp."""
        custom_time = datetime(2025, 7, 21, 10, 0, 0, tzinfo=UTC)
        response = AcknowledgmentResponse(
            success=False,
            message="Failed to process acknowledgment",
            trace_id="trace-123",
            timestamp=custom_time,
        )

        assert response.timestamp == custom_time


class TestMessageStatusRequest:
    """Test MessageStatusRequest model."""

    def test_create_status_request(self) -> None:
        """Test creating message status request."""
        message_id = uuid4()
        request = MessageStatusRequest(message_id=message_id, trace_id="trace-123")

        assert request.message_id == message_id
        assert request.trace_id == "trace-123"


class TestMessageStatusResponse:
    """Test MessageStatusResponse model."""

    def test_create_pending_status(self) -> None:
        """Test creating pending message status."""
        message_id = uuid4()
        now = datetime.now(UTC)
        response = MessageStatusResponse(
            message_id=message_id,
            state="pending",
            retry_count=0,
            created_at=now,
            updated_at=now,
            service_name="user-service",
            method="get_user",
            ack_deadline=datetime.now(UTC),
            trace_id="trace-123",
        )

        assert response.message_id == message_id
        assert response.state == "pending"
        assert response.retry_count == 0
        assert response.last_error is None
        assert response.instance_id is None

    def test_create_failed_status(self) -> None:
        """Test creating failed message status."""
        message_id = uuid4()
        now = datetime.now(UTC)
        response = MessageStatusResponse(
            message_id=message_id,
            state="failed",
            retry_count=3,
            created_at=now,
            updated_at=now,
            last_error="Maximum retry attempts exceeded",
            service_name="user-service",
            method="get_user",
            trace_id="trace-123",
        )

        assert response.state == "failed"
        assert response.retry_count == 3
        assert response.last_error == "Maximum retry attempts exceeded"

    def test_negative_retry_count_raises_error(self) -> None:
        """Test that negative retry count is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            MessageStatusResponse(
                message_id=uuid4(),
                state="pending",
                retry_count=-1,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                service_name="service",
                method="method",
                trace_id="trace-123",
            )

        errors = exc_info.value.errors()
        assert any("greater than or equal to 0" in str(error["msg"]) for error in errors)


class TestAcknowledgmentRetryConfig:
    """Test AcknowledgmentRetryConfig model."""

    def test_default_config(self) -> None:
        """Test default retry configuration."""
        config = AcknowledgmentRetryConfig()

        assert config.max_attempts == 3
        assert config.ack_timeout == 30.0
        assert config.retry_delay == 5.0
        assert config.exponential_backoff is True
        assert config.max_retry_delay == 60.0
        assert config.dead_letter_after_retries is True

    def test_custom_config(self) -> None:
        """Test custom retry configuration."""
        config = AcknowledgmentRetryConfig(
            max_attempts=5,
            ack_timeout=60.0,
            retry_delay=10.0,
            exponential_backoff=False,
            max_retry_delay=120.0,
            dead_letter_after_retries=False,
        )

        assert config.max_attempts == 5
        assert config.ack_timeout == 60.0
        assert config.retry_delay == 10.0
        assert config.exponential_backoff is False
        assert config.max_retry_delay == 120.0
        assert config.dead_letter_after_retries is False

    def test_max_retry_delay_validation(self) -> None:
        """Test that max_retry_delay must be >= retry_delay."""
        with pytest.raises(ValidationError) as exc_info:
            AcknowledgmentRetryConfig(retry_delay=10.0, max_retry_delay=5.0)

        errors = exc_info.value.errors()
        assert any(
            "max_retry_delay must be >= retry_delay" in str(error["msg"]) for error in errors
        )

    def test_invalid_max_attempts(self) -> None:
        """Test max_attempts validation."""
        with pytest.raises(ValidationError):
            AcknowledgmentRetryConfig(max_attempts=0)

        with pytest.raises(ValidationError):
            AcknowledgmentRetryConfig(max_attempts=11)

    def test_invalid_timeouts(self) -> None:
        """Test timeout validations."""
        with pytest.raises(ValidationError):
            AcknowledgmentRetryConfig(ack_timeout=0)

        with pytest.raises(ValidationError):
            AcknowledgmentRetryConfig(ack_timeout=301)


class TestMessageDeliveryConfig:
    """Test MessageDeliveryConfig model."""

    def test_default_config(self) -> None:
        """Test default delivery configuration."""
        config = MessageDeliveryConfig()

        assert isinstance(config.retry_config, AcknowledgmentRetryConfig)
        assert config.require_explicit_ack is True
        assert config.auto_ack_on_success is False
        assert config.message_ttl == 3600.0
        assert config.enable_deduplication is True
        assert config.dedup_window == 300.0

    def test_custom_config(self) -> None:
        """Test custom delivery configuration."""
        retry_config = AcknowledgmentRetryConfig(max_attempts=5, ack_timeout=45.0)
        config = MessageDeliveryConfig(
            retry_config=retry_config,
            require_explicit_ack=False,
            auto_ack_on_success=True,
            message_ttl=7200.0,
            enable_deduplication=False,
            dedup_window=600.0,
        )

        assert config.retry_config.max_attempts == 5
        assert config.retry_config.ack_timeout == 45.0
        assert config.require_explicit_ack is False
        assert config.auto_ack_on_success is True
        assert config.message_ttl == 7200.0
        assert config.enable_deduplication is False
        assert config.dedup_window == 600.0

    def test_invalid_ttl(self) -> None:
        """Test that negative TTL is rejected."""
        with pytest.raises(ValidationError):
            MessageDeliveryConfig(message_ttl=0)

    def test_invalid_dedup_window(self) -> None:
        """Test that negative dedup window is rejected."""
        with pytest.raises(ValidationError):
            MessageDeliveryConfig(dedup_window=0)


class TestModelSerialization:
    """Test model serialization and deserialization."""

    def test_acknowledgment_request_serialization(self) -> None:
        """Test AcknowledgmentRequest JSON serialization."""
        message_id = uuid4()
        request = AcknowledgmentRequest(
            message_id=message_id,
            service_name="test-service",
            instance_id="instance-1",
            status="success",
            processing_time_ms=50.0,
            trace_id="trace-123",
        )

        json_data = request.model_dump_json()
        parsed = AcknowledgmentRequest.model_validate_json(json_data)

        assert parsed.message_id == message_id
        assert parsed.service_name == "test-service"
        assert parsed.status == "success"

    def test_message_delivery_config_serialization(self) -> None:
        """Test MessageDeliveryConfig JSON serialization."""
        config = MessageDeliveryConfig(
            retry_config=AcknowledgmentRetryConfig(max_attempts=5),
            message_ttl=1800.0,
        )

        json_data = config.model_dump_json()
        parsed = MessageDeliveryConfig.model_validate_json(json_data)

        assert parsed.retry_config.max_attempts == 5
        assert parsed.message_ttl == 1800.0
