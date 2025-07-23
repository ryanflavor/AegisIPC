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
        self._registered_resources: dict[str, set[str]] = {}  # service_name -> resource_ids

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
        resource_id: str | None = None,
    ) -> Any:
        """Call a method on a service via the router.

        Args:
            service_name: Name of the target service
            method: Method to call on the service
            params: Method parameters (optional)
            timeout: Request timeout in seconds (uses default if not provided)
            trace_id: Optional trace ID for distributed tracing
            resource_id: Optional resource ID for resource-aware routing

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

        # Add resource_id if provided
        if resource_id is not None:
            request_data["resource_id"] = resource_id

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
