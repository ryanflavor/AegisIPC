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
from nats.js import JetStreamContext
from nats.js.api import RetentionPolicy, StreamConfig

from ipc_router.domain.exceptions import (
    ConnectionError as IPCConnectionError,
)
from ipc_router.infrastructure.logging import get_logger

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
        self._js: JetStreamContext | None = None
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

            # Initialize JetStream
            await self._initialize_jetstream()
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
        self._js = None
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

    async def request_with_ack(
        self,
        subject: str,
        data: Any,
        message_id: str,
        timeout: float = 30.0,
        ack_timeout: float = 30.0,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """Send a request and wait for acknowledgment.

        This method sends a request and waits for both the response and an acknowledgment.
        It's designed for reliable message delivery where the receiver must confirm
        successful processing.

        Args:
            subject: Subject to send request to
            data: Request data (will be serialized with MessagePack)
            message_id: Unique message identifier for tracking
            timeout: Initial request timeout in seconds
            ack_timeout: Acknowledgment wait timeout in seconds
            headers: Optional headers

        Returns:
            Deserialized response data

        Raises:
            asyncio.TimeoutError: If request times out
            AcknowledgmentTimeoutError: If acknowledgment not received within timeout
        """
        if not self._connected or not self._nc:
            raise IPCConnectionError(
                service="NATS",
                endpoint=str(self.servers),
                reason="Not connected",
            )

        # Add message_id to headers for tracking
        if headers is None:
            headers = {}
        headers["X-Message-ID"] = message_id
        headers["X-Requires-Ack"] = "true"

        # Create acknowledgment subject for this message
        ack_subject = f"ipc.ack.{message_id}"
        ack_received = asyncio.Event()
        ack_error: Exception | None = None

        async def ack_handler(ack_data: Any, _reply: str | None) -> None:
            """Handle acknowledgment messages."""
            nonlocal ack_error
            try:
                if ack_data.get("status") == "success":
                    logger.debug(
                        "Received acknowledgment",
                        extra={
                            "message_id": message_id,
                            "processing_time_ms": ack_data.get("processing_time_ms"),
                        },
                    )
                else:
                    error_msg = ack_data.get("error_message", "Unknown error")
                    ack_error = Exception(f"Acknowledgment failed: {error_msg}")
                    logger.error(
                        "Received failure acknowledgment",
                        extra={
                            "message_id": message_id,
                            "error": error_msg,
                        },
                    )
            finally:
                ack_received.set()

        # Subscribe to acknowledgment subject temporarily
        await self.subscribe(ack_subject, ack_handler)

        try:
            # Send the request
            response_data = await self.request(
                subject=subject,
                data=data,
                timeout=timeout,
                headers=headers,
            )

            # Wait for acknowledgment
            try:
                await asyncio.wait_for(ack_received.wait(), timeout=ack_timeout)
                if ack_error:
                    raise ack_error
            except TimeoutError as e:
                from ipc_router.domain.exceptions import AcknowledgmentTimeoutError

                logger.error(
                    "Acknowledgment timeout",
                    extra={
                        "message_id": message_id,
                        "subject": subject,
                        "timeout": ack_timeout,
                    },
                )
                raise AcknowledgmentTimeoutError(
                    message_id=message_id,
                    timeout=ack_timeout,
                    service_name=subject,
                ) from e

            return response_data

        finally:
            # Clean up acknowledgment subscription
            await self.unsubscribe(ack_subject)

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

    async def unsubscribe(self, subject: str) -> None:
        """Unsubscribe from a subject.

        Args:
            subject: Subject to unsubscribe from
        """
        if subject in self._subscriptions:
            task = self._subscriptions[subject]
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            del self._subscriptions[subject]
            logger.info(
                "Unsubscribed from subject",
                extra={"subject": subject},
            )
        else:
            logger.warning(
                "Attempted to unsubscribe from unknown subject",
                extra={"subject": subject},
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

    async def _initialize_jetstream(self) -> None:
        """Initialize JetStream context and create necessary streams."""
        if not self._nc:
            return

        try:
            # Create JetStream context
            self._js = self._nc.jetstream()

            # Create stream for reliable message delivery
            stream_name = "IPC_MESSAGES"
            stream_config = StreamConfig(
                name=stream_name,
                subjects=["ipc.messages.*", "ipc.ack.*"],
                retention=RetentionPolicy.WORK_QUEUE,
                max_age=3600,  # 1 hour retention
                max_msgs=100000,
                duplicate_window=300,  # 5 minute duplicate window
                description="Stream for IPC reliable message delivery",
            )

            try:
                # Try to create the stream
                await self._js.add_stream(stream_config)
                logger.info(
                    "Created JetStream stream",
                    extra={"stream_name": stream_name},
                )
            except Exception:
                # Stream might already exist, try to update it
                try:
                    await self._js.update_stream(stream_config)
                    logger.info(
                        "Updated JetStream stream",
                        extra={"stream_name": stream_name},
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to create/update stream",
                        exc_info=e,
                        extra={"stream_name": stream_name},
                    )

        except Exception as e:
            logger.error(
                "Failed to initialize JetStream",
                exc_info=e,
            )
            # JetStream is optional, so we don't raise

    async def publish_with_jetstream(
        self,
        subject: str,
        data: Any,
        message_id: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Publish a message using JetStream for persistence.

        Args:
            subject: Subject to publish to
            data: Data to publish (will be serialized with MessagePack)
            message_id: Unique message identifier
            headers: Optional headers
        """
        if not self._js:
            # Fallback to regular publish if JetStream not available
            await self.publish(subject, data, headers=headers)
            return

        try:
            # Serialize data with MessagePack
            payload = msgpack.packb(data, use_bin_type=True)

            # Add message ID to headers for deduplication
            if headers is None:
                headers = {}
            headers["Nats-Msg-Id"] = message_id

            # Publish via JetStream
            ack = await self._js.publish(
                subject=subject,
                payload=payload,
                headers=headers,
            )

            logger.debug(
                "Published message via JetStream",
                extra={
                    "subject": subject,
                    "message_id": message_id,
                    "stream": ack.stream,
                    "seq": ack.seq,
                },
            )

        except Exception as e:
            logger.error(
                "Failed to publish via JetStream",
                exc_info=e,
                extra={
                    "subject": subject,
                    "message_id": message_id,
                },
            )
            raise

    @property
    def is_connected(self) -> bool:
        """Check if client is connected."""
        return self._connected

    @property
    def has_jetstream(self) -> bool:
        """Check if JetStream is available."""
        return self._js is not None
