"""Acknowledgment management service implementation.

This module provides acknowledgment handling for exactly-once delivery,
including waiting for acknowledgments with timeout and retry support.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from ipc_router.application.error_handling import RetryConfig, RetryStrategy, with_retry
from ipc_router.domain.exceptions import AcknowledgmentTimeoutError
from ipc_router.domain.interfaces import AcknowledgmentManager
from ipc_router.infrastructure.logging import get_logger

if TYPE_CHECKING:
    from asyncio import Event, Task

logger = get_logger(__name__)

# Type alias for acknowledgment handlers
AckHandler = Callable[[str, bool, Any | None, str | None], Coroutine[Any, Any, None]]


class PendingAcknowledgment:
    """Tracks a pending acknowledgment with its event and metadata."""

    def __init__(
        self,
        message_id: str,
        event: Event,
        trace_id: str,
        timeout_task: Task[None] | None = None,
    ) -> None:
        """Initialize pending acknowledgment.

        Args:
            message_id: Unique message identifier
            event: Asyncio event to signal acknowledgment
            trace_id: Distributed tracing identifier
            timeout_task: Optional timeout monitoring task
        """
        self.message_id = message_id
        self.event = event
        self.trace_id = trace_id
        self.timeout_task = timeout_task
        self.success = False
        self.response_data: Any | None = None
        self.error_message: str | None = None


class AcknowledgmentService(AcknowledgmentManager):
    """Service for managing message acknowledgments.

    This implementation provides:
    - Asynchronous acknowledgment waiting with configurable timeout
    - Handler registration for acknowledgment callbacks
    - Thread-safe acknowledgment tracking
    - Integration with retry mechanisms

    Attributes:
        default_timeout: Default acknowledgment timeout in seconds
        retry_config: Configuration for retry behavior
    """

    def __init__(
        self,
        default_timeout: float = 30.0,
        retry_config: RetryConfig | None = None,
    ) -> None:
        """Initialize the acknowledgment service.

        Args:
            default_timeout: Default timeout in seconds
            retry_config: Optional retry configuration
        """
        self._pending_acks: dict[str, PendingAcknowledgment] = {}
        self._ack_handlers: dict[str, list[AckHandler]] = {}
        self._lock = asyncio.Lock()
        self.default_timeout = default_timeout
        self.retry_config = retry_config or RetryConfig(
            max_attempts=3,
            initial_delay=1.0,
            strategy=RetryStrategy.EXPONENTIAL,
            max_delay=30.0,
        )

        logger.info(
            "Initialized AcknowledgmentService",
            extra={
                "default_timeout": default_timeout,
                "retry_config": {
                    "max_attempts": self.retry_config.max_attempts,
                    "initial_delay": self.retry_config.initial_delay,
                },
            },
        )

    async def wait_for_ack(
        self,
        message_id: str,
        timeout: timedelta,
        trace_id: str,
    ) -> tuple[bool, Any | None]:
        """Wait for acknowledgment of a message.

        Args:
            message_id: Unique message identifier
            timeout: Maximum time to wait
            trace_id: Distributed tracing identifier

        Returns:
            Tuple of (success, response_data)
        """
        timeout_seconds = timeout.total_seconds()

        # Create event for this acknowledgment
        event = asyncio.Event()
        pending = PendingAcknowledgment(
            message_id=message_id,
            event=event,
            trace_id=trace_id,
        )

        async with self._lock:
            self._pending_acks[message_id] = pending

        logger.info(
            "Waiting for acknowledgment",
            extra={
                "message_id": message_id,
                "timeout_seconds": timeout_seconds,
                "trace_id": trace_id,
            },
        )

        try:
            # Wait for acknowledgment or timeout
            await asyncio.wait_for(event.wait(), timeout=timeout_seconds)

            # Acknowledgment received
            logger.info(
                "Acknowledgment received",
                extra={
                    "message_id": message_id,
                    "success": pending.success,
                    "trace_id": trace_id,
                },
            )

            return pending.success, pending.response_data

        except TimeoutError:
            logger.warning(
                "Acknowledgment timeout",
                extra={
                    "message_id": message_id,
                    "timeout_seconds": timeout_seconds,
                    "trace_id": trace_id,
                },
            )

            # Clean up pending acknowledgment
            async with self._lock:
                self._pending_acks.pop(message_id, None)

            return False, None

        finally:
            # Cancel timeout task if it exists
            if pending.timeout_task and not pending.timeout_task.done():
                pending.timeout_task.cancel()

    async def send_ack(
        self,
        message_id: str,
        service_name: str,
        instance_id: str,
        success: bool,
        processing_time_ms: float,
        trace_id: str,
        response_data: Any | None = None,
        error_message: str | None = None,
    ) -> None:
        """Send acknowledgment for a processed message.

        Args:
            message_id: Unique message identifier
            service_name: Name of the acknowledging service
            instance_id: ID of the service instance
            success: Whether processing succeeded
            processing_time_ms: Processing time in milliseconds
            trace_id: Distributed tracing identifier
            response_data: Optional response data
            error_message: Optional error message
        """
        logger.info(
            "Sending acknowledgment",
            extra={
                "message_id": message_id,
                "service_name": service_name,
                "instance_id": instance_id,
                "success": success,
                "processing_time_ms": processing_time_ms,
                "trace_id": trace_id,
                "has_response": response_data is not None,
                "has_error": error_message is not None,
            },
        )

        # Update pending acknowledgment if exists
        async with self._lock:
            pending = self._pending_acks.get(message_id)
            if pending:
                pending.success = success
                pending.response_data = response_data
                pending.error_message = error_message
                pending.event.set()

                # Remove from pending
                self._pending_acks.pop(message_id, None)

        # Notify registered handlers
        async with self._lock:
            handlers = self._ack_handlers.get(message_id, [])

        if handlers:
            # Execute handlers concurrently
            tasks = [
                handler(message_id, success, response_data, error_message) for handler in handlers
            ]
            await asyncio.gather(*tasks, return_exceptions=True)

            # Clean up handlers
            async with self._lock:
                self._ack_handlers.pop(message_id, None)

    async def register_ack_handler(
        self,
        message_id: str,
        handler: AckHandler,
    ) -> None:
        """Register a handler for acknowledgment notification.

        Args:
            message_id: Unique message identifier
            handler: Async function to call when acknowledged
        """
        async with self._lock:
            if message_id not in self._ack_handlers:
                self._ack_handlers[message_id] = []
            self._ack_handlers[message_id].append(handler)

        logger.debug(
            "Registered acknowledgment handler",
            extra={
                "message_id": message_id,
                "handler_count": len(self._ack_handlers.get(message_id, [])),
            },
        )

    async def cancel_ack_wait(self, message_id: str) -> None:
        """Cancel waiting for acknowledgment.

        Args:
            message_id: Unique message identifier
        """
        async with self._lock:
            pending = self._pending_acks.pop(message_id, None)

        if pending:
            # Cancel timeout task
            if pending.timeout_task and not pending.timeout_task.done():
                pending.timeout_task.cancel()

            # Set event to unblock waiter
            pending.event.set()

            logger.info(
                "Cancelled acknowledgment wait",
                extra={
                    "message_id": message_id,
                    "trace_id": pending.trace_id,
                },
            )

    async def get_pending_acks(self) -> list[str]:
        """Get list of message IDs waiting for acknowledgment.

        Returns:
            List of pending message IDs
        """
        async with self._lock:
            return list(self._pending_acks.keys())

    async def wait_for_ack_with_retry(
        self,
        message_id: str,
        service_name: str,
        timeout: timedelta,
        trace_id: str,
        retry_callback: Callable[[], Coroutine[Any, Any, None]] | None = None,
    ) -> tuple[bool, Any | None]:
        """Wait for acknowledgment with automatic retry on timeout.

        This method extends wait_for_ack with retry capability using
        the configured retry policy.

        Args:
            message_id: Unique message identifier
            service_name: Target service name
            timeout: Timeout per attempt
            trace_id: Distributed tracing identifier
            retry_callback: Optional async function to call before retry

        Returns:
            Tuple of (success, response_data)

        Raises:
            AcknowledgmentTimeoutError: If all retry attempts fail
        """
        retry_count = 0

        @with_retry(self.retry_config)  # type: ignore[misc]
        async def attempt_wait() -> tuple[bool, Any | None]:
            nonlocal retry_count

            if retry_count > 0:
                logger.info(
                    f"Retrying acknowledgment wait (attempt {retry_count + 1})",
                    extra={
                        "message_id": message_id,
                        "service_name": service_name,
                        "retry_count": retry_count,
                        "trace_id": trace_id,
                    },
                )

                # Call retry callback if provided
                if retry_callback:
                    await retry_callback()

            success, response_data = await self.wait_for_ack(
                message_id=message_id,
                timeout=timeout,
                trace_id=trace_id,
            )

            if not success:
                retry_count += 1
                raise AcknowledgmentTimeoutError(
                    message_id=message_id,
                    service_name=service_name,
                    timeout_seconds=timeout.total_seconds(),
                    retry_count=retry_count,
                )

            return success, response_data

        try:
            return await attempt_wait()  # type: ignore[no-any-return]
        except AcknowledgmentTimeoutError:
            # All retries exhausted
            logger.error(
                "All acknowledgment retry attempts failed",
                extra={
                    "message_id": message_id,
                    "service_name": service_name,
                    "total_attempts": retry_count,
                    "trace_id": trace_id,
                },
            )
            raise

    async def cleanup_stale_acks(self, max_age: timedelta) -> int:
        """Clean up stale pending acknowledgments.

        This is a maintenance method to remove acknowledgments that
        have been pending for too long without proper cleanup.

        Args:
            max_age: Maximum age for pending acknowledgments

        Returns:
            Number of acknowledgments cleaned up
        """
        # Note: This is a simplified implementation. In production,
        # you would track creation time for each pending acknowledgment
        # and clean up based on age.

        async with self._lock:
            count = len(self._pending_acks)
            self._pending_acks.clear()
            self._ack_handlers.clear()

        if count > 0:
            logger.warning(
                f"Cleaned up {count} stale acknowledgments",
                extra={"count": count},
            )

        return count
