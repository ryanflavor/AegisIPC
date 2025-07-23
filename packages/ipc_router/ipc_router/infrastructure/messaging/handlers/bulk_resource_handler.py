"""Bulk resource management RPC handler."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from ipc_router.application.models import (
    BatchResult,
    BulkResourceRegistrationRequest,
    BulkResourceRegistrationResponse,
    BulkResourceReleaseRequest,
    BulkResourceReleaseResponse,
    ResourceRegistrationFailure,
    ResourceRegistrationItem,
    ResourceReleaseFailure,
)
from ipc_router.application.services import ResourceService
from ipc_router.domain.entities import ResourceMetadata
from ipc_router.domain.exceptions import (
    ResourceConflictError,
    ResourceReleaseError,
    ValidationError,
)
from ipc_router.infrastructure.logging import get_logger
from ipc_router.infrastructure.messaging.nats_client import NATSClient

logger = get_logger(__name__)


class BulkResourceHandler:
    """Handles bulk resource management RPC requests via NATS.

    This handler provides batch processing capabilities for resource
    registration and release operations, supporting large-scale deployments.
    """

    BULK_REGISTRATION_SUBJECT = "ipc.resource.bulk_register"
    BULK_RELEASE_SUBJECT = "ipc.resource.bulk_release"

    def __init__(
        self,
        nats_client: NATSClient,
        resource_service: ResourceService,
        max_concurrent_batches: int = 5,
    ) -> None:
        """Initialize the bulk resource handler.

        Args:
            nats_client: NATS client for messaging
            resource_service: Resource service for managing resources
            max_concurrent_batches: Maximum concurrent batch operations
        """
        self._nats_client = nats_client
        self._resource_service = resource_service
        self._max_concurrent_batches = max_concurrent_batches
        self._semaphore = asyncio.Semaphore(max_concurrent_batches)

    async def start(self) -> None:
        """Start listening for bulk resource management requests."""
        # Subscribe to bulk registration requests
        await self._nats_client.subscribe(
            subject=self.BULK_REGISTRATION_SUBJECT,
            callback=self._handle_bulk_registration,
            queue="bulk-resource-registry",
        )
        logger.info(
            "Bulk resource registration handler started",
            extra={
                "subject": self.BULK_REGISTRATION_SUBJECT,
                "max_concurrent_batches": self._max_concurrent_batches,
            },
        )

        # Subscribe to bulk release requests
        await self._nats_client.subscribe(
            subject=self.BULK_RELEASE_SUBJECT,
            callback=self._handle_bulk_release,
            queue="bulk-resource-registry",
        )
        logger.info(
            "Bulk resource release handler started",
            extra={"subject": self.BULK_RELEASE_SUBJECT},
        )

    async def stop(self) -> None:
        """Stop listening for bulk resource management requests."""
        await self._nats_client.unsubscribe(self.BULK_REGISTRATION_SUBJECT)
        await self._nats_client.unsubscribe(self.BULK_RELEASE_SUBJECT)
        logger.info("Bulk resource handler stopped")

    async def _handle_bulk_registration(self, data: Any, reply_subject: str | None) -> None:
        """Handle incoming bulk resource registration requests.

        Args:
            data: Raw request data
            reply_subject: Subject to send response to
        """
        if not reply_subject:
            logger.error("Bulk resource registration request missing reply subject")
            return

        try:
            # Parse request
            request = BulkResourceRegistrationRequest(**data)

            logger.info(
                "Processing bulk resource registration request",
                extra={
                    "service_name": request.service_name,
                    "instance_id": request.instance_id,
                    "total_resources": len(request.resources),
                    "batch_size": request.batch_size,
                    "continue_on_error": request.continue_on_error,
                    "trace_id": request.trace_id,
                },
            )

            # Process registration in batches
            response = await self._process_bulk_registration(request)

            # Send response
            await self._nats_client.publish(
                subject=reply_subject,
                data=response.model_dump(),
            )

        except Exception as e:
            # Check if it's a Pydantic ValidationError
            if e.__class__.__name__ == "ValidationError" and hasattr(e, "errors"):
                logger.warning(
                    "Invalid bulk resource registration request",
                    extra={
                        "error": str(e),
                        "details": (
                            getattr(e, "errors", lambda: [])()
                            if callable(getattr(e, "errors", None))
                            else []
                        ),
                    },
                )

                await self._send_error_response(
                    reply_subject=reply_subject,
                    error_code="VALIDATION_ERROR",
                    message=str(e),
                    details={
                        "validation_errors": (
                            getattr(e, "errors", lambda: [])()
                            if callable(getattr(e, "errors", None))
                            else []
                        )
                    },
                )
                return
            logger.error(
                "Unexpected error during bulk resource registration",
                exc_info=e,
            )

            await self._send_error_response(
                reply_subject=reply_subject,
                error_code="INTERNAL_ERROR",
                message="An unexpected error occurred during bulk resource registration",
                details={"error": str(e)},
            )

    async def _process_bulk_registration(
        self, request: BulkResourceRegistrationRequest
    ) -> BulkResourceRegistrationResponse:
        """Process bulk resource registration in batches.

        Args:
            request: Bulk registration request

        Returns:
            BulkResourceRegistrationResponse with results
        """
        total_requested = len(request.resources)
        registered: list[str] = []
        failed: list[ResourceRegistrationFailure] = []
        batch_results: list[BatchResult] = []

        # Create batches
        batches = [
            request.resources[i : i + request.batch_size]
            for i in range(0, len(request.resources), request.batch_size)
        ]

        logger.info(
            "Processing resources in batches",
            extra={
                "total_batches": len(batches),
                "batch_size": request.batch_size,
                "trace_id": request.trace_id,
            },
        )

        if request.continue_on_error:
            # Process batches concurrently with semaphore limit
            batch_tasks = []
            for batch_num, batch in enumerate(batches):
                task = asyncio.create_task(
                    self._process_registration_batch(
                        request.service_name,
                        request.instance_id,
                        batch,
                        batch_num + 1,
                        request.continue_on_error,
                        request.trace_id,
                    )
                )
                batch_tasks.append(task)

            # Wait for all batches to complete
            batch_results_list = await asyncio.gather(*batch_tasks, return_exceptions=True)

            # Aggregate results
            for result in batch_results_list:
                if isinstance(result, BaseException):
                    logger.error(
                        "Batch processing failed",
                        exc_info=result,
                        extra={"trace_id": request.trace_id},
                    )
                    # Create a failed batch result
                    failed_batch = BatchResult(
                        batch_number=0,
                        success_count=0,
                        failure_count=0,
                        duration_ms=0,
                    )
                    batch_results.append(failed_batch)
                else:
                    batch_result, batch_registered, batch_failed = result
                    registered.extend(batch_registered)
                    failed.extend(batch_failed)
                    batch_results.append(batch_result)
        else:
            # Process batches sequentially, stopping on first error
            for batch_num, batch in enumerate(batches):
                try:
                    (
                        batch_result,
                        batch_registered,
                        batch_failed,
                    ) = await self._process_registration_batch(
                        request.service_name,
                        request.instance_id,
                        batch,
                        batch_num + 1,
                        request.continue_on_error,
                        request.trace_id,
                    )

                    registered.extend(batch_registered)
                    failed.extend(batch_failed)
                    batch_results.append(batch_result)

                    # Stop processing if any errors occurred in this batch
                    if batch_failed:
                        logger.info(
                            "Stopping batch processing due to error",
                            extra={
                                "batch_number": batch_num + 1,
                                "total_batches": len(batches),
                                "trace_id": request.trace_id,
                            },
                        )
                        break

                except Exception as e:
                    logger.error(
                        "Batch processing failed",
                        exc_info=e,
                        extra={"batch_number": batch_num + 1, "trace_id": request.trace_id},
                    )
                    # Create a failed batch result and stop
                    failed_batch = BatchResult(
                        batch_number=batch_num + 1,
                        success_count=0,
                        failure_count=len(batch),
                        duration_ms=0,
                    )
                    batch_results.append(failed_batch)
                    break

        return BulkResourceRegistrationResponse(
            total_requested=total_requested,
            total_registered=len(registered),
            registered=registered,
            failed=failed,
            batch_results=batch_results,
            trace_id=request.trace_id,
        )

    async def _process_registration_batch(
        self,
        service_name: str,
        instance_id: str,
        batch: list[ResourceRegistrationItem],
        batch_number: int,
        continue_on_error: bool,
        trace_id: str,
    ) -> tuple[BatchResult, list[str], list[ResourceRegistrationFailure]]:
        """Process a single batch of resource registrations.

        Args:
            service_name: Service name
            instance_id: Instance ID
            batch: Batch of resources to register
            batch_number: Batch number for tracking
            continue_on_error: Whether to continue on errors
            trace_id: Trace ID for distributed tracing

        Returns:
            Tuple of (batch result, registered IDs, failures)
        """
        async with self._semaphore:
            start_time = datetime.now(UTC)
            registered: list[str] = []
            failed: list[ResourceRegistrationFailure] = []

            logger.info(
                "Processing registration batch",
                extra={
                    "batch_number": batch_number,
                    "batch_size": len(batch),
                    "trace_id": trace_id,
                },
            )

            for item in batch:
                try:
                    # Register the resource
                    resource = await self._resource_service.register_resource(
                        service_name=service_name,
                        instance_id=instance_id,
                        resource_id=item.resource_id,
                        metadata=item.metadata,
                        force=item.force,
                    )
                    registered.append(resource.resource_id)

                except ResourceConflictError as e:
                    failure = ResourceRegistrationFailure(
                        resource_id=item.resource_id,
                        reason=str(e),
                        current_owner=e.details.get("current_owner"),
                        error_code="RESOURCE_CONFLICT",
                    )
                    failed.append(failure)

                    if not continue_on_error:
                        logger.warning(
                            "Batch processing stopped due to conflict",
                            extra={
                                "batch_number": batch_number,
                                "resource_id": item.resource_id,
                                "trace_id": trace_id,
                            },
                        )
                        break

                except ValidationError as e:
                    failure = ResourceRegistrationFailure(
                        resource_id=item.resource_id,
                        reason=str(e),
                        current_owner=None,
                        error_code="VALIDATION_ERROR",
                    )
                    failed.append(failure)

                    if not continue_on_error:
                        logger.warning(
                            "Batch processing stopped due to validation error",
                            extra={
                                "batch_number": batch_number,
                                "resource_id": item.resource_id,
                                "trace_id": trace_id,
                            },
                        )
                        break

                except Exception as e:
                    failure = ResourceRegistrationFailure(
                        resource_id=item.resource_id,
                        reason=str(e),
                        current_owner=None,
                        error_code="UNKNOWN_ERROR",
                    )
                    failed.append(failure)

                    if not continue_on_error:
                        logger.error(
                            "Batch processing stopped due to unexpected error",
                            exc_info=e,
                            extra={
                                "batch_number": batch_number,
                                "resource_id": item.resource_id,
                                "trace_id": trace_id,
                            },
                        )
                        break

            # Calculate duration
            duration_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000

            batch_result = BatchResult(
                batch_number=batch_number,
                success_count=len(registered),
                failure_count=len(failed),
                duration_ms=duration_ms,
            )

            logger.info(
                "Batch processing completed",
                extra={
                    "batch_number": batch_number,
                    "success_count": len(registered),
                    "failure_count": len(failed),
                    "duration_ms": duration_ms,
                    "trace_id": trace_id,
                },
            )

            return batch_result, registered, failed

    async def _handle_bulk_release(self, data: Any, reply_subject: str | None) -> None:
        """Handle incoming bulk resource release requests.

        Args:
            data: Raw request data
            reply_subject: Subject to send response to
        """
        if not reply_subject:
            logger.error("Bulk resource release request missing reply subject")
            return

        try:
            # Parse request
            request = BulkResourceReleaseRequest(**data)

            logger.info(
                "Processing bulk resource release request",
                extra={
                    "service_name": request.service_name,
                    "instance_id": request.instance_id,
                    "total_resources": len(request.resource_ids),
                    "batch_size": request.batch_size,
                    "continue_on_error": request.continue_on_error,
                    "transactional": request.transactional,
                    "trace_id": request.trace_id,
                },
            )

            # Process release in batches
            response = await self._process_bulk_release(request)

            # Send response
            await self._nats_client.publish(
                subject=reply_subject,
                data=response.model_dump(),
            )

        except Exception as e:
            # Check if it's a Pydantic ValidationError
            if e.__class__.__name__ == "ValidationError" and hasattr(e, "errors"):
                logger.warning(
                    "Invalid bulk resource release request",
                    extra={
                        "error": str(e),
                        "details": (
                            getattr(e, "errors", lambda: [])()
                            if callable(getattr(e, "errors", None))
                            else []
                        ),
                    },
                )

                await self._send_error_response(
                    reply_subject=reply_subject,
                    error_code="VALIDATION_ERROR",
                    message=str(e),
                    details={
                        "validation_errors": (
                            getattr(e, "errors", lambda: [])()
                            if callable(getattr(e, "errors", None))
                            else []
                        )
                    },
                )
                return
            logger.error(
                "Unexpected error during bulk resource release",
                exc_info=e,
            )

            await self._send_error_response(
                reply_subject=reply_subject,
                error_code="INTERNAL_ERROR",
                message="An unexpected error occurred during bulk resource release",
                details={"error": str(e)},
            )

    async def _process_bulk_release(
        self, request: BulkResourceReleaseRequest
    ) -> BulkResourceReleaseResponse:
        """Process bulk resource release in batches with optional transactional support.

        Args:
            request: Bulk release request

        Returns:
            BulkResourceReleaseResponse with results
        """
        total_requested = len(request.resource_ids)
        released: list[str] = []
        failed: list[ResourceReleaseFailure] = []
        batch_results: list[BatchResult] = []
        rollback_performed = False

        # Create batches
        batches = [
            request.resource_ids[i : i + request.batch_size]
            for i in range(0, len(request.resource_ids), request.batch_size)
        ]

        logger.info(
            "Processing resource releases in batches",
            extra={
                "total_batches": len(batches),
                "batch_size": request.batch_size,
                "transactional": request.transactional,
                "trace_id": request.trace_id,
            },
        )

        if request.transactional:
            # For transactional processing, we need to track all operations
            # and be able to rollback if any failure occurs
            all_released: list[tuple[str, ResourceMetadata | None]] = []
            transaction_failed = False

            for batch_num, batch in enumerate(batches):
                if transaction_failed and not request.continue_on_error:
                    break

                batch_result, batch_released, batch_failed = await self._process_release_batch(
                    request.service_name,
                    request.instance_id,
                    batch,
                    batch_num + 1,
                    request.continue_on_error,
                    request.trace_id,
                )

                # Store resource IDs with their metadata for potential rollback
                for resource_id in batch_released:
                    # Fetch metadata before it's lost
                    resource = await self._resource_service._registry.get_resource(resource_id)
                    metadata = resource.metadata if resource else None
                    all_released.append((resource_id, metadata))

                failed.extend(batch_failed)
                batch_results.append(batch_result)

                # Check if we need to rollback
                if batch_failed and request.transactional and not request.continue_on_error:
                    transaction_failed = True
                    logger.warning(
                        "Transactional bulk release failed, initiating rollback",
                        extra={
                            "batch_number": batch_num + 1,
                            "resources_to_rollback": len(all_released),
                            "trace_id": request.trace_id,
                        },
                    )

                    # Rollback by re-registering all released resources
                    rollback_success = await self._rollback_released_resources(
                        request.service_name,
                        request.instance_id,
                        all_released,
                        request.trace_id,
                    )
                    rollback_performed = True  # We attempted rollback

                    # Clear the released list only if rollback succeeded
                    if rollback_success:
                        released = []
                    break

            if not transaction_failed:
                released = [resource_id for resource_id, _ in all_released]

        else:
            # Non-transactional processing - process all batches independently
            batch_tasks = []
            for batch_num, batch in enumerate(batches):
                task = asyncio.create_task(
                    self._process_release_batch(
                        request.service_name,
                        request.instance_id,
                        batch,
                        batch_num + 1,
                        request.continue_on_error,
                        request.trace_id,
                    )
                )
                batch_tasks.append(task)

            # Wait for all batches to complete
            batch_results_list = await asyncio.gather(*batch_tasks, return_exceptions=True)

            # Aggregate results
            for result in batch_results_list:
                if isinstance(result, BaseException):
                    logger.error(
                        "Batch processing failed",
                        exc_info=result,
                        extra={"trace_id": request.trace_id},
                    )
                    # Create a failed batch result
                    failed_batch = BatchResult(
                        batch_number=0,
                        success_count=0,
                        failure_count=0,
                        duration_ms=0,
                    )
                    batch_results.append(failed_batch)
                else:
                    batch_result, batch_released, batch_failed = result
                    released.extend(batch_released)
                    failed.extend(batch_failed)
                    batch_results.append(batch_result)

        return BulkResourceReleaseResponse(
            total_requested=total_requested,
            total_released=len(released),
            released=released,
            failed=failed,
            batch_results=batch_results,
            rollback_performed=rollback_performed,
            trace_id=request.trace_id,
        )

    async def _process_release_batch(
        self,
        service_name: str,
        instance_id: str,
        batch: list[str],
        batch_number: int,
        continue_on_error: bool,
        trace_id: str,
    ) -> tuple[BatchResult, list[str], list[ResourceReleaseFailure]]:
        """Process a single batch of resource releases.

        Args:
            service_name: Service name
            instance_id: Instance ID
            batch: Batch of resource IDs to release
            batch_number: Batch number for tracking
            continue_on_error: Whether to continue on errors
            trace_id: Trace ID for distributed tracing

        Returns:
            Tuple of (batch result, released IDs, failures)
        """
        async with self._semaphore:
            start_time = datetime.now(UTC)
            released: list[str] = []
            failed: list[ResourceReleaseFailure] = []

            logger.info(
                "Processing release batch",
                extra={
                    "batch_number": batch_number,
                    "batch_size": len(batch),
                    "trace_id": trace_id,
                },
            )

            for resource_id in batch:
                try:
                    # Release the resource
                    success = await self._resource_service.release_resource(
                        resource_id=resource_id,
                        instance_id=instance_id,
                    )
                    if success:
                        released.append(resource_id)
                    else:
                        failure = ResourceReleaseFailure(
                            resource_id=resource_id,
                            reason="Resource not found or already released",
                            error_code="NOT_FOUND",
                        )
                        failed.append(failure)

                except ResourceReleaseError as e:
                    failure = ResourceReleaseFailure(
                        resource_id=resource_id,
                        reason=str(e),
                        error_code="NOT_OWNER",
                    )
                    failed.append(failure)

                    if not continue_on_error:
                        logger.warning(
                            "Batch processing stopped due to release error",
                            extra={
                                "batch_number": batch_number,
                                "resource_id": resource_id,
                                "trace_id": trace_id,
                            },
                        )
                        break

                except ValidationError as e:
                    failure = ResourceReleaseFailure(
                        resource_id=resource_id,
                        reason=str(e),
                        error_code="VALIDATION_ERROR",
                    )
                    failed.append(failure)

                    if not continue_on_error:
                        logger.warning(
                            "Batch processing stopped due to validation error",
                            extra={
                                "batch_number": batch_number,
                                "resource_id": resource_id,
                                "trace_id": trace_id,
                            },
                        )
                        break

                except Exception as e:
                    failure = ResourceReleaseFailure(
                        resource_id=resource_id,
                        reason=str(e),
                        error_code="UNKNOWN_ERROR",
                    )
                    failed.append(failure)

                    if not continue_on_error:
                        logger.error(
                            "Batch processing stopped due to unexpected error",
                            exc_info=e,
                            extra={
                                "batch_number": batch_number,
                                "resource_id": resource_id,
                                "trace_id": trace_id,
                            },
                        )
                        break

            # Calculate duration
            duration_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000

            batch_result = BatchResult(
                batch_number=batch_number,
                success_count=len(released),
                failure_count=len(failed),
                duration_ms=duration_ms,
            )

            logger.info(
                "Batch processing completed",
                extra={
                    "batch_number": batch_number,
                    "success_count": len(released),
                    "failure_count": len(failed),
                    "duration_ms": duration_ms,
                    "trace_id": trace_id,
                },
            )

            return batch_result, released, failed

    async def _rollback_released_resources(
        self,
        service_name: str,
        instance_id: str,
        resources: list[tuple[str, ResourceMetadata | None]],
        trace_id: str,
    ) -> bool:
        """Rollback released resources by re-registering them.

        Args:
            service_name: Service name
            instance_id: Instance ID
            resources: List of (resource_id, metadata) tuples to rollback
            trace_id: Trace ID for distributed tracing

        Returns:
            True if rollback succeeded, False otherwise
        """
        logger.info(
            "Starting resource release rollback",
            extra={
                "service_name": service_name,
                "instance_id": instance_id,
                "resource_count": len(resources),
                "trace_id": trace_id,
            },
        )

        rollback_failures = 0
        for resource_id, metadata in resources:
            try:
                # Re-register the resource with force=True to reclaim ownership
                # Use the preserved metadata if available, otherwise create a default one
                if metadata is None:
                    # Create default metadata if not preserved
                    from datetime import UTC, datetime

                    from ipc_router.domain.entities import ResourceMetadata

                    metadata = ResourceMetadata(
                        resource_type="rollback",
                        version=1,
                        created_by=instance_id,
                        last_modified=datetime.now(UTC),
                        tags=["rollback"],
                        attributes={"rollback_reason": "transaction_failed"},
                    )

                await self._resource_service.register_resource(
                    service_name=service_name,
                    instance_id=instance_id,
                    resource_id=resource_id,
                    metadata=metadata,
                    force=True,
                )
            except Exception as e:
                rollback_failures += 1
                logger.error(
                    "Failed to rollback resource",
                    exc_info=e,
                    extra={
                        "resource_id": resource_id,
                        "trace_id": trace_id,
                    },
                )

        if rollback_failures > 0:
            logger.error(
                "Rollback completed with failures",
                extra={
                    "total_resources": len(resources),
                    "failed_rollbacks": rollback_failures,
                    "trace_id": trace_id,
                },
            )
            return False

        logger.info(
            "Rollback completed successfully",
            extra={
                "resources_rolled_back": len(resources),
                "trace_id": trace_id,
            },
        )
        return True

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
