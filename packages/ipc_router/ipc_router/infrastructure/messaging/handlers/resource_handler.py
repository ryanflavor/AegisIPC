"""Resource management RPC handler."""

from __future__ import annotations

from typing import Any

from ipc_router.application.models import (
    ResourceRegistrationRequest,
    ResourceRegistrationResponse,
    ResourceReleaseRequest,
    ResourceReleaseResponse,
)
from ipc_router.application.services import ResourceService
from ipc_router.domain.exceptions import (
    AegisIPCError,
    ResourceConflictError,
    ResourceNotFoundError,
    ValidationError,
)
from ipc_router.infrastructure.logging import get_logger
from ipc_router.infrastructure.messaging.nats_client import NATSClient

logger = get_logger(__name__)


class ResourceHandler:
    """Handles resource management RPC requests via NATS.

    This handler subscribes to resource registration and release requests
    and processes them using the ResourceService application service.
    """

    REGISTRATION_SUBJECT = "ipc.resource.register"
    RELEASE_SUBJECT = "ipc.resource.release"

    def __init__(self, nats_client: NATSClient, resource_service: ResourceService) -> None:
        """Initialize the resource handler.

        Args:
            nats_client: NATS client for messaging
            resource_service: Resource service for managing resources
        """
        self._nats_client = nats_client
        self._resource_service = resource_service

    async def start(self) -> None:
        """Start listening for resource management requests."""
        # Subscribe to registration requests
        await self._nats_client.subscribe(
            subject=self.REGISTRATION_SUBJECT,
            callback=self._handle_registration,
            queue="resource-registry",  # Use queue group for load balancing
        )
        logger.info(
            "Resource registration handler started",
            extra={"subject": self.REGISTRATION_SUBJECT},
        )

        # Subscribe to release requests
        await self._nats_client.subscribe(
            subject=self.RELEASE_SUBJECT,
            callback=self._handle_release,
            queue="resource-registry",  # Use same queue group
        )
        logger.info(
            "Resource release handler started",
            extra={"subject": self.RELEASE_SUBJECT},
        )

    async def stop(self) -> None:
        """Stop listening for resource management requests."""
        await self._nats_client.unsubscribe(self.REGISTRATION_SUBJECT)
        await self._nats_client.unsubscribe(self.RELEASE_SUBJECT)
        logger.info("Resource handler stopped")

    async def _handle_registration(self, data: Any, reply_subject: str | None) -> None:
        """Handle incoming resource registration requests.

        Args:
            data: Raw request data
            reply_subject: Subject to send response to
        """
        if not reply_subject:
            logger.error("Resource registration request missing reply subject")
            return

        try:
            # Parse request
            try:
                request = ResourceRegistrationRequest(**data)
            except Exception as e:
                # Handle Pydantic validation errors
                logger.warning(
                    "Invalid resource registration request",
                    extra={
                        "error": str(e),
                    },
                )
                await self._send_error_response(
                    reply_subject=reply_subject,
                    error_code="VALIDATION_ERROR",
                    message=f"Invalid request data: {e}",
                    details={"validation_errors": str(e)},
                )
                return

            logger.info(
                "Processing resource registration request",
                extra={
                    "service_name": request.service_name,
                    "instance_id": request.instance_id,
                    "resource_count": len(request.resource_ids),
                    "trace_id": request.trace_id,
                },
            )

            # Process registration through service layer
            registered = []
            conflicts = {}

            for resource_id in request.resource_ids:
                try:
                    # Get metadata for this resource if provided
                    metadata = request.metadata.get(resource_id)

                    # Register the resource
                    resource = await self._resource_service.register_resource(
                        service_name=request.service_name,
                        instance_id=request.instance_id,
                        resource_id=resource_id,
                        metadata=metadata,
                        force=request.force,
                    )
                    registered.append(resource.resource_id)

                except ResourceConflictError as e:
                    # Handle resource conflict
                    if not request.force:
                        # Extract the current owner from the error details
                        current_owner = e.details.get("current_owner", "unknown")
                        conflicts[resource_id] = current_owner
                        logger.warning(
                            "Resource registration conflict",
                            extra={
                                "resource_id": resource_id,
                                "current_owner": current_owner,
                                "instance_id": request.instance_id,
                                "trace_id": request.trace_id,
                            },
                        )

            # Build response
            success = len(conflicts) == 0
            response = ResourceRegistrationResponse(
                success=success,
                registered=registered,
                conflicts=conflicts,
                trace_id=request.trace_id,
            )

            # Send success response
            await self._nats_client.publish(
                subject=reply_subject,
                data=response.model_dump(),
            )

        except ValidationError as e:
            # Handle validation errors
            logger.warning(
                "Invalid resource registration request",
                extra={
                    "error": str(e),
                    "details": e.details,
                },
            )

            await self._send_error_response(
                reply_subject=reply_subject,
                error_code="VALIDATION_ERROR",
                message=str(e),
                details=e.details,
            )

        except AegisIPCError as e:
            # Handle domain errors
            logger.error(
                "Resource registration failed",
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
                "Unexpected error during resource registration",
                exc_info=e,
            )

            await self._send_error_response(
                reply_subject=reply_subject,
                error_code="INTERNAL_ERROR",
                message="An unexpected error occurred during resource registration",
                details={"error": str(e)},
            )

    async def _handle_release(self, data: Any, reply_subject: str | None) -> None:
        """Handle incoming resource release requests.

        Args:
            data: Raw request data
            reply_subject: Subject to send response to
        """
        if not reply_subject:
            logger.error("Resource release request missing reply subject")
            return

        try:
            # Parse request
            try:
                request = ResourceReleaseRequest(**data)
            except Exception as e:
                # Handle Pydantic validation errors
                logger.warning(
                    "Invalid resource release request",
                    extra={
                        "error": str(e),
                    },
                )
                await self._send_error_response(
                    reply_subject=reply_subject,
                    error_code="VALIDATION_ERROR",
                    message=f"Invalid request data: {e}",
                    details={"validation_errors": str(e)},
                )
                return

            logger.info(
                "Processing resource release request",
                extra={
                    "service_name": request.service_name,
                    "instance_id": request.instance_id,
                    "resource_count": len(request.resource_ids),
                    "trace_id": request.trace_id,
                },
            )

            # Process releases through service layer
            released = []
            errors = {}

            for resource_id in request.resource_ids:
                try:
                    # Release the resource
                    success = await self._resource_service.release_resource(
                        resource_id=resource_id,
                        instance_id=request.instance_id,
                    )
                    if success:
                        released.append(resource_id)
                    else:
                        errors[resource_id] = "Release failed"

                except ResourceNotFoundError:
                    errors[resource_id] = "Resource not found"
                    logger.warning(
                        "Attempted to release non-existent resource",
                        extra={
                            "resource_id": resource_id,
                            "instance_id": request.instance_id,
                            "trace_id": request.trace_id,
                        },
                    )
                except ValidationError as e:
                    errors[resource_id] = f"Validation error: {e!s}"
                    logger.warning(
                        "Resource release validation error",
                        extra={
                            "resource_id": resource_id,
                            "error": str(e),
                            "trace_id": request.trace_id,
                        },
                    )

            # Build response
            success = len(errors) == 0
            response = ResourceReleaseResponse(
                success=success,
                released=released,
                errors=errors,
                trace_id=request.trace_id,
            )

            # Send success response
            await self._nats_client.publish(
                subject=reply_subject,
                data=response.model_dump(),
            )

        except ValidationError as e:
            # Handle validation errors
            logger.warning(
                "Invalid resource release request",
                extra={
                    "error": str(e),
                    "details": e.details,
                },
            )

            await self._send_error_response(
                reply_subject=reply_subject,
                error_code="VALIDATION_ERROR",
                message=str(e),
                details=e.details,
            )

        except AegisIPCError as e:
            # Handle domain errors
            logger.error(
                "Resource release failed",
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
                "Unexpected error during resource release",
                exc_info=e,
            )

            await self._send_error_response(
                reply_subject=reply_subject,
                error_code="INTERNAL_ERROR",
                message="An unexpected error occurred during resource release",
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
