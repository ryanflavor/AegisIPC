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


class ResourceConflictError(ConflictError):
    """Raised when attempting to register an already owned resource."""

    def __init__(self, resource_id: str, current_owner: str, **kwargs: Any) -> None:
        """
        Initialize resource conflict error.

        Args:
            resource_id: ID of the conflicting resource
            current_owner: Current owner instance ID
            **kwargs: Additional error details
        """
        message = f"Resource '{resource_id}' is already owned by instance '{current_owner}'"
        super().__init__(
            message,
            conflicting_resource=resource_id,
            details={"resource_id": resource_id, "current_owner": current_owner},
        )


class ResourceNotFoundError(NotFoundError):
    """Raised when a requested resource is not found."""

    def __init__(self, resource_id: str, **kwargs: Any) -> None:
        """
        Initialize resource not found error.

        Args:
            resource_id: ID of the missing resource
            **kwargs: Additional error details
        """
        super().__init__("Resource", resource_id, **kwargs)


class ResourceOwnershipError(DomainError):
    """Raised when resource ownership validation fails."""

    def __init__(
        self, resource_id: str, instance_id: str, actual_owner: str, **kwargs: Any
    ) -> None:
        """
        Initialize resource ownership error.

        Args:
            resource_id: ID of the resource
            instance_id: Instance attempting the operation
            actual_owner: Actual owner of the resource
            **kwargs: Additional error details
        """
        message = (
            f"Instance '{instance_id}' does not own resource '{resource_id}' "
            f"(owned by '{actual_owner}')"
        )
        details = {
            "resource_id": resource_id,
            "instance_id": instance_id,
            "actual_owner": actual_owner,
            **kwargs.pop("details", {}),
        }
        super().__init__(message, error_code="RESOURCE_OWNERSHIP_ERROR", details=details)


class ResourceReleaseError(DomainError):
    """Raised when resource release fails."""

    def __init__(self, message: str, resource_id: str | None = None, **kwargs: Any) -> None:
        """
        Initialize resource release error.

        Args:
            message: Error message
            resource_id: ID of the resource that failed to release
            **kwargs: Additional error details
        """
        details = kwargs.pop("details", {})
        if resource_id:
            details["resource_id"] = resource_id
        super().__init__(message, error_code="RESOURCE_RELEASE_ERROR", details=details)


class ResourceLimitExceededError(DomainError):
    """Raised when an instance exceeds its resource limit."""

    def __init__(self, instance_id: str, current_count: int, limit: int, **kwargs: Any) -> None:
        """
        Initialize resource limit exceeded error.

        Args:
            instance_id: Instance that exceeded the limit
            current_count: Current number of resources
            limit: Maximum allowed resources
            **kwargs: Additional error details
        """
        message = (
            f"Instance '{instance_id}' cannot register more resources "
            f"(current: {current_count}, limit: {limit})"
        )
        details = {
            "instance_id": instance_id,
            "current_count": current_count,
            "limit": limit,
            **kwargs.pop("details", {}),
        }
        super().__init__(message, error_code="RESOURCE_LIMIT_EXCEEDED", details=details)


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


# Resource-related exceptions
class ResourceError(DomainError):
    """Base class for resource-related errors."""

    pass


# Message-related exceptions for exactly-once delivery
class DuplicateMessageError(DomainError):
    """Raised when a duplicate message is detected.

    Used for idempotent processing to indicate that a message with the
    same ID has already been processed.
    """

    def __init__(self, message_id: str, cached_response: Any | None = None, **kwargs: Any) -> None:
        """
        Initialize duplicate message error.

        Args:
            message_id: ID of the duplicate message
            cached_response: Cached response from original processing
            **kwargs: Additional error details
        """
        message = f"Message '{message_id}' has already been processed"
        details = {
            "message_id": message_id,
            "has_cached_response": cached_response is not None,
            **kwargs.pop("details", {}),
        }
        super().__init__(message, error_code="DUPLICATE_MESSAGE", details=details)
        self.message_id = message_id
        self.cached_response = cached_response


class MessageExpiredError(DomainError):
    """Raised when a message has exceeded its TTL.

    Indicates that a message has passed its acknowledgment deadline and
    is no longer valid for processing.
    """

    def __init__(self, message_id: str, expired_at: str, created_at: str, **kwargs: Any) -> None:
        """
        Initialize message expired error.

        Args:
            message_id: ID of the expired message
            expired_at: Expiration timestamp
            created_at: Creation timestamp
            **kwargs: Additional error details
        """
        message = f"Message '{message_id}' has expired"
        details = {
            "message_id": message_id,
            "expired_at": expired_at,
            "created_at": created_at,
            **kwargs.pop("details", {}),
        }
        super().__init__(message, error_code="MESSAGE_EXPIRED", details=details)


class AcknowledgmentTimeoutError(ApplicationError):
    """Raised when message acknowledgment times out.

    Triggers message retry according to the retry policy.
    """

    def __init__(
        self,
        message_id: str,
        service_name: str,
        timeout_seconds: float,
        retry_count: int = 0,
        **kwargs: Any,
    ) -> None:
        """
        Initialize acknowledgment timeout error.

        Args:
            message_id: ID of the message that timed out
            service_name: Target service name
            timeout_seconds: Timeout duration in seconds
            retry_count: Current retry attempt number
            **kwargs: Additional error details
        """
        message = (
            f"Acknowledgment timeout for message '{message_id}' to service '{service_name}' "
            f"after {timeout_seconds} seconds"
        )
        details = {
            "message_id": message_id,
            "service_name": service_name,
            "timeout_seconds": timeout_seconds,
            "retry_count": retry_count,
            **kwargs.pop("details", {}),
        }
        super().__init__(message, error_code="ACKNOWLEDGMENT_TIMEOUT", details=details)


class MessageStorageError(InfrastructureError):
    """Raised when message persistence fails.

    May cause degradation to at-most-once delivery if messages cannot be stored.
    """

    def __init__(
        self,
        operation: str,
        message_id: str | None = None,
        reason: str | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Initialize message storage error.

        Args:
            operation: Storage operation that failed (store, retrieve, update, delete)
            message_id: ID of the affected message, if applicable
            reason: Failure reason
            **kwargs: Additional error details
        """
        message = f"Message storage operation '{operation}' failed"
        if message_id:
            message += f" for message '{message_id}'"
        if reason:
            message += f": {reason}"
        details = {
            "operation": operation,
            "message_id": message_id,
            "reason": reason,
            **kwargs.pop("details", {}),
        }
        super().__init__(message, error_code="MESSAGE_STORAGE_ERROR", details=details)
