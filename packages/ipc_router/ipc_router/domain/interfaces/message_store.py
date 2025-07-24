"""Abstract interface for message storage.

This module defines the MessageStore interface for persisting and retrieving
messages in the exactly-once delivery system.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ipc_router.domain.entities import Message


class MessageStore(ABC):
    """Abstract interface for message persistence and retrieval.

    This interface defines the contract for storing messages, checking for
    duplicates, and updating message states to support exactly-once delivery.
    """

    @abstractmethod
    async def store_message(self, message: Message) -> None:
        """Store a message in the persistence layer.

        Args:
            message: Message entity to persist

        Raises:
            MessageStorageError: If message cannot be stored
        """
        ...

    @abstractmethod
    async def get_message(self, message_id: str) -> Message | None:
        """Retrieve a message by its ID.

        Args:
            message_id: Unique message identifier

        Returns:
            Message entity if found, None otherwise
        """
        ...

    @abstractmethod
    async def is_duplicate(self, message_id: str) -> bool:
        """Check if a message ID already exists.

        Args:
            message_id: Unique message identifier to check

        Returns:
            True if message ID exists, False otherwise
        """
        ...

    @abstractmethod
    async def update_message_state(
        self,
        message_id: str,
        state: str,
        response: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        """Update the state of an existing message.

        Args:
            message_id: Unique message identifier
            state: New message state value
            response: Optional response data for caching
            error: Optional error message for failed states

        Raises:
            MessageNotFoundError: If message doesn't exist
            MessageStorageError: If update fails
        """
        ...

    @abstractmethod
    async def get_expired_messages(self, limit: int = 100) -> list[Message]:
        """Retrieve messages that have expired.

        Args:
            limit: Maximum number of expired messages to return

        Returns:
            List of expired messages
        """
        ...

    @abstractmethod
    async def delete_message(self, message_id: str) -> None:
        """Delete a message from storage.

        Args:
            message_id: Unique message identifier to delete

        Raises:
            MessageNotFoundError: If message doesn't exist
            MessageStorageError: If deletion fails
        """
        ...

    @abstractmethod
    async def get_pending_messages_for_retry(
        self,
        service_name: str | None = None,
        limit: int = 100,
    ) -> list[Message]:
        """Retrieve pending messages eligible for retry.

        Args:
            service_name: Optional filter by service name
            limit: Maximum number of messages to return

        Returns:
            List of messages eligible for retry
        """
        ...
