"""Service registration client for IPC SDK."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import msgpack
import nats
from nats.aio.client import Client as NATSConnection

from ipc_client_sdk.models import (
    ServiceRegistrationResponse,
)


@dataclass
class ServiceClientConfig:
    """Configuration for ServiceClient.

    Attributes:
        nats_servers: NATS server URLs
        timeout: Request timeout in seconds
        max_reconnect_attempts: Maximum reconnection attempts
        reconnect_time_wait: Time to wait between reconnections
        retry_attempts: Number of retry attempts for registration
        retry_delay: Initial delay between retries in seconds
    """

    nats_servers: list[str] | str = "nats://localhost:4222"
    timeout: float = 5.0
    max_reconnect_attempts: int = 10
    reconnect_time_wait: int = 2
    retry_attempts: int = 3
    retry_delay: float = 0.5


class ServiceRegistrationError(Exception):
    """Raised when service registration fails."""

    def __init__(
        self, message: str, error_code: str | None = None, details: dict[str, Any] | None = None
    ) -> None:
        """Initialize the error.

        Args:
            message: Error message
            error_code: Optional error code
            details: Optional error details
        """
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


class NATSClient:
    """NATS client wrapper for testing purposes."""

    def __init__(self, nats_url: str) -> None:
        """Initialize NATS client.

        Args:
            nats_url: NATS server URL
        """
        self.nats_url = nats_url
        self._nc: NATSConnection | None = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        """Check if connected to NATS."""
        return self._connected and self._nc is not None

    async def connect(self) -> None:
        """Connect to NATS server."""
        if self._connected:
            return

        try:
            self._nc = await nats.connect(servers=[self.nats_url])
            self._connected = True
        except Exception as e:
            raise ServiceRegistrationError(f"Failed to connect to NATS: {e}") from e

    async def disconnect(self) -> None:
        """Disconnect from NATS server."""
        if self._nc and self._connected:
            await self._nc.close()
            self._connected = False

    async def request(
        self, subject: str, payload: dict[str, Any], timeout: float = 5.0
    ) -> dict[str, Any] | None:
        """Send request and wait for response.

        Args:
            subject: NATS subject
            payload: Request payload
            timeout: Request timeout

        Returns:
            Response data or None on timeout
        """
        if not self._nc:
            raise ServiceRegistrationError("Not connected to NATS")

        try:
            request_data = msgpack.packb(payload, use_bin_type=True)
            response_msg = await self._nc.request(subject, request_data, timeout=timeout)
            result = msgpack.unpackb(response_msg.data, raw=False)
            return result if isinstance(result, dict) else {"data": result}
        except TimeoutError:
            return None

    async def publish(self, subject: str, payload: dict[str, Any]) -> None:
        """Publish message to subject.

        Args:
            subject: NATS subject
            payload: Message payload
        """
        if not self._nc:
            raise ServiceRegistrationError("Not connected to NATS")

        data = msgpack.packb(payload, use_bin_type=True)
        await self._nc.publish(subject, data)


class ServiceClient:
    """Client for service registration and discovery.

    This client provides a simple interface for services to register
    themselves with the IPC router.
    """

    def __init__(
        self,
        nats_url: str = "nats://localhost:4222",
        instance_id: str | None = None,
        timeout: float = 5.0,
    ) -> None:
        """Initialize the service client.

        Args:
            nats_url: NATS server URL
            instance_id: Instance ID, generated if not provided
            timeout: Request timeout in seconds
        """
        self._nats_url = nats_url
        self._instance_id = instance_id or f"instance_{uuid.uuid4().hex[:8]}"
        self._timeout = timeout
        self._nats_client = NATSClient(nats_url)
        self._registered_services: set[str] = set()
        self._heartbeat_tasks: dict[str, asyncio.Task[None]] = {}

    @property
    def is_connected(self) -> bool:
        """Check if connected to NATS."""
        return self._nats_client.is_connected

    async def __aenter__(self) -> ServiceClient:
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.disconnect()

    async def connect(self) -> None:
        """Connect to NATS server."""
        await self._nats_client.connect()

    async def disconnect(self) -> None:
        """Disconnect from NATS server."""
        # Cancel all heartbeat tasks
        for task in self._heartbeat_tasks.values():
            task.cancel()

        # Wait for tasks to complete
        if self._heartbeat_tasks:
            await asyncio.gather(*self._heartbeat_tasks.values(), return_exceptions=True)
            self._heartbeat_tasks.clear()

        await self._nats_client.disconnect()

    async def register(
        self,
        service_name: str,
        instance_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ServiceRegistrationResponse:
        """Register a service instance.

        Args:
            service_name: Name of the service
            instance_id: Instance ID, uses default if not provided
            metadata: Optional metadata for the instance

        Returns:
            ServiceRegistrationResponse with registration details

        Raises:
            RuntimeError: If not connected to NATS
            TimeoutError: If request times out
        """
        if not self.is_connected:
            raise RuntimeError("Not connected to NATS")

        # Use provided instance_id or default
        effective_instance_id = instance_id or self._instance_id

        # Create registration request
        request_data = {
            "service_name": service_name,
            "instance_id": effective_instance_id,
            "metadata": metadata or {},
        }

        # Send request
        response = await self._nats_client.request(
            "ipc.service.register", request_data, timeout=self._timeout
        )

        if response is None:
            raise TimeoutError("Registration request timed out")

        # Check for error in envelope
        envelope = response.get("envelope", {})
        if not envelope.get("success", True):
            error_msg = envelope.get("message", "Registration failed")
            raise Exception(error_msg)

        # Parse response data
        data = response.get("data", {})
        self._registered_services.add(service_name)

        return ServiceRegistrationResponse(
            success=data.get("success", True),
            service_name=data.get("service_name", service_name),
            instance_id=data.get("instance_id", effective_instance_id),
            registered_at=data.get("registered_at"),
            message=data.get("message", ""),
        )

    async def unregister(self, service_name: str) -> None:
        """Unregister a service instance.

        Args:
            service_name: Name of the service to unregister

        Raises:
            ValueError: If service is not registered
        """
        if service_name not in self._registered_services:
            raise ValueError(f"Service '{service_name}' is not registered")

        # Send unregister request
        request_data = {
            "service_name": service_name,
            "instance_id": self._instance_id,
        }

        await self._nats_client.request(
            "ipc.service.unregister", request_data, timeout=self._timeout
        )

        # Remove from registered services
        self._registered_services.discard(service_name)

        # Cancel heartbeat task if running
        if service_name in self._heartbeat_tasks:
            self._heartbeat_tasks[service_name].cancel()
            del self._heartbeat_tasks[service_name]

    async def heartbeat(self, service_name: str) -> None:
        """Send heartbeat for a registered service.

        Args:
            service_name: Name of the service

        Raises:
            ValueError: If service is not registered
        """
        if service_name not in self._registered_services:
            raise ValueError(f"Service '{service_name}' is not registered")

        payload = {
            "service_name": service_name,
            "instance_id": self._instance_id,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        await self._nats_client.publish("ipc.service.heartbeat", payload)

    async def start_heartbeat(
        self, service_name: str, interval: float = 30.0
    ) -> asyncio.Task[None]:
        """Start background heartbeat task for a service.

        Args:
            service_name: Name of the service
            interval: Heartbeat interval in seconds

        Returns:
            The background task

        Raises:
            ValueError: If service is not registered
        """
        if service_name not in self._registered_services:
            raise ValueError(f"Service '{service_name}' is not registered")

        async def heartbeat_loop() -> None:
            try:
                while True:
                    await self.heartbeat(service_name)
                    await asyncio.sleep(interval)
            except asyncio.CancelledError:
                pass

        task = asyncio.create_task(heartbeat_loop())
        self._heartbeat_tasks[service_name] = task
        return task

    async def call(
        self,
        service_name: str,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
        trace_id: str | None = None,
    ) -> Any:
        """Call a method on a service via the router.

        Args:
            service_name: Name of the target service
            method: Method to call on the service
            params: Method parameters (optional)
            timeout: Request timeout in seconds (uses default if not provided)
            trace_id: Optional trace ID for distributed tracing

        Returns:
            The result from the method call

        Raises:
            RuntimeError: If not connected to NATS
            TimeoutError: If request times out
            Exception: If the service call fails
        """
        if not self.is_connected:
            raise RuntimeError("Not connected to NATS")

        # Generate trace ID if not provided
        if trace_id is None:
            trace_id = f"trace_{uuid.uuid4().hex[:16]}"

        # Build request data
        request_data = {
            "service_name": service_name,
            "method": method,
            "params": params or {},
            "timeout": timeout or self._timeout,
            "trace_id": trace_id,
        }

        # Send request to router
        response = await self._nats_client.request(
            "ipc.route.request",
            request_data,
            timeout=timeout or self._timeout,
        )

        if response is None:
            raise TimeoutError(f"Service call to '{service_name}.{method}' timed out")

        # Check if routing was successful
        if not response.get("success", False):
            error = response.get("error", {})
            error_type = error.get("type", "UnknownError")
            error_msg = error.get("message", f"Call to '{service_name}.{method}' failed")
            error_code = error.get("code", 500)

            # Create appropriate exception based on error code
            if error_code == 404:
                raise ValueError(f"Service '{service_name}' not found")
            elif error_code == 503:
                raise RuntimeError(f"Service '{service_name}' unavailable: {error_msg}")
            elif error_code == 504:
                raise TimeoutError(f"Service '{service_name}' timeout: {error_msg}")
            else:
                raise Exception(f"{error_type}: {error_msg}")

        # Return the result
        return response.get("result")
