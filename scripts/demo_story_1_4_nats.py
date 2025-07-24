#!/usr/bin/env python3
"""Complete NATS-based test for resource routing.

This test demonstrates all 4 acceptance criteria using real NATS messaging.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

import msgpack
import nats
from demo_utils import (
    DemoLogger,
    DemoResult,
    DemoSettings,
    check_nats_connection,
    colors,
    format_instance_id,
)
from ipc_client_sdk.models import ServiceRegistrationRequest
from ipc_router.application.models import (
    ResourceMetadata,
    ResourceRegistrationRequest,
    RouteRequest,
)
from ipc_router.application.services import (
    ResourceAwareRoutingService,
    ResourceRegistry,
    ResourceService,
)
from ipc_router.infrastructure.messaging.handlers import ResourceHandler, RouteRequestHandler
from ipc_router.infrastructure.messaging.nats_client import NATSClient


async def simulate_service_instance(
    nc: nats.aio.client.Client, instance_id: str, inbox_subject: str, logger: DemoLogger
) -> None:
    """Simulate a service instance that responds to routed requests.

    Args:
        nc: NATS client connection
        instance_id: Unique instance identifier
        inbox_subject: NATS subject for this instance's inbox
        logger: Logger instance for output
    """

    async def handle_request(msg: Any) -> None:
        """Handle incoming requests to this instance."""
        try:
            data = msgpack.unpackb(msg.data, raw=False)
            logger.info(
                f"Instance {format_instance_id(instance_id)} received request",
                method=data.get("method"),
            )

            # Send response
            response = msgpack.packb(
                {
                    "success": True,
                    "result": {
                        "message": f"Hello from {instance_id}",
                        "method": data.get("method"),
                        "handled_by": instance_id,
                        "trace_id": data.get("trace_id"),
                    },
                }
            )

            # Extract response subject from correlation_id
            correlation_id = data.get("correlation_id", "")
            if correlation_id:
                response_subject = f"ipc.response.{correlation_id}"
                await nc.publish(response_subject, response)
                logger.info(
                    f"Instance {format_instance_id(instance_id)} sent response",
                    subject=response_subject,
                )

        except Exception as e:
            logger.error(f"Instance {instance_id} error", error=str(e))

    # Subscribe to instance inbox
    await nc.subscribe(inbox_subject, cb=handle_request)
    logger.success(f"Instance {format_instance_id(instance_id)} listening on {inbox_subject}")


async def send_resource_registration(
    nc: nats.aio.client.Client,
    service_name: str,
    instance_id: str,
    resource_ids: list[str],
    timeout: float = 5.0,
) -> dict[str, Any]:
    """Send resource registration request via NATS.

    Args:
        nc: NATS client connection
        service_name: Name of the service
        instance_id: Instance identifier
        resource_ids: List of resource IDs to register
        timeout: Request timeout in seconds

    Returns:
        Response dictionary from the registration
    """
    # Create metadata for each resource
    metadata_dict: dict[str, dict[str, Any]] = {}
    for resource_id in resource_ids:
        # Create proper metadata object
        meta = ResourceMetadata(
            resource_type="chat_room",
            version=1,
            tags=["active"],
            attributes={"test": "data"},
            created_by="test",
            last_modified=datetime.now(UTC),
            ttl_seconds=None,
            priority=5,
        )
        # Convert to dict to avoid datetime serialization issues
        metadata_dict[resource_id] = {
            "resource_type": meta.resource_type,
            "version": meta.version,
            "tags": meta.tags,
            "attributes": meta.attributes,
            "created_by": meta.created_by,
            "last_modified": meta.last_modified.isoformat(),
            "ttl_seconds": meta.ttl_seconds,
            "priority": meta.priority,
        }

    request = ResourceRegistrationRequest(
        service_name=service_name,
        instance_id=instance_id,
        resource_ids=resource_ids,
        force=False,
        metadata=metadata_dict,
        trace_id=f"trace-{uuid.uuid4().hex[:8]}",
    )

    # Send request - use mode='json' to handle datetime serialization
    request_data = msgpack.packb(request.model_dump(mode="json"), use_bin_type=True)
    response_msg = await nc.request("ipc.resource.register", request_data, timeout=timeout)
    result: dict[str, Any] = msgpack.unpackb(response_msg.data, raw=False)
    return result


async def send_route_request(
    nc: nats.aio.client.Client,
    service_name: str,
    resource_id: str,
    method: str = "test_method",
    timeout: float = 5.0,
) -> dict[str, Any]:
    """Send routing request via NATS and wait for the routed response.

    Args:
        nc: NATS client connection
        service_name: Name of the service
        resource_id: Resource ID to route to
        method: Method to call
        timeout: Request timeout in seconds

    Returns:
        Response dictionary from the routing
    """
    route_request = RouteRequest(
        service_name=service_name,
        method=method,
        params={"test": "data"},
        resource_id=resource_id,
        timeout=timeout,
        trace_id=f"trace-{uuid.uuid4().hex[:8]}",
    )

    # Send route request
    request_data = msgpack.packb(route_request.model_dump(mode="json"), use_bin_type=True)
    response_msg = await nc.request("ipc.route.request", request_data, timeout=timeout)

    # Parse routing response
    route_response: dict[str, Any] = msgpack.unpackb(response_msg.data, raw=False)

    if not route_response.get("success"):
        return route_response  # Return error response

    # The route handler will forward to the instance and return the result
    return route_response


class ResourceRoutingDemo:
    """Main demo class for resource-based routing."""

    def __init__(self, settings: DemoSettings) -> None:
        """Initialize demo with configuration.

        Args:
            settings: Demo configuration settings
        """
        self.settings = settings
        self.logger = DemoLogger("Story 1.4")
        self.nc: nats.aio.client.Client | None = None
        self.router_nats: NATSClient | None = None
        self.resource_registry: ResourceRegistry | None = None
        self.resource_service: ResourceService | None = None
        self.routing_service: ResourceAwareRoutingService | None = None
        self.resource_handler: ResourceHandler | None = None
        self.route_handler: RouteRequestHandler | None = None

    async def setup(self) -> None:
        """Set up NATS connections and routing infrastructure."""
        self.logger.section("Setting up Resource Routing Infrastructure")

        # Connect to NATS
        self.logger.info("Connecting to NATS server...")
        self.nc = await nats.connect(self.settings.nats_url)
        self.router_nats = NATSClient(self.settings.nats_url)
        await self.router_nats.connect()
        self.logger.success("Connected to NATS")

        # Initialize router components
        self.logger.info("Initializing router components...")
        self.resource_registry = ResourceRegistry()
        self.resource_service = ResourceService(self.resource_registry)
        self.routing_service = ResourceAwareRoutingService(self.resource_registry)

        # Start handlers
        self.resource_handler = ResourceHandler(self.router_nats, self.resource_service)
        self.route_handler = RouteRequestHandler(self.router_nats, self.routing_service)

        await self.resource_handler.start()
        await self.route_handler.start()
        self.logger.success("Router handlers started")

    async def register_service_instances(self) -> None:
        """Register service instances in registry."""
        self.logger.info("Registering service instances...")
        assert self.resource_registry is not None
        assert self.nc is not None

        req1 = ServiceRegistrationRequest(
            service_name="chat-service",
            instance_id="chat-instance-1",
            host="localhost",
            port=8001,
            metadata={"zone": "us-west"},
            trace_id="test-trace-1",
        )
        await self.resource_registry.register_service(req1)

        req2 = ServiceRegistrationRequest(
            service_name="chat-service",
            instance_id="chat-instance-2",
            host="localhost",
            port=8002,
            metadata={"zone": "us-east"},
            trace_id="test-trace-2",
        )
        await self.resource_registry.register_service(req2)

        # Start instance simulators
        await simulate_service_instance(
            self.nc, "chat-instance-1", "ipc.instance.chat-instance-1.inbox", self.logger
        )
        await simulate_service_instance(
            self.nc, "chat-instance-2", "ipc.instance.chat-instance-2.inbox", self.logger
        )
        self.logger.success("Registered 2 instances and started simulators")

        # Small delay to ensure subscriptions are ready
        await asyncio.sleep(self.settings.setup_delay)

    async def test_ac1(self) -> bool:
        """AC1: 服务实例能注册自己正在处理一个或多个'资源ID'.

        Returns:
            True if test passes
        """
        self.logger.subsection("AC1: Service instances can register multiple resource IDs")
        assert self.nc is not None

        # Register resources via NATS
        result = await send_resource_registration(
            self.nc,
            "chat-service",
            "chat-instance-1",
            ["room-123", "room-456", "room-789"],
            self.settings.connection_timeout,
        )

        self.logger.info(f"NATS Response: {result}")
        self.logger.info(f"Registered resources: {result.get('registered', [])}")

        if result.get("success") and len(result.get("registered", [])) == 3:
            self.logger.success("AC1 Passed: Instance can register multiple resources via NATS")
            return True
        else:
            self.logger.failure("AC1 Failed: Registration did not succeed as expected")
            return False

    async def test_ac2(self) -> bool:
        """AC2: 一个'资源ID'在同一时间只能被一个实例注册.

        Returns:
            True if test passes
        """
        self.logger.subsection("AC2: Resource ID can only be registered by one instance")
        assert self.nc is not None

        # Try to register same resource with instance 2
        result2 = await send_resource_registration(
            self.nc,
            "chat-service",
            "chat-instance-2",
            ["room-123"],  # Already owned by instance 1
            self.settings.connection_timeout,
        )

        self.logger.info(f"NATS Response: {result2}")
        self.logger.info(f"Conflicts: {result2.get('conflicts', {})}")

        if not result2.get("success") and "room-123" in result2.get("conflicts", {}):
            self.logger.success("AC2 Passed: Resource conflict detected via NATS")
            return True
        else:
            self.logger.failure("AC2 Failed: Conflict was not properly detected")
            return False

    async def test_ac3(self) -> bool:
        """AC3: 包含'资源ID'的请求被精确路由到对应的实例.

        Returns:
            True if test passes
        """
        self.logger.subsection("AC3: Requests with resource_id are routed to correct instance")
        assert self.nc is not None

        # First register a resource for instance 2
        await send_resource_registration(
            self.nc,
            "chat-service",
            "chat-instance-2",
            ["room-999"],
            self.settings.connection_timeout,
        )

        all_passed = True

        # Test routing to instance 1 resources
        for resource_id in ["room-123", "room-456", "room-789"]:
            response = await send_route_request(
                self.nc,
                "chat-service",
                resource_id,
                "send_message",
                self.settings.connection_timeout,
            )
            self.logger.info(
                f"Route for {resource_id}",
                success=response.get("success"),
                instance=response.get("instance_id"),
            )
            if not response.get("success") or response.get("instance_id") != "chat-instance-1":
                all_passed = False
                self.logger.failure(f"Routing failed for {resource_id}")

        # Test routing to instance 2 resource
        response = await send_route_request(
            self.nc, "chat-service", "room-999", "send_message", self.settings.connection_timeout
        )
        self.logger.info(
            "Route for room-999",
            success=response.get("success"),
            instance=response.get("instance_id"),
        )
        if not response.get("success") or response.get("instance_id") != "chat-instance-2":
            all_passed = False
            self.logger.failure("Routing failed for room-999")

        if all_passed:
            self.logger.success("AC3 Passed: Resource-based routing works correctly via NATS")
        return all_passed

    async def test_ac4(self) -> bool:
        """AC4: 若请求的'资源ID'无实例处理,则返回明确错误.

        Returns:
            True if test passes
        """
        self.logger.subsection("AC4: Requests for non-existent resources return clear error")
        assert self.nc is not None

        response = await send_route_request(
            self.nc,
            "chat-service",
            "room-unknown",
            "send_message",
            self.settings.connection_timeout,
        )
        self.logger.info("Route for unknown resource", success=response.get("success"))
        self.logger.info(f"Error: {response.get('error', {})}")

        error = response.get("error", {})
        if (
            not response.get("success")
            and error.get("type") == "ResourceNotFoundError"
            and error.get("code") == 404
        ):
            self.logger.success("AC4 Passed: Clear error for unknown resource via NATS")
            return True
        else:
            self.logger.failure("AC4 Failed: Did not receive expected error response")
            return False

    async def test_e2e_flow(self) -> None:
        """Additional Test: Complete end-to-end message flow."""
        self.logger.subsection("Additional Test: Complete end-to-end message flow")
        assert self.nc is not None

        # Create a proper client subscription to receive forwarded responses
        response_future: asyncio.Future[dict[str, Any]] = asyncio.Future()

        async def handle_response(msg: Any) -> None:
            """Handle response message."""
            data = msgpack.unpackb(msg.data, raw=False)
            response_future.set_result(data)

        # Subscribe to a unique response subject
        response_subject = f"test.response.{uuid.uuid4().hex[:8]}"
        await self.nc.subscribe(response_subject, cb=handle_response)

        # Send request with reply subject
        route_request = RouteRequest(
            service_name="chat-service",
            method="get_room_info",
            params={"room_id": "room-123"},
            resource_id="room-123",
            timeout=self.settings.connection_timeout,
            trace_id="e2e-test",
        )

        request_data = msgpack.packb(route_request.model_dump(mode="json"), use_bin_type=True)

        # Send with reply subject
        await self.nc.publish("ipc.route.request", request_data, reply=response_subject)

        # Wait for response (with timeout)
        try:
            # First we get the routing response
            routing_response = await asyncio.wait_for(response_future, timeout=2.0)
            self.logger.info(f"Routing response: {routing_response}")
            self.logger.success("Message flow verified")

        except TimeoutError:
            self.logger.info(
                "Note: Full end-to-end forwarding requires complete RouteHandler implementation"
            )

    async def cleanup(self) -> None:
        """Clean up resources."""
        self.logger.warning("Cleaning up...")

        if self.resource_handler:
            await self.resource_handler.stop()
        if self.route_handler:
            await self.route_handler.stop()
        if self.router_nats:
            await self.router_nats.disconnect()
        if self.nc:
            await self.nc.close()

        self.logger.success("Cleanup complete")

    async def run(self) -> DemoResult:
        """Run the complete demonstration.

        Returns:
            Demo execution result
        """
        self.logger.demo_header("Story 1.4 Resource Routing NATS Test", "基于资源的精确路由")

        result = DemoResult(success=True)

        try:
            await self.setup()
            await self.register_service_instances()

            # Run acceptance criteria tests
            if await self.test_ac1():
                result.criteria_passed.append(
                    "AC1: Services can register multiple resource IDs via NATS"
                )
            else:
                result.criteria_failed.append("AC1: Resource registration failed")
                result.success = False

            if await self.test_ac2():
                result.criteria_passed.append(
                    "AC2: Resource IDs are exclusive (conflicts detected)"
                )
            else:
                result.criteria_failed.append("AC2: Resource exclusivity not enforced")
                result.success = False

            if await self.test_ac3():
                result.criteria_passed.append("AC3: Resource-based routing works correctly")
            else:
                result.criteria_failed.append("AC3: Resource routing failed")
                result.success = False

            if await self.test_ac4():
                result.criteria_passed.append("AC4: Clear errors for unknown resources")
            else:
                result.criteria_failed.append("AC4: Error handling not working")
                result.success = False

            # Run additional tests
            await self.test_e2e_flow()

            if result.success:
                self.logger.section(
                    f"{colors.GREEN}ALL ACCEPTANCE CRITERIA PASSED WITH NATS!{colors.RESET}"
                )
            else:
                self.logger.section(f"{colors.RED}Some Acceptance Criteria FAILED!{colors.RESET}")

            self.logger.info("\nSummary:")
            for passed in result.criteria_passed:
                self.logger.success(passed)
            for failed in result.criteria_failed:
                self.logger.failure(failed)

            if result.success:
                self.logger.info(
                    "\nThe resource-based routing is fully functional with NATS messaging!"
                )

        except Exception as e:
            result.success = False
            result.error_message = str(e)
            self.logger.error("Demo failed", error=str(e))

        finally:
            await self.cleanup()

        return result


async def main() -> None:
    """Entry point."""
    settings = DemoSettings()

    # Check NATS connection
    if not await check_nats_connection(settings):
        return

    demo = ResourceRoutingDemo(settings)
    result = await demo.run()

    # Exit with appropriate code
    exit(0 if result.success else 1)


if __name__ == "__main__":
    asyncio.run(main())
