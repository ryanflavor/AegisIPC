"""NATS client for messaging infrastructure."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable, Coroutine
from typing import Any

import msgpack
import nats
from nats.aio.client import Client as NATSConnection
from nats.aio.msg import Msg

from ...domain.exceptions import ConnectionError as IPCConnectionError
from ..logging import get_logger

logger = get_logger(__name__)


class NATSClient:
    """NATS client for handling messaging operations.

    This client manages the connection to NATS server and provides
    methods for publishing and subscribing to messages.
    """

    def __init__(
        self,
        servers: list[str] | str = "nats://localhost:4222",
        name: str = "ipc-router",
        reconnect_time_wait: int = 2,
        max_reconnect_attempts: int = 10,
    ) -> None:
        """Initialize the NATS client.

        Args:
            servers: NATS server URLs
            name: Client name for identification
            reconnect_time_wait: Time to wait between reconnection attempts
            max_reconnect_attempts: Maximum number of reconnection attempts
        """
        self.servers = servers if isinstance(servers, list) else [servers]
        self.name = name
        self.reconnect_time_wait = reconnect_time_wait
        self.max_reconnect_attempts = max_reconnect_attempts
        self._nc: NATSConnection | None = None
        self._subscriptions: dict[str, asyncio.Task[None]] = {}
        self._connected = False

    async def connect(self) -> None:
        """Connect to NATS server."""
        if self._connected:
            logger.warning("NATS client already connected")
            return

        try:
            self._nc = await nats.connect(
                servers=self.servers,
                name=self.name,
                reconnect_time_wait=self.reconnect_time_wait,
                max_reconnect_attempts=self.max_reconnect_attempts,
                error_cb=self._error_callback,
                disconnected_cb=self._disconnected_callback,
                reconnected_cb=self._reconnected_callback,
                closed_cb=self._closed_callback,
            )
            self._connected = True
            logger.info(
                "Connected to NATS server",
                extra={
                    "servers": self.servers,
                    "client_name": self.name,
                },
            )
        except Exception as e:
            logger.error(
                "Failed to connect to NATS server",
                exc_info=e,
                extra={"servers": self.servers},
            )
            raise IPCConnectionError(
                service="NATS",
                endpoint=str(self.servers),
                reason=str(e),
            ) from e

    async def disconnect(self) -> None:
        """Disconnect from NATS server."""
        if not self._connected or not self._nc:
            logger.warning("NATS client not connected")
            return

        # Cancel all subscriptions
        for _subject, task in self._subscriptions.items():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        self._subscriptions.clear()

        # Close connection
        await self._nc.close()
        self._connected = False
        logger.info("Disconnected from NATS server")

    async def publish(
        self,
        subject: str,
        data: Any,
        reply: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Publish a message to a subject.

        Args:
            subject: Subject to publish to
            data: Data to publish (will be serialized with MessagePack)
            reply: Optional reply subject
            headers: Optional headers
        """
        if not self._connected or not self._nc:
            raise IPCConnectionError(
                service="NATS",
                endpoint=str(self.servers),
                reason="Not connected",
            )

        try:
            # Serialize data with MessagePack
            payload = msgpack.packb(data, use_bin_type=True)

            publish_kwargs = {
                "subject": subject,
                "payload": payload,
                "headers": headers,
            }
            if reply is not None:
                publish_kwargs["reply"] = reply

            await self._nc.publish(**publish_kwargs)

            logger.debug(
                "Published message",
                extra={
                    "subject": subject,
                    "payload_size": len(payload),
                    "reply": reply,
                },
            )
        except Exception as e:
            logger.error(
                "Failed to publish message",
                exc_info=e,
                extra={"subject": subject},
            )
            raise

    async def request(
        self,
        subject: str,
        data: Any,
        timeout: float = 5.0,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """Send a request and wait for a response.

        Args:
            subject: Subject to send request to
            data: Request data (will be serialized with MessagePack)
            timeout: Request timeout in seconds
            headers: Optional headers

        Returns:
            Deserialized response data

        Raises:
            asyncio.TimeoutError: If request times out
        """
        if not self._connected or not self._nc:
            raise IPCConnectionError(
                service="NATS",
                endpoint=str(self.servers),
                reason="Not connected",
            )

        try:
            # Serialize request data
            payload = msgpack.packb(data, use_bin_type=True)

            # Send request and wait for response
            response = await self._nc.request(
                subject=subject,
                payload=payload,
                timeout=timeout,
                headers=headers,
            )

            # Deserialize response
            response_data = msgpack.unpackb(response.data, raw=False)

            logger.debug(
                "Received response",
                extra={
                    "subject": subject,
                    "request_size": len(payload),
                    "response_size": len(response.data),
                },
            )

            return response_data
        except TimeoutError:
            logger.error(
                "Request timed out",
                extra={
                    "subject": subject,
                    "timeout": timeout,
                },
            )
            raise
        except Exception as e:
            logger.error(
                "Request failed",
                exc_info=e,
                extra={"subject": subject},
            )
            raise

    async def subscribe(
        self,
        subject: str,
        callback: Callable[[Any, str | None], Coroutine[Any, Any, None]],
        queue: str | None = None,
    ) -> None:
        """Subscribe to a subject.

        Args:
            subject: Subject to subscribe to
            callback: Async callback function that receives (data, reply_subject)
            queue: Optional queue group name
        """
        if not self._connected or not self._nc:
            raise IPCConnectionError(
                service="NATS",
                endpoint=str(self.servers),
                reason="Not connected",
            )

        async def message_handler(msg: Msg) -> None:
            """Handle incoming messages."""
            try:
                # Deserialize message data
                data = msgpack.unpackb(msg.data, raw=False)

                # Call the callback
                await callback(data, msg.reply)

            except Exception as e:
                logger.error(
                    "Error handling message",
                    exc_info=e,
                    extra={
                        "subject": subject,
                        "reply": msg.reply,
                    },
                )

        # Subscribe to the subject
        if queue is not None:
            subscription = await self._nc.subscribe(
                subject=subject,
                cb=message_handler,
                queue=queue,
            )
        else:
            subscription = await self._nc.subscribe(
                subject=subject,
                cb=message_handler,
            )

        # Store subscription task
        self._subscriptions[subject] = asyncio.create_task(self._subscription_handler(subscription))

        logger.info(
            "Subscribed to subject",
            extra={
                "subject": subject,
                "queue": queue,
            },
        )

    async def _subscription_handler(self, subscription: Any) -> None:
        """Handle subscription lifecycle."""
        try:
            # Keep subscription alive
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            # Unsubscribe when cancelled
            await subscription.unsubscribe()
            raise

    async def _error_callback(self, e: Exception) -> None:
        """Handle NATS errors."""
        logger.error("NATS error", exc_info=e)

    async def _disconnected_callback(self) -> None:
        """Handle NATS disconnection."""
        self._connected = False
        logger.warning("Disconnected from NATS server")

    async def _reconnected_callback(self) -> None:
        """Handle NATS reconnection."""
        self._connected = True
        logger.info("Reconnected to NATS server")

    async def _closed_callback(self) -> None:
        """Handle NATS connection closure."""
        self._connected = False
        logger.info("NATS connection closed")

    @property
    def is_connected(self) -> bool:
        """Check if client is connected."""
        return self._connected
