"""Service registration RPC handler."""

from __future__ import annotations

from typing import Any

from ipc_client_sdk.models import ServiceRegistrationRequest

from ipc_router.application.error_handling import RetryConfig
from ipc_router.application.services import ServiceRegistry
from ipc_router.domain.exceptions import AegisIPCError, ConflictError, DuplicateServiceInstanceError
from ipc_router.infrastructure.logging import get_logger
from ipc_router.infrastructure.messaging.nats_client import NATSClient

logger = get_logger(__name__)


class RegistrationHandler:
    """Handles service registration RPC requests via NATS.

    This handler subscribes to registration requests and processes them
    using the ServiceRegistry application service.
    """

    REGISTRATION_SUBJECT = "ipc.service.register"

    def __init__(self, nats_client: NATSClient, service_registry: ServiceRegistry) -> None:
        """Initialize the registration handler.

        Args:
            nats_client: NATS client for messaging
            service_registry: Service registry for managing registrations
        """
        self._nats_client = nats_client
        self._service_registry = service_registry
        self._retry_config = RetryConfig(
            max_attempts=3,
            initial_delay=0.5,
            max_delay=2.0,
        )

    async def start(self) -> None:
        """Start listening for registration requests."""
        await self._nats_client.subscribe(
            subject=self.REGISTRATION_SUBJECT,
            callback=self._handle_registration,
            queue="service-registry",  # Use queue group for load balancing
        )
        logger.info(
            "Registration handler started",
            extra={"subject": self.REGISTRATION_SUBJECT},
        )

    async def stop(self) -> None:
        """Stop listening for registration requests."""
        await self._nats_client.unsubscribe(self.REGISTRATION_SUBJECT)
        logger.info("Registration handler stopped")

    async def _handle_registration(self, data: Any, reply_subject: str | None) -> None:
        """Handle incoming registration requests.

        Args:
            data: Raw request data
            reply_subject: Subject to send response to
        """
        if not reply_subject:
            logger.error("Registration request missing reply subject")
            return

        try:
            # Parse request
            request = ServiceRegistrationRequest(**data)

            # Default to STANDBY role if not specified for backward compatibility
            if not hasattr(request, "role") or request.role is None:
                request.role = "standby"

            logger.info(
                "Processing registration request",
                extra={
                    "service_name": request.service_name,
                    "instance_id": request.instance_id,
                    "role": request.role,
                },
            )

            # Process registration without retry decorator for now
            # TODO: Implement retry logic properly
            response = await self._service_registry.register_service(request)

            # Send success response
            await self._nats_client.publish(
                subject=reply_subject,
                data={
                    "success": response.success,
                    "service_name": response.service_name,
                    "instance_id": response.instance_id,
                    "role": response.role,
                    "registered_at": response.registered_at.isoformat(),
                    "message": response.message,
                },
            )

        except ConflictError as e:
            # Handle role conflicts
            logger.warning(
                "Role conflict during registration",
                extra={
                    "error": str(e),
                    "details": e.details,
                },
            )

            # Send error response
            await self._send_error_response(
                reply_subject=reply_subject,
                error_code="ROLE_CONFLICT",
                message=str(e),
                details=e.details,
            )

        except DuplicateServiceInstanceError as e:
            # Handle duplicate registration
            logger.warning(
                "Duplicate registration attempt",
                extra={
                    "error": str(e),
                    "details": e.details,
                },
            )

            # Send error response
            await self._send_error_response(
                reply_subject=reply_subject,
                error_code="DUPLICATE_INSTANCE",
                message=str(e),
                details=e.details,
            )

        except AegisIPCError as e:
            # Handle domain errors
            logger.error(
                "Registration failed",
                exc_info=e,
                extra={"error_code": e.error_code},
            )

            await self._send_error_response(
                reply_subject=reply_subject,
                error_code=e.error_code,
                message=str(e),
                details=e.details,
            )

        except Exception as e:
            # Handle unexpected errors
            logger.error(
                "Unexpected error during registration",
                exc_info=e,
            )

            await self._send_error_response(
                reply_subject=reply_subject,
                error_code="INTERNAL_ERROR",
                message="An unexpected error occurred during registration",
                details={"error": str(e)},
            )

    async def _send_error_response(
        self,
        reply_subject: str,
        error_code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Send an error response.

        Args:
            reply_subject: Subject to send response to
            error_code: Error code
            message: Error message
            details: Additional error details
        """
        try:
            await self._nats_client.publish(
                subject=reply_subject,
                data={
                    "success": False,
                    "error": {
                        "code": error_code,
                        "message": message,
                        "details": details or {},
                    },
                },
            )
        except Exception as e:
            logger.error(
                "Failed to send error response",
                exc_info=e,
                extra={
                    "reply_subject": reply_subject,
                    "error_code": error_code,
                },
            )
