"""Tests for domain exceptions."""

from ipc_router.domain.exceptions import (
    AegisIPCError,
    ApplicationError,
    ConfigurationError,
    ConflictError,
    ConnectionError,
    DomainError,
    InfrastructureError,
    NotFoundError,
    ServiceUnavailableError,
    TimeoutError,
    ValidationError,
)


class TestAegisIPCError:
    """Test base exception class."""

    def test_basic_initialization(self) -> None:
        """Test basic exception initialization."""
        error = AegisIPCError("Test error")
        assert str(error) == "Test error"
        assert error.message == "Test error"
        assert error.error_code == "AegisIPCError"
        assert error.details == {}

    def test_with_error_code_and_details(self) -> None:
        """Test exception with custom error code and details."""
        details = {"key": "value", "count": 42}
        error = AegisIPCError("Test error", error_code="CUSTOM_ERROR", details=details)
        assert error.message == "Test error"
        assert error.error_code == "CUSTOM_ERROR"
        assert error.details == details


class TestDomainErrors:
    """Test domain layer exceptions."""

    def test_validation_error_basic(self) -> None:
        """Test basic validation error."""
        error = ValidationError("Invalid value")
        assert error.message == "Invalid value"
        assert error.error_code == "VALIDATION_ERROR"
        assert error.details == {}

    def test_validation_error_with_field(self) -> None:
        """Test validation error with field."""
        error = ValidationError("Invalid email format", field="email")
        assert error.message == "Invalid email format"
        assert error.error_code == "VALIDATION_ERROR"
        assert error.details == {"field": "email"}

    def test_not_found_error(self) -> None:
        """Test not found error."""
        error = NotFoundError("User", "user123")
        assert error.message == "User with id 'user123' not found"
        assert error.error_code == "NOT_FOUND"
        assert error.details == {"resource_type": "User", "resource_id": "user123"}

    def test_not_found_error_with_extra_details(self) -> None:
        """Test not found error with additional details."""
        error = NotFoundError("Service", "auth-service", details={"namespace": "production"})
        assert error.message == "Service with id 'auth-service' not found"
        assert error.details == {
            "resource_type": "Service",
            "resource_id": "auth-service",
            "namespace": "production",
        }

    def test_conflict_error_basic(self) -> None:
        """Test basic conflict error."""
        error = ConflictError("Resource already exists")
        assert error.message == "Resource already exists"
        assert error.error_code == "CONFLICT"
        assert error.details == {}

    def test_conflict_error_with_resource(self) -> None:
        """Test conflict error with conflicting resource."""
        error = ConflictError("User already exists", conflicting_resource="user123")
        assert error.message == "User already exists"
        assert error.details == {"conflicting_resource": "user123"}


class TestApplicationErrors:
    """Test application layer exceptions."""

    def test_service_unavailable_basic(self) -> None:
        """Test basic service unavailable error."""
        error = ServiceUnavailableError("payment-service")
        assert error.message == "Service 'payment-service' is unavailable"
        assert error.error_code == "SERVICE_UNAVAILABLE"
        assert error.details == {"service_name": "payment-service", "reason": None}

    def test_service_unavailable_with_reason(self) -> None:
        """Test service unavailable error with reason."""
        error = ServiceUnavailableError("auth-service", reason="Circuit breaker open")
        assert error.message == "Service 'auth-service' is unavailable: Circuit breaker open"
        assert error.details == {
            "service_name": "auth-service",
            "reason": "Circuit breaker open",
        }

    def test_timeout_error(self) -> None:
        """Test timeout error."""
        error = TimeoutError("fetch_user_data", 30.0)
        assert error.message == "Operation 'fetch_user_data' timed out after 30.0 seconds"
        assert error.error_code == "TIMEOUT"
        assert error.details == {"operation": "fetch_user_data", "timeout_seconds": 30.0}


class TestInfrastructureErrors:
    """Test infrastructure layer exceptions."""

    def test_connection_error_basic(self) -> None:
        """Test basic connection error."""
        error = ConnectionError("NATS", "nats://localhost:4222")
        assert error.message == "Failed to connect to NATS at nats://localhost:4222"
        assert error.error_code == "CONNECTION_ERROR"
        assert error.details == {
            "service": "NATS",
            "endpoint": "nats://localhost:4222",
            "reason": None,
        }

    def test_connection_error_with_reason(self) -> None:
        """Test connection error with reason."""
        error = ConnectionError("Database", "postgres://db:5432", reason="Connection refused")
        assert (
            error.message
            == "Failed to connect to Database at postgres://db:5432: Connection refused"
        )
        assert error.details["reason"] == "Connection refused"

    def test_configuration_error(self) -> None:
        """Test configuration error."""
        error = ConfigurationError("DATABASE_URL", "Missing required environment variable")
        assert (
            error.message
            == "Configuration error for 'DATABASE_URL': Missing required environment variable"
        )
        assert error.error_code == "CONFIGURATION_ERROR"
        assert error.details == {
            "config_key": "DATABASE_URL",
            "reason": "Missing required environment variable",
        }


class TestExceptionHierarchy:
    """Test exception inheritance hierarchy."""

    def test_domain_error_inheritance(self) -> None:
        """Test that domain errors inherit from AegisIPCError."""
        error = ValidationError("test")
        assert isinstance(error, DomainError)
        assert isinstance(error, AegisIPCError)
        assert isinstance(error, Exception)

    def test_application_error_inheritance(self) -> None:
        """Test that application errors inherit from AegisIPCError."""
        error = TimeoutError("test", 1.0)
        assert isinstance(error, ApplicationError)
        assert isinstance(error, AegisIPCError)
        assert isinstance(error, Exception)

    def test_infrastructure_error_inheritance(self) -> None:
        """Test that infrastructure errors inherit from AegisIPCError."""
        error = ConnectionError("test", "endpoint")
        assert isinstance(error, InfrastructureError)
        assert isinstance(error, AegisIPCError)
        assert isinstance(error, Exception)
