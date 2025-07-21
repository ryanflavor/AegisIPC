"""Domain-specific exceptions for AegisIPC Router.

This module defines the exception hierarchy for the IPC Router service,
following clean architecture principles where domain exceptions are
independent of infrastructure concerns.
"""

from typing import Any


class AegisIPCError(Exception):
    """Base exception for all AegisIPC errors."""

    def __init__(
        self,
        message: str,
        error_code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize the exception.

        Args:
            message: Human-readable error message
            error_code: Machine-readable error code for programmatic handling
            details: Additional error context
        """
        super().__init__(message)
        self.message = message
        self.error_code = error_code or self.__class__.__name__
        self.details = details or {}


class DomainError(AegisIPCError):
    """Base class for domain-layer errors."""

    pass


class ValidationError(DomainError):
    """Raised when domain validation fails."""

    def __init__(self, message: str, field: str | None = None, **kwargs: Any) -> None:
        """
        Initialize validation error.

        Args:
            message: Validation error message
            field: Field that failed validation
            **kwargs: Additional error details
        """
        details = kwargs.pop("details", {})
        if field:
            details["field"] = field
        super().__init__(message, error_code="VALIDATION_ERROR", details=details)


class NotFoundError(DomainError):
    """Raised when a requested resource is not found."""

    def __init__(self, resource_type: str, resource_id: str, **kwargs: Any) -> None:
        """
        Initialize not found error.

        Args:
            resource_type: Type of resource (e.g., "Service", "Route")
            resource_id: Identifier of the missing resource
            **kwargs: Additional error details
        """
        message = f"{resource_type} with id '{resource_id}' not found"
        details = {
            "resource_type": resource_type,
            "resource_id": resource_id,
            **kwargs.pop("details", {}),
        }
        super().__init__(message, error_code="NOT_FOUND", details=details)


class ConflictError(DomainError):
    """Raised when an operation conflicts with existing state."""

    def __init__(
        self, message: str, conflicting_resource: str | None = None, **kwargs: Any
    ) -> None:
        """
        Initialize conflict error.

        Args:
            message: Conflict description
            conflicting_resource: Identifier of conflicting resource
            **kwargs: Additional error details
        """
        details = kwargs.pop("details", {})
        if conflicting_resource:
            details["conflicting_resource"] = conflicting_resource
        super().__init__(message, error_code="CONFLICT", details=details)


class ServiceRegistrationError(DomainError):
    """Raised when service registration fails."""

    def __init__(self, service_name: str, instance_id: str, reason: str, **kwargs: Any) -> None:
        """
        Initialize service registration error.

        Args:
            service_name: Name of the service attempting to register
            instance_id: Instance ID attempting to register
            reason: Reason for registration failure
            **kwargs: Additional error details
        """
        message = f"Failed to register service '{service_name}' instance '{instance_id}': {reason}"
        details = {
            "service_name": service_name,
            "instance_id": instance_id,
            "reason": reason,
            **kwargs.pop("details", {}),
        }
        super().__init__(message, error_code="SERVICE_REGISTRATION_ERROR", details=details)


class DuplicateServiceInstanceError(ConflictError):
    """Raised when attempting to register a duplicate service instance."""

    def __init__(self, service_name: str, instance_id: str, **kwargs: Any) -> None:
        """
        Initialize duplicate service instance error.

        Args:
            service_name: Name of the service
            instance_id: Duplicate instance ID
            **kwargs: Additional error details
        """
        message = (
            f"Service instance '{instance_id}' is already registered for service '{service_name}'"
        )
        super().__init__(
            message,
            conflicting_resource=f"{service_name}/{instance_id}",
            details={"service_name": service_name, "instance_id": instance_id},
        )


class ApplicationError(AegisIPCError):
    """Base class for application-layer errors."""

    pass


class ServiceUnavailableError(ApplicationError):
    """Raised when a required service is unavailable."""

    def __init__(self, service_name: str, reason: str | None = None, **kwargs: Any) -> None:
        """
        Initialize service unavailable error.

        Args:
            service_name: Name of the unavailable service
            reason: Reason for unavailability
            **kwargs: Additional error details
        """
        message = f"Service '{service_name}' is unavailable"
        if reason:
            message += f": {reason}"
        details = {
            "service_name": service_name,
            "reason": reason,
            **kwargs.pop("details", {}),
        }
        super().__init__(message, error_code="SERVICE_UNAVAILABLE", details=details)


class TimeoutError(ApplicationError):
    """Raised when an operation times out."""

    def __init__(self, operation: str, timeout_seconds: float, **kwargs: Any) -> None:
        """
        Initialize timeout error.

        Args:
            operation: Operation that timed out
            timeout_seconds: Timeout duration in seconds
            **kwargs: Additional error details
        """
        message = f"Operation '{operation}' timed out after {timeout_seconds} seconds"
        details = {
            "operation": operation,
            "timeout_seconds": timeout_seconds,
            **kwargs.pop("details", {}),
        }
        super().__init__(message, error_code="TIMEOUT", details=details)


class InfrastructureError(AegisIPCError):
    """Base class for infrastructure-layer errors."""

    pass


class ConnectionError(InfrastructureError):
    """Raised when connection to external service fails."""

    def __init__(
        self, service: str, endpoint: str, reason: str | None = None, **kwargs: Any
    ) -> None:
        """
        Initialize connection error.

        Args:
            service: Service name (e.g., "NATS", "Database")
            endpoint: Connection endpoint
            reason: Failure reason
            **kwargs: Additional error details
        """
        message = f"Failed to connect to {service} at {endpoint}"
        if reason:
            message += f": {reason}"
        details = {
            "service": service,
            "endpoint": endpoint,
            "reason": reason,
            **kwargs.pop("details", {}),
        }
        super().__init__(message, error_code="CONNECTION_ERROR", details=details)


class ConfigurationError(InfrastructureError):
    """Raised when configuration is invalid or missing."""

    def __init__(self, config_key: str, reason: str, **kwargs: Any) -> None:
        """
        Initialize configuration error.

        Args:
            config_key: Configuration key that has issues
            reason: Reason for configuration error
            **kwargs: Additional error details
        """
        message = f"Configuration error for '{config_key}': {reason}"
        details = {
            "config_key": config_key,
            "reason": reason,
            **kwargs.pop("details", {}),
        }
        super().__init__(message, error_code="CONFIGURATION_ERROR", details=details)
