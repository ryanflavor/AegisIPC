"""Message storage service implementation.

This module provides an in-memory implementation of the MessageStore interface
with TTL-based automatic cleanup for exactly-once delivery support.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from ipc_router.domain.entities import Message, MessageState
from ipc_router.domain.exceptions import MessageStorageError, NotFoundError
from ipc_router.domain.interfaces import MessageStore
from ipc_router.infrastructure.logging import get_logger

if TYPE_CHECKING:
    from asyncio import Task

logger = get_logger(__name__)


class MessageStoreService(MessageStore):
    """In-memory message store with TTL and automatic cleanup.

    This implementation provides:
    - Thread-safe in-memory storage using asyncio locks
    - Automatic cleanup of expired messages
    - Configurable TTL for message retention
    - Efficient duplicate detection

    Attributes:
        default_ttl: Default time-to-live for messages in seconds
        cleanup_interval: Interval for running cleanup task in seconds
        max_messages: Maximum number of messages to store (LRU eviction)
    """

    def __init__(
        self,
        default_ttl: int = 3600,  # 1 hour
        cleanup_interval: int = 300,  # 5 minutes
        max_messages: int = 10000,
    ) -> None:
        """Initialize the message store service.

        Args:
            default_ttl: Default TTL for messages in seconds
            cleanup_interval: Cleanup task interval in seconds
            max_messages: Maximum number of messages to store
        """
        self._messages: dict[str, Message] = {}
        self._lock = asyncio.Lock()
        self.default_ttl = default_ttl
        self.cleanup_interval = cleanup_interval
        self.max_messages = max_messages
        self._cleanup_task: Task[None] | None = None
        self._running = False

        logger.info(
            "Initialized MessageStoreService",
            extra={
                "default_ttl": default_ttl,
                "cleanup_interval": cleanup_interval,
                "max_messages": max_messages,
            },
        )

    async def start(self) -> None:
        """Start the background cleanup task."""
        if self._running:
            return

        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("Started message store cleanup task")

    async def stop(self) -> None:
        """Stop the background cleanup task."""
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._cleanup_task
        logger.info("Stopped message store cleanup task")

    async def store_message(self, message: Message) -> None:
        """Store a message in memory.

        Args:
            message: Message entity to persist

        Raises:
            MessageStorageError: If storage fails
        """
        try:
            async with self._lock:
                # Check if we need to evict old messages
                if len(self._messages) >= self.max_messages:
                    await self._evict_oldest_messages()

                self._messages[message.message_id] = message

            logger.info(
                "Stored message",
                extra={
                    "message_id": message.message_id,
                    "service_name": message.service_name,
                    "method": message.method,
                    "state": message.state.value,
                    "trace_id": message.trace_id,
                },
            )
        except Exception as e:
            logger.error(
                "Failed to store message",
                exc_info=e,
                extra={
                    "message_id": message.message_id,
                    "error": str(e),
                },
            )
            raise MessageStorageError(
                operation="store",
                message_id=message.message_id,
                reason=str(e),
            ) from e

    async def get_message(self, message_id: str) -> Message | None:
        """Retrieve a message by ID.

        Args:
            message_id: Unique message identifier

        Returns:
            Message if found, None otherwise
        """
        async with self._lock:
            message = self._messages.get(message_id)

        if message:
            logger.debug(
                "Retrieved message",
                extra={
                    "message_id": message_id,
                    "state": message.state.value,
                },
            )
        return message

    async def is_duplicate(self, message_id: str) -> bool:
        """Check if a message ID exists.

        Args:
            message_id: Unique message identifier

        Returns:
            True if message exists, False otherwise
        """
        async with self._lock:
            exists = message_id in self._messages

        if exists:
            logger.debug(
                "Duplicate message detected",
                extra={"message_id": message_id},
            )
        return exists

    async def update_message_state(
        self,
        message_id: str,
        state: str,
        response: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        """Update message state.

        Args:
            message_id: Message to update
            state: New state value
            response: Optional response data
            error: Optional error message

        Raises:
            NotFoundError: If message doesn't exist
            MessageStorageError: If update fails
        """
        try:
            async with self._lock:
                message = self._messages.get(message_id)
                if not message:
                    raise NotFoundError("Message", message_id)

                # Update state
                old_state = message.state
                message.state = MessageState(state)
                message.updated_at = datetime.now(UTC)

                # Update response or error
                if response is not None:
                    message.response = response
                if error is not None:
                    message.last_error = error

            logger.info(
                "Updated message state",
                extra={
                    "message_id": message_id,
                    "old_state": old_state.value,
                    "new_state": state,
                    "has_response": response is not None,
                    "has_error": error is not None,
                },
            )
        except NotFoundError:
            raise
        except Exception as e:
            logger.error(
                "Failed to update message state",
                exc_info=e,
                extra={
                    "message_id": message_id,
                    "state": state,
                    "error": str(e),
                },
            )
            raise MessageStorageError(
                operation="update",
                message_id=message_id,
                reason=str(e),
            ) from e

    async def get_expired_messages(self, limit: int = 100) -> list[Message]:
        """Get expired messages.

        Args:
            limit: Maximum messages to return

        Returns:
            List of expired messages
        """
        expired_messages: list[Message] = []
        now = datetime.now(UTC)

        async with self._lock:
            for message in self._messages.values():
                if message.is_expired() or (
                    message.state == MessageState.PENDING and message.ack_deadline < now
                ):
                    expired_messages.append(message)
                    if len(expired_messages) >= limit:
                        break

        if expired_messages:
            logger.debug(
                f"Found {len(expired_messages)} expired messages",
                extra={"count": len(expired_messages)},
            )
        return expired_messages

    async def delete_message(self, message_id: str) -> None:
        """Delete a message.

        Args:
            message_id: Message to delete

        Raises:
            NotFoundError: If message doesn't exist
            MessageStorageError: If deletion fails
        """
        try:
            async with self._lock:
                if message_id not in self._messages:
                    raise NotFoundError("Message", message_id)
                del self._messages[message_id]

            logger.info(
                "Deleted message",
                extra={"message_id": message_id},
            )
        except NotFoundError:
            raise
        except Exception as e:
            logger.error(
                "Failed to delete message",
                exc_info=e,
                extra={
                    "message_id": message_id,
                    "error": str(e),
                },
            )
            raise MessageStorageError(
                operation="delete",
                message_id=message_id,
                reason=str(e),
            ) from e

    async def get_pending_messages_for_retry(
        self,
        service_name: str | None = None,
        limit: int = 100,
    ) -> list[Message]:
        """Get pending messages eligible for retry.

        Args:
            service_name: Optional service filter
            limit: Maximum messages to return

        Returns:
            List of messages eligible for retry
        """
        retry_messages: list[Message] = []

        async with self._lock:
            for message in self._messages.values():
                if message.state != MessageState.PENDING:
                    continue
                if service_name and message.service_name != service_name:
                    continue
                if message.can_retry():
                    retry_messages.append(message)
                    if len(retry_messages) >= limit:
                        break

        if retry_messages:
            logger.debug(
                f"Found {len(retry_messages)} messages for retry",
                extra={
                    "count": len(retry_messages),
                    "service_name": service_name,
                },
            )
        return retry_messages

    async def _cleanup_loop(self) -> None:
        """Background task to clean up expired messages."""
        while self._running:
            try:
                await asyncio.sleep(self.cleanup_interval)
                await self._cleanup_expired_messages()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(
                    "Error in cleanup loop",
                    exc_info=e,
                    extra={"error": str(e)},
                )

    async def _cleanup_expired_messages(self) -> None:
        """Remove expired messages from storage."""
        now = datetime.now(UTC)
        ttl_cutoff = now - timedelta(seconds=self.default_ttl)
        expired_ids: list[str] = []

        async with self._lock:
            for message_id, message in self._messages.items():
                # Remove if expired or older than TTL
                if message.is_expired() or message.created_at < ttl_cutoff:
                    expired_ids.append(message_id)

            # Delete expired messages
            for message_id in expired_ids:
                del self._messages[message_id]

        if expired_ids:
            logger.info(
                f"Cleaned up {len(expired_ids)} expired messages",
                extra={"count": len(expired_ids)},
            )

    async def _evict_oldest_messages(self) -> None:
        """Evict oldest messages when at capacity."""
        # Sort by created_at and remove oldest 10%
        sorted_messages = sorted(
            self._messages.items(),
            key=lambda x: x[1].created_at,
        )

        evict_count = max(1, len(sorted_messages) // 10)
        for message_id, _ in sorted_messages[:evict_count]:
            del self._messages[message_id]

        logger.warning(
            f"Evicted {evict_count} oldest messages due to capacity",
            extra={
                "evicted_count": evict_count,
                "total_messages": len(self._messages),
            },
        )
