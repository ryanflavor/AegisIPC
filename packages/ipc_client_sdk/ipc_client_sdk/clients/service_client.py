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
    ResourceMetadata,
    ResourceRegistrationRequest,
    ResourceRegistrationResponse,
    ResourceReleaseRequest,
    ResourceReleaseResponse,
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
        heartbeat_enabled: Whether to automatically send heartbeats after registration
        heartbeat_interval: Interval between heartbeats in seconds
    """

    nats_servers: list[str] | str = "nats://localhost:4222"
    timeout: float = 5.0
    max_reconnect_attempts: int = 10
    reconnect_time_wait: int = 2
    retry_attempts: int = 3
    retry_delay: float = 0.5
    heartbeat_enabled: bool = True
    heartbeat_interval: float = 5.0


@dataclass
class ReliableDeliveryConfig:
    """Configuration for reliable message delivery.

    Attributes:
        require_ack: Whether to require acknowledgment
        ack_timeout: Timeout for acknowledgment in seconds
        max_retries: Maximum number of retry attempts
        retry_delay: Initial delay between retries in seconds
        retry_multiplier: Multiplier for exponential backoff
    """

    require_ack: bool = True
    ack_timeout: float = 30.0
    max_retries: int = 3
    retry_delay: float = 1.0
    retry_multiplier: float = 2.0


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


class ResourceConflictError(Exception):
    """Raised when resource registration conflicts occur."""

    def __init__(
        self,
        message: str,
        conflicts: dict[str, str] | None = None,
        registered: list[str] | None = None,
    ) -> None:
        """Initialize the error.

        Args:
            message: Error message
            conflicts: Dictionary of conflicting resource IDs and their owners
            registered: List of successfully registered resource IDs
        """
        super().__init__(message)
        self.conflicts = conflicts or {}
        self.registered = registered or []


class ResourceNotFoundError(Exception):
    """Raised when requested resource is not found."""

    def __init__(self, message: str, resource_id: str | None = None) -> None:
        """Initialize the error.

        Args:
            message: Error message
            resource_id: The resource ID that was not found
        """
        super().__init__(message)
        self.resource_id = resource_id


class AcknowledgmentTimeoutError(Exception):
    """Raised when acknowledgment is not received within timeout."""

    def __init__(
        self,
        message: str,
        message_id: str,
        timeout: float,
        service_name: str | None = None,
    ) -> None:
        """Initialize the error.

        Args:
            message: Error message
            message_id: The message ID that timed out
            timeout: The timeout value in seconds
            service_name: Optional service name
        """
        super().__init__(message)
        self.message_id = message_id
        self.timeout = timeout
        self.service_name = service_name


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
        config: ServiceClientConfig | None = None,
    ) -> None:
        """Initialize the service client.

        Args:
            nats_url: NATS server URL
            instance_id: Instance ID, generated if not provided
            timeout: Request timeout in seconds
            config: Optional configuration object (defaults created from other params)
        """
        # Use provided config or create from individual params
        if config:
            self._config = config
            self._nats_url = (
                config.nats_servers
                if isinstance(config.nats_servers, str)
                else config.nats_servers[0]
            )
            self._timeout = config.timeout
        else:
            # Create config from individual params for backward compatibility
            self._config = ServiceClientConfig(
                nats_servers=nats_url,
                timeout=timeout,
            )
            self._nats_url = nats_url
            self._timeout = timeout

        self._instance_id = instance_id or f"instance_{uuid.uuid4().hex[:8]}"
        self._nats_client = NATSClient(self._nats_url)
        self._registered_services: set[str] = set()
        self._heartbeat_tasks: dict[str, asyncio.Task[None]] = {}
        self._registered_resources: dict[str, set[str]] = {}  # service_name -> resource_ids
        self._heartbeat_status: dict[str, bool] = {}  # service_name -> is_heartbeat_active
        self._service_instances: dict[str, str] = {}  # service_name -> instance_id

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
        role: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ServiceRegistrationResponse:
        """Register a service instance.

        Args:
            service_name: Name of the service
            instance_id: Instance ID, uses default if not provided
            role: Service role ("active" or "standby"), defaults to "standby"
            metadata: Optional metadata for the instance

        Returns:
            ServiceRegistrationResponse with registration details

        Raises:
            RuntimeError: If not connected to NATS
            TimeoutError: If request times out
            ServiceRegistrationError: If registration fails
        """
        if not self.is_connected:
            raise RuntimeError("Not connected to NATS")

        # Use provided instance_id or default
        effective_instance_id = instance_id or self._instance_id

        # Create registration request
        request_data = {
            "service_name": service_name,
            "instance_id": effective_instance_id,
            "role": role or "standby",  # Default to standby if not specified
            "metadata": metadata or {},
        }

        # Send request
        response = await self._nats_client.request(
            "ipc.service.register", request_data, timeout=self._timeout
        )

        if response is None:
            raise TimeoutError("Registration request timed out")

        # Check for error in response
        if not response.get("success", True):
            # Check if it's a structured error response
            error_info = response.get("error", {})
            if error_info:
                error_code = error_info.get("code", "UNKNOWN")
                error_msg = error_info.get("message", "Registration failed")
                error_details = error_info.get("details", {})

                # Handle specific error codes
                if error_code == "ROLE_CONFLICT" or error_code == "DUPLICATE_INSTANCE":
                    raise ServiceRegistrationError(
                        error_msg, error_code=error_code, details=error_details
                    )
                else:
                    raise ServiceRegistrationError(
                        error_msg, error_code=error_code, details=error_details
                    )
            else:
                # Legacy error format
                error_msg = response.get("message", "Registration failed")
                raise ServiceRegistrationError(error_msg)

        # Parse response data
        data = response.get("data", {})
        self._registered_services.add(service_name)
        self._service_instances[service_name] = effective_instance_id  # Store the instance_id used

        # Start automatic heartbeat if enabled
        if self._config.heartbeat_enabled:
            try:
                await self.start_heartbeat(service_name, self._config.heartbeat_interval)
                self._heartbeat_status[service_name] = True
            except Exception:
                # Log error but don't fail registration
                # Heartbeat is optional functionality
                self._heartbeat_status[service_name] = False

        # Parse registered_at if provided
        registered_at_str = data.get("registered_at")
        registered_at = None
        if registered_at_str:
            try:
                registered_at = datetime.fromisoformat(registered_at_str)
            except (ValueError, TypeError):
                registered_at = datetime.now(UTC)
        else:
            registered_at = datetime.now(UTC)

        return ServiceRegistrationResponse(
            success=data.get("success", True),
            service_name=data.get("service_name", service_name),
            instance_id=data.get("instance_id", effective_instance_id),
            role=data.get("role", "STANDBY"),  # Default to STANDBY if not provided
            registered_at=registered_at,
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

        # Update heartbeat status
        if service_name in self._heartbeat_status:
            del self._heartbeat_status[service_name]

        # Clean up instance mapping
        if service_name in self._service_instances:
            del self._service_instances[service_name]

    async def heartbeat(self, service_name: str) -> None:
        """Send heartbeat for a registered service.

        Args:
            service_name: Name of the service

        Raises:
            ValueError: If service is not registered
        """
        if service_name not in self._registered_services:
            raise ValueError(f"Service '{service_name}' is not registered")

        # Use the instance_id that was registered for this service
        instance_id = self._service_instances.get(service_name, self._instance_id)

        payload = {
            "service_name": service_name,
            "instance_id": instance_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "status": "healthy",  # Add status field for HeartbeatRequest model
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

    def get_heartbeat_status(self, service_name: str | None = None) -> dict[str, bool]:
        """Get heartbeat status for services.

        Args:
            service_name: Optional service name to filter by

        Returns:
            Dictionary mapping service names to heartbeat status (True if active)
        """
        if service_name:
            return {service_name: self._heartbeat_status.get(service_name, False)}
        return self._heartbeat_status.copy()

    async def call(
        self,
        service_name: str,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
        trace_id: str | None = None,
        resource_id: str | None = None,
        excluded_instances: list[str] | None = None,
    ) -> Any:
        """Call a method on a service via the router.

        Args:
            service_name: Name of the target service
            method: Method to call on the service
            params: Method parameters (optional)
            timeout: Request timeout in seconds (uses default if not provided)
            trace_id: Optional trace ID for distributed tracing
            resource_id: Optional resource ID for resource-aware routing
            excluded_instances: Optional list of instance IDs to exclude from routing

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

        # Generate message ID for tracking
        message_id = str(uuid.uuid4())

        # Build request data
        request_data = {
            "service_name": service_name,
            "method": method,
            "params": params or {},
            "timeout": timeout or self._timeout,
            "trace_id": trace_id,
            "message_id": message_id,
        }

        # Add resource_id if provided
        if resource_id is not None:
            request_data["resource_id"] = resource_id

        # Add excluded_instances if provided
        if excluded_instances:
            request_data["excluded_instances"] = excluded_instances

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
                # Check if this is a resource-not-found error
                if resource_id and "resource" in error_msg.lower():
                    raise ResourceNotFoundError(error_msg, resource_id=resource_id)
                else:
                    raise ValueError(f"Service '{service_name}' not found")
            elif error_code == 503:
                raise RuntimeError(f"Service '{service_name}' unavailable: {error_msg}")
            elif error_code == 504:
                raise TimeoutError(f"Service '{service_name}' timeout: {error_msg}")
            else:
                raise Exception(f"{error_type}: {error_msg}")

        # Return the result
        return response.get("result")

    async def call_with_failover(
        self,
        service_name: str,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
        trace_id: str | None = None,
        resource_id: str | None = None,
        max_retries: int = 3,
        retry_on_codes: set[int] | None = None,
    ) -> Any:
        """Call a method on a service with instance-level failover support.

        This method automatically retries failed calls on different healthy instances
        when the failure is due to instance-specific issues (503, 504 errors).

        Args:
            service_name: Name of the target service
            method: Method to call on the service
            params: Method parameters (optional)
            timeout: Request timeout in seconds (uses default if not provided)
            trace_id: Optional trace ID for distributed tracing
            resource_id: Optional resource ID for resource-aware routing
            max_retries: Maximum number of different instances to try (default: 3)
            retry_on_codes: Set of error codes to retry on (default: {503, 504})

        Returns:
            The result from the method call

        Raises:
            RuntimeError: If not connected to NATS
            TimeoutError: If all retry attempts timeout
            Exception: If the service call fails on all instances
        """
        if retry_on_codes is None:
            retry_on_codes = {503, 504}  # Service unavailable and gateway timeout

        excluded_instances: list[str] = []
        last_error: Exception | None = None

        for attempt in range(max_retries):
            try:
                # Call with excluded instances from previous failures
                return await self.call(
                    service_name=service_name,
                    method=method,
                    params=params,
                    timeout=timeout,
                    trace_id=trace_id,
                    resource_id=resource_id,
                    excluded_instances=excluded_instances if excluded_instances else None,
                )
            except (RuntimeError, TimeoutError) as e:
                last_error = e
                # Extract instance_id from error if available
                # For now, we'll retry on these errors
                if attempt < max_retries - 1:
                    # Get instance_id from response if available
                    # Since we don't have access to the raw response in exceptions,
                    # we'll need to enhance error handling in the future
                    continue
                raise
            except Exception as e:
                last_error = e
                # Check if error is retryable
                error_code = getattr(e, "code", None)
                if error_code in retry_on_codes and attempt < max_retries - 1:
                    continue
                raise

        # Should not reach here, but just in case
        if last_error:
            raise last_error
        raise Exception(f"Failed to call {service_name}.{method} after {max_retries} attempts")

    async def call_reliable(
        self,
        service_name: str,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
        trace_id: str | None = None,
        resource_id: str | None = None,
        delivery_config: ReliableDeliveryConfig | None = None,
    ) -> Any:
        """Call a method on a service with reliable delivery guarantees.

        This method ensures at-least-once delivery with acknowledgment tracking.
        It will automatically retry on failures and wait for acknowledgments.

        Args:
            service_name: Name of the target service
            method: Method to call on the service
            params: Method parameters (optional)
            timeout: Request timeout in seconds (uses default if not provided)
            trace_id: Optional trace ID for distributed tracing
            resource_id: Optional resource ID for resource-aware routing
            delivery_config: Optional reliable delivery configuration

        Returns:
            The result from the method call

        Raises:
            RuntimeError: If not connected to NATS
            TimeoutError: If request times out
            AcknowledgmentTimeoutError: If acknowledgment not received
            Exception: If the service call fails after all retries
        """
        if not self.is_connected:
            raise RuntimeError("Not connected to NATS")

        # Use provided config or default
        config = delivery_config or ReliableDeliveryConfig()

        # Generate trace ID if not provided
        if trace_id is None:
            trace_id = f"trace_{uuid.uuid4().hex[:16]}"

        # Track the last error for retry logic
        last_error = None
        current_delay = config.retry_delay

        for attempt in range(config.max_retries + 1):
            try:
                # Generate message ID for tracking
                message_id = str(uuid.uuid4())

                # Build request data with reliable delivery flags
                request_data = {
                    "service_name": service_name,
                    "method": method,
                    "params": params or {},
                    "timeout": timeout or self._timeout,
                    "trace_id": trace_id,
                    "message_id": message_id,
                    "require_ack": config.require_ack,
                }

                # Add resource_id if provided
                if resource_id is not None:
                    request_data["resource_id"] = resource_id

                # Send request to router with acknowledgment support
                if config.require_ack:
                    response = await self._request_with_ack(
                        subject="ipc.route.request",
                        data=request_data,
                        message_id=message_id,
                        timeout=timeout or self._timeout,
                        ack_timeout=config.ack_timeout,
                    )
                else:
                    # Standard request without acknowledgment
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
                        # Check if this is a resource-not-found error
                        if resource_id and "resource" in error_msg.lower():
                            raise ResourceNotFoundError(error_msg, resource_id=resource_id)
                        else:
                            raise ValueError(f"Service '{service_name}' not found")
                    elif error_code == 503:
                        raise RuntimeError(f"Service '{service_name}' unavailable: {error_msg}")
                    elif error_code == 504:
                        raise TimeoutError(f"Service '{service_name}' timeout: {error_msg}")
                    else:
                        raise Exception(f"{error_type}: {error_msg}")

                # Return the result
                return response.get("result")

            except (TimeoutError, AcknowledgmentTimeoutError) as e:
                last_error = e
                if attempt < config.max_retries:
                    # Wait before retry with exponential backoff
                    await asyncio.sleep(current_delay)
                    current_delay *= config.retry_multiplier
                    continue
                raise

            except Exception:
                # Don't retry on non-timeout errors
                raise

        # Should not reach here, but just in case
        raise last_error or Exception("Service call failed after all retries")

    async def _request_with_ack(
        self,
        subject: str,
        data: dict[str, Any],
        message_id: str,
        timeout: float,
        ack_timeout: float,
    ) -> dict[str, Any] | None:
        """Send request and wait for acknowledgment.

        Args:
            subject: NATS subject
            data: Request data
            message_id: Unique message identifier
            timeout: Request timeout
            ack_timeout: Acknowledgment timeout

        Returns:
            Response data or None

        Raises:
            AcknowledgmentTimeoutError: If acknowledgment not received
        """
        # Create acknowledgment subject for this message
        ack_subject = f"ipc.ack.{message_id}"
        ack_received = asyncio.Event()
        ack_error: Exception | None = None

        async def ack_handler(msg: Any) -> None:
            """Handle acknowledgment messages."""
            nonlocal ack_error
            try:
                ack_data = msgpack.unpackb(msg.data, raw=False)
                if ack_data.get("status") == "success":
                    # Success acknowledgment
                    pass
                else:
                    error_msg = ack_data.get("error_message", "Unknown error")
                    ack_error = Exception(f"Acknowledgment failed: {error_msg}")
            finally:
                ack_received.set()

        # Subscribe to acknowledgment subject temporarily
        if not self._nats_client._nc:
            raise RuntimeError("Not connected to NATS")

        subscription = await self._nats_client._nc.subscribe(ack_subject, cb=ack_handler)

        try:
            # Send the request
            response = await self._nats_client.request(subject, data, timeout=timeout)

            # Wait for acknowledgment
            try:
                await asyncio.wait_for(ack_received.wait(), timeout=ack_timeout)
                if ack_error:
                    raise ack_error
            except TimeoutError as e:
                raise AcknowledgmentTimeoutError(
                    f"Acknowledgment timeout for message {message_id}",
                    message_id=message_id,
                    timeout=ack_timeout,
                    service_name=data.get("service_name"),
                ) from e

            return response

        finally:
            # Clean up subscription
            await subscription.unsubscribe()

    async def send_acknowledgment(
        self,
        message_id: str,
        service_name: str,
        status: str,
        error_message: str | None = None,
        processing_time_ms: float | None = None,
    ) -> None:
        """Send acknowledgment for a received message.

        This method is used by service implementations to acknowledge
        successful or failed message processing.

        Args:
            message_id: The message ID to acknowledge
            service_name: Name of the acknowledging service
            status: Status ("success" or "failure")
            error_message: Optional error message for failures
            processing_time_ms: Optional processing time in milliseconds
        """
        if not self.is_connected:
            raise RuntimeError("Not connected to NATS")

        # Create acknowledgment data
        ack_data = {
            "message_id": message_id,
            "service_name": service_name,
            "instance_id": self._instance_id,
            "status": status,
            "error_message": error_message,
            "processing_time_ms": processing_time_ms or 0.0,
            "trace_id": f"ack_{uuid.uuid4().hex[:16]}",
        }

        # Publish acknowledgment
        ack_subject = f"ipc.ack.{message_id}"
        await self._nats_client.publish(ack_subject, ack_data)

    async def query_message_status(
        self,
        message_id: str,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Query the status of a message.

        Args:
            message_id: The message ID to query
            timeout: Request timeout

        Returns:
            Message status information

        Raises:
            RuntimeError: If not connected to NATS
            TimeoutError: If request times out
        """
        if not self.is_connected:
            raise RuntimeError("Not connected to NATS")

        # Create status query request
        request_data = {
            "message_id": message_id,
            "trace_id": f"status_{uuid.uuid4().hex[:16]}",
        }

        # Send request
        response = await self._nats_client.request(
            "ipc.message.status",
            request_data,
            timeout=timeout or self._timeout,
        )

        if response is None:
            raise TimeoutError(f"Message status query timed out for {message_id}")

        return response

    async def register_resource(
        self,
        service_name: str,
        resource_ids: list[str],
        metadata: dict[str, ResourceMetadata] | None = None,
        force: bool = False,
        instance_id: str | None = None,
    ) -> ResourceRegistrationResponse:
        """Register resources for a service instance.

        Args:
            service_name: Name of the service
            resource_ids: List of resource IDs to register
            metadata: Optional metadata for each resource ID
            force: Force override existing registrations
            instance_id: Instance ID, uses default if not provided

        Returns:
            ResourceRegistrationResponse with registration details

        Raises:
            RuntimeError: If not connected to NATS
            TimeoutError: If request times out
            ValueError: If validation fails
        """
        if not self.is_connected:
            raise RuntimeError("Not connected to NATS")

        # Use provided instance_id or default
        effective_instance_id = instance_id or self._instance_id

        # Generate trace ID
        trace_id = f"trace_{uuid.uuid4().hex[:16]}"

        # Create registration request
        request = ResourceRegistrationRequest(
            service_name=service_name,
            instance_id=effective_instance_id,
            resource_ids=resource_ids,
            force=force,
            metadata=metadata or {},
            trace_id=trace_id,
        )

        # Send request
        response = await self._nats_client.request(
            "ipc.resource.register",
            request.model_dump(),
            timeout=self._timeout,
        )

        if response is None:
            raise TimeoutError("Resource registration request timed out")

        # Check for complete failure error
        if (
            not response.get("success", False)
            and "error" in response
            and "registered" not in response
        ):
            # This is a complete failure with no partial success
            error = response.get("error", {})
            error_code = error.get("code", "UNKNOWN_ERROR")
            error_msg = error.get("message", "Resource registration failed")

            if error_code == "VALIDATION_ERROR":
                raise ValueError(f"Validation error: {error_msg}")
            else:
                raise Exception(f"Resource registration failed: {error_msg}")

        # Parse response (may have partial success with conflicts)
        result = ResourceRegistrationResponse(**response)

        # Track registered resources
        if result.registered:
            if service_name not in self._registered_resources:
                self._registered_resources[service_name] = set()
            self._registered_resources[service_name].update(result.registered)

        # Check for conflicts
        if result.conflicts:
            raise ResourceConflictError(
                f"Resource conflicts detected: {len(result.conflicts)} resources already registered",
                conflicts=result.conflicts,
                registered=result.registered,
            )

        return result

    async def release_resource(
        self,
        service_name: str,
        resource_ids: list[str],
        instance_id: str | None = None,
    ) -> ResourceReleaseResponse:
        """Release resources for a service instance.

        Args:
            service_name: Name of the service
            resource_ids: List of resource IDs to release
            instance_id: Instance ID, uses default if not provided

        Returns:
            ResourceReleaseResponse with release details

        Raises:
            RuntimeError: If not connected to NATS
            TimeoutError: If request times out
            ValueError: If validation fails
        """
        if not self.is_connected:
            raise RuntimeError("Not connected to NATS")

        # Use provided instance_id or default
        effective_instance_id = instance_id or self._instance_id

        # Generate trace ID
        trace_id = f"trace_{uuid.uuid4().hex[:16]}"

        # Create release request
        request = ResourceReleaseRequest(
            service_name=service_name,
            instance_id=effective_instance_id,
            resource_ids=resource_ids,
            trace_id=trace_id,
        )

        # Send request
        response = await self._nats_client.request(
            "ipc.resource.release",
            request.model_dump(),
            timeout=self._timeout,
        )

        if response is None:
            raise TimeoutError("Resource release request timed out")

        # Parse response first
        result = ResourceReleaseResponse(**response)

        # Check for error in response - but allow partial success
        if not response.get("success", False) and not result.released:
            # Only raise error if no resources were released
            error = response.get("error", {})
            error_code = error.get("code", "UNKNOWN_ERROR")
            error_msg = error.get("message", "Resource release failed")

            if error_code == "VALIDATION_ERROR":
                raise ValueError(f"Validation error: {error_msg}")
            else:
                raise Exception(f"Resource release failed: {error_msg}")

        # Update tracked resources
        if service_name in self._registered_resources:
            self._registered_resources[service_name].difference_update(result.released)
            if not self._registered_resources[service_name]:
                del self._registered_resources[service_name]

        return result

    def get_registered_resources(self, service_name: str | None = None) -> dict[str, set[str]]:
        """Get registered resources.

        Args:
            service_name: Optional service name to filter by

        Returns:
            Dictionary mapping service names to sets of resource IDs
        """
        if service_name:
            return {service_name: self._registered_resources.get(service_name, set())}
        return self._registered_resources.copy()

    async def bulk_register_resource(
        self,
        service_name: str,
        resources: list[tuple[str, ResourceMetadata]],
        batch_size: int = 100,
        continue_on_error: bool = False,
        force: bool = False,
        instance_id: str | None = None,
        progress_callback: Any | None = None,
    ) -> Any:
        """Bulk register resources for a service instance.

        Args:
            service_name: Name of the service
            resources: List of (resource_id, metadata) tuples
            batch_size: Number of resources per batch (default: 100)
            continue_on_error: Continue processing on errors
            force: Force override existing registrations
            instance_id: Instance ID, uses default if not provided
            progress_callback: Optional async callback for progress updates

        Returns:
            BulkResourceRegistrationResponse with registration details

        Raises:
            RuntimeError: If not connected to NATS
            TimeoutError: If request times out
            ValueError: If validation fails
        """
        if not self.is_connected:
            raise RuntimeError("Not connected to NATS")

        # Import models locally to avoid circular imports
        from ipc_client_sdk.models import (
            BulkResourceRegistrationRequest,
            BulkResourceRegistrationResponse,
            ResourceRegistrationItem,
        )

        # Use provided instance_id or default
        effective_instance_id = instance_id or self._instance_id

        # Generate trace ID
        trace_id = f"trace_{uuid.uuid4().hex[:16]}"

        # Convert resources to ResourceRegistrationItem objects
        resource_items = [
            ResourceRegistrationItem(
                resource_id=resource_id,
                metadata=metadata,
                force=force,
            )
            for resource_id, metadata in resources
        ]

        # Create bulk registration request
        request = BulkResourceRegistrationRequest(
            service_name=service_name,
            instance_id=effective_instance_id,
            resources=resource_items,
            batch_size=batch_size,
            continue_on_error=continue_on_error,
            trace_id=trace_id,
        )

        # Send request with extended timeout for bulk operations
        timeout = max(self._timeout * 3, 30.0)  # At least 30 seconds for bulk ops
        response = await self._nats_client.request(
            "ipc.resource.bulk_register",
            request.model_dump(),
            timeout=timeout,
        )

        if response is None:
            raise TimeoutError("Bulk resource registration request timed out")

        # Check for error in response
        if not response.get("success", False):
            error = response.get("error", {})
            error_code = error.get("code", "UNKNOWN_ERROR")
            error_msg = error.get("message", "Bulk resource registration failed")

            if error_code == "VALIDATION_ERROR":
                raise ValueError(f"Validation error: {error_msg}")
            else:
                raise Exception(f"Bulk resource registration failed: {error_msg}")

        # Parse response
        result = BulkResourceRegistrationResponse(**response)

        # Track registered resources
        if result.registered:
            if service_name not in self._registered_resources:
                self._registered_resources[service_name] = set()
            self._registered_resources[service_name].update(result.registered)

        # Notify progress callback if provided
        if progress_callback:
            await progress_callback(result)

        return result

    async def bulk_release_resource(
        self,
        service_name: str,
        resource_ids: list[str],
        batch_size: int = 100,
        continue_on_error: bool = False,
        transactional: bool = True,
        instance_id: str | None = None,
        progress_callback: Any | None = None,
    ) -> Any:
        """Bulk release resources for a service instance.

        Args:
            service_name: Name of the service
            resource_ids: List of resource IDs to release
            batch_size: Number of resources per batch (default: 100)
            continue_on_error: Continue processing on errors
            transactional: Use transactional processing with rollback
            instance_id: Instance ID, uses default if not provided
            progress_callback: Optional async callback for progress updates

        Returns:
            BulkResourceReleaseResponse with release details

        Raises:
            RuntimeError: If not connected to NATS
            TimeoutError: If request times out
            ValueError: If validation fails
        """
        if not self.is_connected:
            raise RuntimeError("Not connected to NATS")

        # Import models locally to avoid circular imports
        from ipc_client_sdk.models import (
            BulkResourceReleaseRequest,
            BulkResourceReleaseResponse,
        )

        # Use provided instance_id or default
        effective_instance_id = instance_id or self._instance_id

        # Generate trace ID
        trace_id = f"trace_{uuid.uuid4().hex[:16]}"

        # Create bulk release request
        request = BulkResourceReleaseRequest(
            service_name=service_name,
            instance_id=effective_instance_id,
            resource_ids=resource_ids,
            batch_size=batch_size,
            continue_on_error=continue_on_error,
            transactional=transactional,
            trace_id=trace_id,
        )

        # Send request with extended timeout for bulk operations
        timeout = max(self._timeout * 3, 30.0)  # At least 30 seconds for bulk ops
        response = await self._nats_client.request(
            "ipc.resource.bulk_release",
            request.model_dump(),
            timeout=timeout,
        )

        if response is None:
            raise TimeoutError("Bulk resource release request timed out")

        # Check for error in response
        if not response.get("success", False):
            error = response.get("error", {})
            error_code = error.get("code", "UNKNOWN_ERROR")
            error_msg = error.get("message", "Bulk resource release failed")

            if error_code == "VALIDATION_ERROR":
                raise ValueError(f"Validation error: {error_msg}")
            else:
                raise Exception(f"Bulk resource release failed: {error_msg}")

        # Parse response
        result = BulkResourceReleaseResponse(**response)

        # Update tracked resources
        if service_name in self._registered_resources:
            self._registered_resources[service_name].difference_update(result.released)
            if not self._registered_resources[service_name]:
                del self._registered_resources[service_name]

        # Notify progress callback if provided
        if progress_callback:
            await progress_callback(result)

        return result

    async def transfer_resource(
        self,
        service_name: str,
        resource_ids: list[str],
        to_instance_id: str,
        from_instance_id: str | None = None,
        verify_ownership: bool = True,
        reason: str = "Manual transfer",
    ) -> Any:
        """Transfer resource ownership between instances.

        Args:
            service_name: Name of the service
            resource_ids: List of resource IDs to transfer
            to_instance_id: Target instance ID
            from_instance_id: Current owner instance ID (uses default if not provided)
            verify_ownership: Verify the sender owns the resources
            reason: Transfer reason for audit trail

        Returns:
            ResourceTransferResponse with transfer details

        Raises:
            RuntimeError: If not connected to NATS
            TimeoutError: If request times out
            ValueError: If validation fails
        """
        if not self.is_connected:
            raise RuntimeError("Not connected to NATS")

        # Import models locally to avoid circular imports
        from ipc_client_sdk.models import (
            ResourceTransferRequest,
            ResourceTransferResponse,
        )

        # Use provided from_instance_id or default
        effective_from_instance_id = from_instance_id or self._instance_id

        # Generate trace ID
        trace_id = f"trace_{uuid.uuid4().hex[:16]}"

        # Create transfer request
        request = ResourceTransferRequest(
            service_name=service_name,
            resource_ids=resource_ids,
            from_instance_id=effective_from_instance_id,
            to_instance_id=to_instance_id,
            verify_ownership=verify_ownership,
            reason=reason,
            trace_id=trace_id,
        )

        # Send request
        response = await self._nats_client.request(
            "ipc.resource.transfer",
            request.model_dump(),
            timeout=self._timeout,
        )

        if response is None:
            raise TimeoutError("Resource transfer request timed out")

        # Check for error in response
        if not response.get("success", False):
            error = response.get("error", {})
            error_code = error.get("code", "UNKNOWN_ERROR")
            error_msg = error.get("message", "Resource transfer failed")

            if error_code == "VALIDATION_ERROR":
                raise ValueError(f"Validation error: {error_msg}")
            elif error_code == "FORBIDDEN":
                raise PermissionError(f"Permission denied: {error_msg}")
            else:
                raise Exception(f"Resource transfer failed: {error_msg}")

        # Parse response
        result = ResourceTransferResponse(**response)

        # Update tracked resources if transfer was from this instance
        if (
            effective_from_instance_id == self._instance_id
            and service_name in self._registered_resources
        ):
            self._registered_resources[service_name].difference_update(result.transferred)
            if not self._registered_resources[service_name]:
                del self._registered_resources[service_name]

        return result

    async def bulk_register_with_retry(
        self,
        service_name: str,
        resources: list[tuple[str, ResourceMetadata]],
        batch_size: int = 100,
        continue_on_error: bool = False,
        force: bool = False,
        instance_id: str | None = None,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        retry_multiplier: float = 2.0,
        progress_callback: Any | None = None,
    ) -> Any:
        """Bulk register resources with automatic retry on failure.

        Args:
            service_name: Name of the service
            resources: List of (resource_id, metadata) tuples
            batch_size: Number of resources per batch
            continue_on_error: Continue processing on errors
            force: Force override existing registrations
            instance_id: Instance ID, uses default if not provided
            max_retries: Maximum number of retry attempts
            retry_delay: Initial delay between retries in seconds
            retry_multiplier: Multiplier for exponential backoff
            progress_callback: Optional async callback for progress updates

        Returns:
            BulkResourceRegistrationResponse with registration details

        Raises:
            RuntimeError: If not connected to NATS
            TimeoutError: If all retry attempts fail
            ValueError: If validation fails
        """
        last_error = None
        current_delay = retry_delay

        for attempt in range(max_retries + 1):
            try:
                return await self.bulk_register_resource(
                    service_name=service_name,
                    resources=resources,
                    batch_size=batch_size,
                    continue_on_error=continue_on_error,
                    force=force,
                    instance_id=instance_id,
                    progress_callback=progress_callback,
                )
            except (TimeoutError, Exception) as e:
                last_error = e
                if attempt < max_retries:
                    await asyncio.sleep(current_delay)
                    current_delay *= retry_multiplier
                    continue
                raise

        raise last_error or Exception("Bulk registration failed after all retries")
