"""Idempotent handler decorator for message processing."""

import asyncio
import functools
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar, cast

from ipc_router.domain.entities.message import MessageState
from ipc_router.domain.exceptions import DuplicateMessageError
from ipc_router.domain.interfaces.message_store import MessageStore

logger = logging.getLogger(__name__)

T = TypeVar("T")


def idempotent_handler(
    message_store: MessageStore,
    message_id_getter: Callable[[Any], str | None],
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Decorator that ensures idempotent message processing.

    This decorator:
    1. Checks if a message has been processed before
    2. Returns cached response for duplicate messages
    3. Caches the response after successful processing

    Args:
        message_store: The message store to check for duplicates
        message_id_getter: Function to extract message_id from handler arguments

    Returns:
        Decorator function

    Example:
        @idempotent_handler(
            message_store=store,
            message_id_getter=lambda req: req.message_id
        )
        async def handle_request(self, request: RouteRequest) -> RouteResponse:
            # Process request
            return response
    """

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            # Extract message_id
            message_id = message_id_getter(*args, **kwargs)
            if not message_id:
                # No message_id provided, proceed without idempotency
                return await func(*args, **kwargs)

            # Check if message is duplicate
            is_duplicate = await message_store.is_duplicate(message_id)
            if is_duplicate:
                # Get the message to check its state and cached response
                message = await message_store.get_message(message_id)
                if (
                    message
                    and message.state == MessageState.ACKNOWLEDGED
                    and message.response is not None
                ):
                    logger.info(
                        "Returning cached response for duplicate message",
                        extra={
                            "message_id": message_id,
                            "service_name": message.service_name,
                            "method": message.method,
                        },
                    )
                    # Raise DuplicateMessageError with cached response
                    raise DuplicateMessageError(
                        message_id=message_id, cached_response=message.response
                    )

                # Message exists but no cached response, let it reprocess
                logger.warning(
                    "Duplicate message without cached response, reprocessing",
                    extra={
                        "message_id": message_id,
                        "state": message.state.value if message else "unknown",
                    },
                )

            try:
                # Process the request
                result = await func(*args, **kwargs)

                # Cache the successful response atomically
                message = await message_store.get_message(message_id)
                if message:
                    # Update message state and response in a single operation
                    await message_store.update_message_state(
                        message_id, MessageState.ACKNOWLEDGED.value, response=result
                    )

                    logger.info(
                        "Cached response for message",
                        extra={
                            "message_id": message_id,
                            "service_name": message.service_name,
                            "method": message.method,
                        },
                    )

                return result

            except Exception as e:
                # On failure, update message state
                message = await message_store.get_message(message_id)
                if message:
                    await message_store.update_message_state(
                        message_id, MessageState.FAILED.value, None, str(e)
                    )
                raise

        # Only handle async functions - idempotent handling requires async
        if not asyncio.iscoroutinefunction(func):
            raise TypeError(
                f"idempotent_handler can only be applied to async functions, "
                f"but {func.__name__} is not async"
            )

        return cast(Callable[..., Awaitable[T]], wrapper)

    return decorator
