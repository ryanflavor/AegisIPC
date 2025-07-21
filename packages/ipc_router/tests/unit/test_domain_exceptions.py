"""Unit tests for domain exceptions."""

from __future__ import annotations

from ipc_router.domain.exceptions import (
    AegisIPCError,
    ApplicationError,
    ConfigurationError,
    ConflictError,
    ConnectionError,
    DomainError,
    DuplicateServiceInstanceError,
    InfrastructureError,
    NotFoundError,
    ServiceRegistrationError,
    ServiceUnavailableError,
    TimeoutError,
    ValidationError,
)


class TestAegisIPCError:
    """Tests for base AegisIPCError exception."""

    def test_basic_exception(self) -> None:
        """Test creating a basic exception."""
        error = AegisIPCError("Test error message")

        assert str(error) == "Test error message"
        assert error.message == "Test error message"
        assert error.error_code == "AegisIPCError"
        assert error.details == {}

    def test_exception_with_error_code(self) -> None:
        """Test exception with custom error code."""
        error = AegisIPCError("Test error", error_code="CUSTOM_ERROR")

        assert error.message == "Test error"
        assert error.error_code == "CUSTOM_ERROR"
        assert error.details == {}

    def test_exception_with_details(self) -> None:
        """Test exception with additional details."""
        details = {"field": "username", "value": "invalid"}
        error = AegisIPCError("Validation failed", details=details)

        assert error.message == "Validation failed"
        assert error.details == details


class TestDomainExceptions:
    """Tests for domain layer exceptions."""

    def test_domain_error(self) -> None:
        """Test DomainError base class."""
        error = DomainError("Domain error")
        assert isinstance(error, AegisIPCError)
        assert str(error) == "Domain error"

    def test_validation_error_basic(self) -> None:
        """Test ValidationError without field."""
        error = ValidationError("Invalid data")

        assert str(error) == "Invalid data"
        assert error.error_code == "VALIDATION_ERROR"
        assert error.details == {}

    def test_validation_error_with_field(self) -> None:
        """Test ValidationError with field name."""
        error = ValidationError("Invalid email format", field="email")

        assert str(error) == "Invalid email format"
        assert error.error_code == "VALIDATION_ERROR"
        assert error.details == {"field": "email"}

    def test_validation_error_with_existing_details(self) -> None:
        """Test ValidationError preserves existing details."""
        error = ValidationError(
            "Invalid data", field="username", details={"constraint": "min_length", "value": 3}
        )

        assert error.details["field"] == "username"
        assert error.details["constraint"] == "min_length"
        assert error.details["value"] == 3

    def test_not_found_error(self) -> None:
        """Test NotFoundError."""
        error = NotFoundError(resource_type="User", resource_id="123")

        assert str(error) == "User with id '123' not found"
        assert error.error_code == "NOT_FOUND"
        assert error.details["resource_type"] == "User"
        assert error.details["resource_id"] == "123"

    def test_not_found_error_with_extra_details(self) -> None:
        """Test NotFoundError with additional details."""
        error = NotFoundError(
            resource_type="Service", resource_id="test-service", details={"namespace": "production"}
        )

        assert error.details["resource_type"] == "Service"
        assert error.details["resource_id"] == "test-service"
        assert error.details["namespace"] == "production"

    def test_conflict_error_basic(self) -> None:
        """Test ConflictError without conflicting resource."""
        error = ConflictError("Resource already exists")

        assert str(error) == "Resource already exists"
        assert error.error_code == "CONFLICT"
        assert error.details == {}

    def test_conflict_error_with_resource(self) -> None:
        """Test ConflictError with conflicting resource."""
        error = ConflictError("Username already taken", conflicting_resource="user:john_doe")

        assert str(error) == "Username already taken"
        assert error.details["conflicting_resource"] == "user:john_doe"

    def test_service_registration_error(self) -> None:
        """Test ServiceRegistrationError."""
        error = ServiceRegistrationError(
            service_name="test-service", instance_id="instance-01", reason="Connection timeout"
        )

        expected_msg = (
            "Failed to register service 'test-service' instance 'instance-01': Connection timeout"
        )
        assert str(error) == expected_msg
        assert error.error_code == "SERVICE_REGISTRATION_ERROR"
        assert error.details["service_name"] == "test-service"
        assert error.details["instance_id"] == "instance-01"
        assert error.details["reason"] == "Connection timeout"

    def test_duplicate_service_instance_error(self) -> None:
        """Test DuplicateServiceInstanceError."""
        error = DuplicateServiceInstanceError(service_name="api-service", instance_id="instance-01")

        expected_msg = (
            "Service instance 'instance-01' is already registered for service 'api-service'"
        )
        assert str(error) == expected_msg
        assert error.error_code == "CONFLICT"
        assert error.details["conflicting_resource"] == "api-service/instance-01"
        assert error.details["service_name"] == "api-service"
        assert error.details["instance_id"] == "instance-01"


class TestApplicationExceptions:
    """Tests for application layer exceptions."""

    def test_application_error(self) -> None:
        """Test ApplicationError base class."""
        error = ApplicationError("Application error")
        assert isinstance(error, AegisIPCError)
        assert str(error) == "Application error"

    def test_service_unavailable_error(self) -> None:
        """Test ServiceUnavailableError."""
        error = ServiceUnavailableError(
            service_name="payment-service", reason="Circuit breaker open"
        )

        expected_msg = "Service 'payment-service' is unavailable: Circuit breaker open"
        assert str(error) == expected_msg
        assert error.error_code == "SERVICE_UNAVAILABLE"
        assert error.details["service_name"] == "payment-service"
        assert error.details["reason"] == "Circuit breaker open"

    def test_timeout_error(self) -> None:
        """Test TimeoutError."""
        error = TimeoutError(operation="fetch_user_data", timeout_seconds=5.0)

        expected_msg = "Operation 'fetch_user_data' timed out after 5.0 seconds"
        assert str(error) == expected_msg
        assert error.error_code == "TIMEOUT"
        assert error.details["operation"] == "fetch_user_data"
        assert error.details["timeout_seconds"] == 5.0


class TestInfrastructureExceptions:
    """Tests for infrastructure layer exceptions."""

    def test_infrastructure_error(self) -> None:
        """Test InfrastructureError base class."""
        error = InfrastructureError("Infrastructure error")
        assert isinstance(error, AegisIPCError)
        assert str(error) == "Infrastructure error"

    def test_connection_error(self) -> None:
        """Test ConnectionError."""
        error = ConnectionError(
            service="NATS", endpoint="localhost:4222", reason="Connection refused"
        )

        expected_msg = "Failed to connect to NATS at localhost:4222: Connection refused"
        assert str(error) == expected_msg
        assert error.error_code == "CONNECTION_ERROR"
        assert error.details["service"] == "NATS"
        assert error.details["endpoint"] == "localhost:4222"
        assert error.details["reason"] == "Connection refused"

    def test_configuration_error(self) -> None:
        """Test ConfigurationError."""
        error = ConfigurationError(config_key="nats_url", reason="Invalid URL format")

        expected_msg = "Configuration error for 'nats_url': Invalid URL format"
        assert str(error) == expected_msg
        assert error.error_code == "CONFIGURATION_ERROR"
        assert error.details["config_key"] == "nats_url"
        assert error.details["reason"] == "Invalid URL format"
