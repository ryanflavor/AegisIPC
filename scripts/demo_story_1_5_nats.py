#!/usr/bin/env python3
"""Complete NATS-based test for exactly-once delivery mechanism.

This test demonstrates all 4 acceptance criteria for Story 1.5:
1. 发出的每条请求消息都有全局唯一ID
2. 接收方在成功处理业务后必须发送ACK
3. 系统在未收到ACK时会进行重试
4. 接收方必须是幂等的,能根据消息ID安全地忽略重复消息
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
from ipc_client_sdk.clients import ServiceClient
from ipc_client_sdk.models import (
    ReliableDeliveryConfig,
    ServiceRegistrationRequest,
)
from ipc_router.application.models import (
    AcknowledgmentRequest,
    MessageStatusRequest,
    RouteRequest,
)
from ipc_router.application.services import (
    AcknowledgmentService,
    MessageStoreService,
    ResourceAwareRoutingService,
    ResourceRegistry,
)
from ipc_router.domain.entities import MessageState
from ipc_router.infrastructure.messaging.handlers import (
    AcknowledgmentHandler,
    RouteRequestHandler,
)
from ipc_router.infrastructure.messaging.nats_client import NATSClient


class SimulatedService:
    """Simulates a service instance with idempotent message handling."""

    def __init__(
        self,
        nc: nats.aio.client.Client,
        instance_id: str,
        logger: DemoLogger,
        should_fail_first: bool = False,
        should_timeout: bool = False,
    ) -> None:
        """Initialize simulated service.

        Args:
            nc: NATS client connection
            instance_id: Unique instance identifier
            logger: Logger instance
            should_fail_first: If True, fail first attempt then succeed
            should_timeout: If True, simulate timeout by not responding
        """
        self.nc = nc
        self.instance_id = instance_id
        self.logger = logger
        self.inbox_subject = f"ipc.instance.{instance_id}.inbox"
        self.processed_messages: dict[str, Any] = {}  # message_id -> response
        self.attempt_counts: dict[str, int] = {}  # message_id -> attempt count
        self.should_fail_first = should_fail_first
        self.should_timeout = should_timeout

    async def start(self) -> None:
        """Start listening for requests."""
        await self.nc.subscribe(self.inbox_subject, cb=self._handle_request)
        self.logger.success(f"Instance {format_instance_id(self.instance_id)} started")

    async def _handle_request(self, msg: Any) -> None:
        """Handle incoming request with idempotency."""
        try:
            data = msgpack.unpackb(msg.data, raw=False)
            message_id = data.get("message_id")
            method = data.get("method")
            correlation_id = data.get("correlation_id", "")

            # Track attempt count
            self.attempt_counts[message_id] = self.attempt_counts.get(message_id, 0) + 1
            attempt = self.attempt_counts[message_id]

            self.logger.info(
                f"Instance {format_instance_id(self.instance_id)} received",
                message_id=message_id[:8],
                method=method,
                attempt=attempt,
            )

            # Check if already processed (idempotency)
            if message_id in self.processed_messages:
                self.logger.warning(
                    "Duplicate message detected! Returning cached response",
                    message_id=message_id[:8],
                )
                response = self.processed_messages[message_id]
            else:
                # Simulate processing
                if self.should_timeout:
                    self.logger.warning(
                        "Simulating timeout - not responding", message_id=message_id[:8]
                    )
                    return  # Don't send response to simulate timeout

                if self.should_fail_first and attempt == 1:
                    self.logger.warning(
                        "Simulating failure on first attempt", message_id=message_id[:8]
                    )
                    # Don't send ACK to trigger retry
                    return

                # Process the request
                await asyncio.sleep(0.1)  # Simulate work

                result = {
                    "message": f"Processed by {self.instance_id}",
                    "method": method,
                    "handled_by": self.instance_id,
                    "message_id": message_id,
                    "processing_time_ms": 100,
                    "attempt": attempt,
                }

                response = msgpack.packb(
                    {
                        "success": True,
                        "result": result,
                        "instance_id": self.instance_id,
                    }
                )

                # Cache response for idempotency
                self.processed_messages[message_id] = response

                self.logger.success(
                    "Processed successfully", message_id=message_id[:8], attempt=attempt
                )

            # Send response
            if correlation_id:
                response_subject = f"ipc.response.{correlation_id}"
                await self.nc.publish(response_subject, response)

                # Send acknowledgment
                ack_request = AcknowledgmentRequest(
                    message_id=message_id,
                    service_name=data.get("service_name", "test-service"),
                    instance_id=self.instance_id,
                    status="success",
                    processing_time_ms=100,
                    trace_id=data.get("trace_id", ""),
                )

                ack_data = msgpack.packb(ack_request.model_dump(mode="json"))
                await self.nc.publish(f"ipc.ack.{message_id}", ack_data)

                self.logger.info("Sent ACK", message_id=message_id[:8], status="success")

        except Exception as e:
            self.logger.error("Error processing request", error=str(e))


class ExactlyOnceDeliveryDemo:
    """Main demo class for exactly-once delivery mechanism."""

    def __init__(self, settings: DemoSettings) -> None:
        """Initialize demo with configuration."""
        self.settings = settings
        self.logger = DemoLogger("Story 1.5")
        self.nc: nats.aio.client.Client | None = None
        self.router_nats: NATSClient | None = None
        self.resource_registry: ResourceRegistry | None = None
        self.routing_service: ResourceAwareRoutingService | None = None
        self.message_store: MessageStoreService | None = None
        self.ack_service: AcknowledgmentService | None = None
        self.route_handler: RouteRequestHandler | None = None
        self.ack_handler: AcknowledgmentHandler | None = None
        self.services: list[SimulatedService] = []

    async def setup(self) -> None:
        """Set up NATS connections and routing infrastructure."""
        self.logger.section("Setting up Exactly-Once Delivery Infrastructure")

        # Connect to NATS
        self.logger.info("Connecting to NATS server...")
        self.nc = await nats.connect(self.settings.nats_url)
        self.router_nats = NATSClient(self.settings.nats_url)
        await self.router_nats.connect()
        self.logger.success("Connected to NATS")

        # Initialize router components
        self.logger.info("Initializing router components...")
        self.resource_registry = ResourceRegistry()
        self.message_store = MessageStoreService()
        self.ack_service = AcknowledgmentService(
            message_store=self.message_store,
            nats_client=self.router_nats,
        )
        self.routing_service = ResourceAwareRoutingService(
            resource_registry=self.resource_registry,
            message_store=self.message_store,
            acknowledgment_service=self.ack_service,
        )

        # Start handlers
        self.route_handler = RouteRequestHandler(self.router_nats, self.routing_service)
        self.ack_handler = AcknowledgmentHandler(self.router_nats, self.ack_service)

        await self.route_handler.start()
        await self.ack_handler.start()
        self.logger.success("Router handlers started with reliable delivery support")

    async def register_service_instances(self) -> None:
        """Register service instances."""
        self.logger.info("Registering service instances...")
        assert self.resource_registry is not None
        assert self.nc is not None

        # Register instances
        for i in range(1, 4):
            instance_id = f"test-instance-{i}"
            req = ServiceRegistrationRequest(
                service_name="test-service",
                instance_id=instance_id,
                host="localhost",
                port=8000 + i,
                metadata={"zone": f"zone-{i}"},
                trace_id=f"setup-trace-{i}",
            )
            await self.resource_registry.register_service(req)

        # Start simulated services with different behaviors
        # Instance 1: Normal behavior
        service1 = SimulatedService(self.nc, "test-instance-1", self.logger)
        await service1.start()
        self.services.append(service1)

        # Instance 2: Fails first attempt then succeeds
        service2 = SimulatedService(self.nc, "test-instance-2", self.logger, should_fail_first=True)
        await service2.start()
        self.services.append(service2)

        # Instance 3: Simulates timeout
        service3 = SimulatedService(self.nc, "test-instance-3", self.logger, should_timeout=True)
        await service3.start()
        self.services.append(service3)

        self.logger.success("Registered 3 instances with different behaviors")
        await asyncio.sleep(self.settings.setup_delay)

    async def test_ac1(self) -> bool:
        """AC1: 发出的每条请求消息都有全局唯一ID."""
        self.logger.subsection("AC1: Every request message has a globally unique ID")
        assert self.nc is not None

        # Send multiple requests and collect message IDs
        message_ids: set[str] = set()

        for i in range(10):
            request = RouteRequest(
                service_name="test-service",
                method="test_method",
                params={"test": f"data-{i}"},
                timeout=5.0,
                trace_id=f"ac1-trace-{i}",
                require_ack=True,  # Enable acknowledgment
            )

            # The routing service should generate a unique message_id
            request_data = msgpack.packb(request.model_dump(mode="json"))
            response_msg = await self.nc.request(
                "ipc.route.request", request_data, timeout=self.settings.connection_timeout
            )

            response: dict[str, Any] = msgpack.unpackb(response_msg.data, raw=False)

            if response.get("success"):
                message_id = response.get("message_id", "")
                if message_id:
                    message_ids.add(message_id)
                    self.logger.info(f"Request {i+1} generated message_id: {message_id[:8]}...")

        # Verify all IDs are unique
        if len(message_ids) == 10:
            self.logger.success("AC1 Passed: All 10 messages have unique IDs")

            # Verify they are valid UUIDs
            try:
                for msg_id in message_ids:
                    uuid.UUID(msg_id)
                self.logger.success("All message IDs are valid UUIDs")
            except ValueError:
                self.logger.failure("Some message IDs are not valid UUIDs")
                return False

            return True
        else:
            self.logger.failure(f"AC1 Failed: Expected 10 unique IDs, got {len(message_ids)}")
            return False

    async def test_ac2(self) -> bool:
        """AC2: 接收方在成功处理业务后必须发送ACK."""
        self.logger.subsection("AC2: Receiver must send ACK after successful processing")
        assert self.nc is not None

        # Create a client to send reliable request
        client = ServiceClient(
            nats_client=self.router_nats,
            service_name="test-service",
            client_id="test-client-ac2",
        )

        # Send a reliable request
        try:
            result = await client.call_reliable(
                method="process_order",
                params={"order_id": "12345"},
                timeout=5.0,
                delivery_config=ReliableDeliveryConfig(
                    require_acknowledgment=True,
                    acknowledgment_timeout=2.0,
                    max_retries=0,  # No retries for this test
                ),
                trace_id="ac2-test",
            )

            self.logger.info(f"Received result: {result}")

            # Check if we got the result (which means ACK was received)
            if (
                result
                and isinstance(result, dict)
                and result.get("handled_by") == "test-instance-1"
            ):
                self.logger.success("AC2 Passed: ACK was received and result returned")
                return True
            else:
                self.logger.failure("AC2 Failed: Unexpected result format")
                return False

        except TimeoutError:
            self.logger.failure("AC2 Failed: No ACK received, request timed out")
            return False
        except Exception as e:
            self.logger.failure(f"AC2 Failed: {e!s}")
            return False

    async def test_ac3(self) -> bool:
        """AC3: 系统在未收到ACK时会进行重试."""
        self.logger.subsection("AC3: System retries when ACK is not received")
        assert self.nc is not None

        # Create a client
        client = ServiceClient(
            nats_client=self.router_nats,
            service_name="test-service",
            client_id="test-client-ac3",
        )

        # Send request to instance-2 which fails first attempt
        try:
            # First register instance-2 as the only available instance
            if self.resource_registry:
                await self.resource_registry.unregister_service("test-service", "test-instance-1")
                await self.resource_registry.unregister_service("test-service", "test-instance-3")

            result = await client.call_reliable(
                method="process_with_retry",
                params={"data": "retry-test"},
                timeout=10.0,
                delivery_config=ReliableDeliveryConfig(
                    require_acknowledgment=True,
                    acknowledgment_timeout=2.0,
                    max_retries=3,
                    retry_delay=0.5,
                ),
                trace_id="ac3-retry-test",
            )

            # Check the result shows it was processed after retry
            if result and isinstance(result, dict):
                attempt = result.get("attempt", 0)
                if attempt > 1:
                    self.logger.success(
                        f"AC3 Passed: Request succeeded after {attempt} attempts (retry worked)"
                    )
                    return True
                else:
                    self.logger.failure("AC3 Failed: No retry detected")
                    return False
            else:
                self.logger.failure("AC3 Failed: Unexpected result")
                return False

        except Exception as e:
            self.logger.failure(f"AC3 Failed: {e!s}")
            return False
        finally:
            # Re-register all instances
            for i in range(1, 4):
                instance_id = f"test-instance-{i}"
                req = ServiceRegistrationRequest(
                    service_name="test-service",
                    instance_id=instance_id,
                    host="localhost",
                    port=8000 + i,
                    metadata={"zone": f"zone-{i}"},
                    trace_id=f"restore-trace-{i}",
                )
                if self.resource_registry:
                    await self.resource_registry.register_service(req)

    async def test_ac4(self) -> bool:
        """AC4: 接收方必须是幂等的,能根据消息ID安全地忽略重复消息."""
        self.logger.subsection(
            "AC4: Receiver must be idempotent, safely ignoring duplicate messages"
        )
        assert self.nc is not None

        # Generate a specific message ID for testing
        test_message_id = str(uuid.uuid4())

        # Send the same message multiple times
        responses = []

        for i in range(3):
            request = RouteRequest(
                service_name="test-service",
                method="idempotent_operation",
                params={"data": "test", "attempt": i + 1},
                timeout=5.0,
                trace_id=f"ac4-trace-{i}",
                message_id=test_message_id,  # Use same message ID
                require_ack=True,
            )

            request_data = msgpack.packb(request.model_dump(mode="json"))

            try:
                response_msg = await self.nc.request(
                    "ipc.route.request", request_data, timeout=self.settings.connection_timeout
                )

                response: dict[str, Any] = msgpack.unpackb(response_msg.data, raw=False)
                responses.append(response)

                if response.get("success"):
                    self.logger.info(
                        f"Attempt {i+1}", success=True, cached=response.get("from_cache", False)
                    )

            except Exception as e:
                self.logger.error(f"Attempt {i+1} failed", error=str(e))
                responses.append({"success": False, "error": str(e)})

        # Verify idempotency
        # First response should be fresh, others should be from cache
        if len(responses) >= 3:
            # All responses should be successful
            all_success = all(r.get("success") for r in responses)

            # The result should be the same for all attempts
            results = [r.get("result") for r in responses if r.get("success")]

            if all_success and len({str(r) for r in results}) == 1:
                self.logger.success(
                    "AC4 Passed: All duplicate requests returned the same result (idempotent)"
                )

                # Check if service detected duplicates
                service = self.services[0]  # test-instance-1
                if test_message_id in service.attempt_counts:
                    actual_processing = service.attempt_counts[test_message_id]
                    self.logger.info(
                        f"Message was actually processed {actual_processing} time(s) "
                        + f"but returned {len(responses)} responses"
                    )

                return True
            else:
                self.logger.failure("AC4 Failed: Responses were not idempotent")
                return False
        else:
            self.logger.failure("AC4 Failed: Not enough responses collected")
            return False

    async def test_message_status_query(self) -> None:
        """Additional Test: Query message status."""
        self.logger.subsection("Additional Test: Message Status Query")
        assert self.nc is not None

        # Send a request and get its message ID
        request = RouteRequest(
            service_name="test-service",
            method="status_test",
            params={"test": "data"},
            timeout=5.0,
            trace_id="status-test",
            require_ack=True,
        )

        request_data = msgpack.packb(request.model_dump(mode="json"))
        response_msg = await self.nc.request(
            "ipc.route.request", request_data, timeout=self.settings.connection_timeout
        )

        response: dict[str, Any] = msgpack.unpackb(response_msg.data, raw=False)
        message_id = response.get("message_id", "")

        if message_id:
            # Query the message status
            status_request = MessageStatusRequest(
                message_id=message_id,
                trace_id="status-query",
            )

            status_data = msgpack.packb(status_request.model_dump(mode="json"))
            status_response_msg = await self.nc.request(
                "ipc.message.status", status_data, timeout=2.0
            )

            status_response: dict[str, Any] = msgpack.unpackb(status_response_msg.data, raw=False)

            self.logger.info(f"Message Status: {status_response}")

            if status_response.get("state") == MessageState.ACKNOWLEDGED.value:
                self.logger.success("Message status query working correctly")
            else:
                self.logger.warning(f"Message state: {status_response.get('state')}")

    async def test_performance(self) -> None:
        """Performance Test: Verify throughput and latency requirements."""
        self.logger.subsection("Performance Test: Throughput and Latency")
        assert self.nc is not None

        # Create a client
        client = ServiceClient(
            nats_client=self.router_nats,
            service_name="test-service",
            client_id="test-client-perf",
        )

        # Measure throughput
        start_time = datetime.now(UTC)
        successful_messages = 0
        total_messages = 50

        tasks = []
        for i in range(total_messages):
            task = client.call_reliable(
                method="perf_test",
                params={"index": i},
                timeout=5.0,
                delivery_config=ReliableDeliveryConfig(
                    require_acknowledgment=True,
                    acknowledgment_timeout=1.0,
                    max_retries=1,
                ),
                trace_id=f"perf-{i}",
            )
            tasks.append(task)

        # Run all requests concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)

        end_time = datetime.now(UTC)
        duration = (end_time - start_time).total_seconds()

        # Count successes
        for result in results:
            if not isinstance(result, Exception):
                successful_messages += 1

        # Calculate metrics
        throughput = successful_messages / duration * 60  # messages per minute
        success_rate = successful_messages / total_messages * 100

        self.logger.info("Performance Results:")
        self.logger.info(f"  Total messages: {total_messages}")
        self.logger.info(f"  Successful: {successful_messages}")
        self.logger.info(f"  Duration: {duration:.2f}s")
        self.logger.info(f"  Throughput: {throughput:.0f} TPM")
        self.logger.info(f"  Success rate: {success_rate:.1f}%")

        if throughput > 200 and success_rate == 100:
            self.logger.success("Performance requirements met (>200 TPM, 0% loss)")
        else:
            self.logger.warning("Performance below requirements")

    async def cleanup(self) -> None:
        """Clean up resources."""
        self.logger.warning("Cleaning up...")

        if self.route_handler:
            await self.route_handler.stop()
        if self.ack_handler:
            await self.ack_handler.stop()
        if self.router_nats:
            await self.router_nats.disconnect()
        if self.nc:
            await self.nc.close()

        self.logger.success("Cleanup complete")

    async def run(self) -> DemoResult:
        """Run the complete demonstration."""
        self.logger.demo_header("Story 1.5 Exactly-Once Delivery Test", "精确一次投递保证机制")

        result = DemoResult(success=True)

        try:
            await self.setup()
            await self.register_service_instances()

            # Run acceptance criteria tests
            if await self.test_ac1():
                result.criteria_passed.append("AC1: Every message has a globally unique ID")
            else:
                result.criteria_failed.append("AC1: Message ID generation failed")
                result.success = False

            if await self.test_ac2():
                result.criteria_passed.append("AC2: Receivers send ACK after successful processing")
            else:
                result.criteria_failed.append("AC2: ACK mechanism not working")
                result.success = False

            if await self.test_ac3():
                result.criteria_passed.append("AC3: System retries when ACK not received")
            else:
                result.criteria_failed.append("AC3: Retry mechanism failed")
                result.success = False

            if await self.test_ac4():
                result.criteria_passed.append(
                    "AC4: Receivers are idempotent, safely handle duplicates"
                )
            else:
                result.criteria_failed.append("AC4: Idempotency not working")
                result.success = False

            # Run additional tests
            await self.test_message_status_query()
            await self.test_performance()

            if result.success:
                self.logger.section(f"{colors.GREEN}ALL ACCEPTANCE CRITERIA PASSED!{colors.RESET}")
            else:
                self.logger.section(f"{colors.RED}Some Acceptance Criteria FAILED!{colors.RESET}")

            self.logger.info("\nSummary:")
            for passed in result.criteria_passed:
                self.logger.success(passed)
            for failed in result.criteria_failed:
                self.logger.failure(failed)

            if result.success:
                self.logger.info("\nThe exactly-once delivery mechanism is fully functional!")
                self.logger.info("✓ Messages have unique IDs")
                self.logger.info("✓ Acknowledgments are sent and received")
                self.logger.info("✓ Retry mechanism works on failures")
                self.logger.info("✓ Idempotent processing prevents duplicates")

        except Exception as e:
            result.success = False
            result.error_message = str(e)
            self.logger.error("Demo failed", error=str(e))
            import traceback

            traceback.print_exc()

        finally:
            await self.cleanup()

        return result


async def main() -> None:
    """Entry point."""
    settings = DemoSettings()

    # Check NATS connection
    if not await check_nats_connection(settings):
        return

    demo = ExactlyOnceDeliveryDemo(settings)
    result = await demo.run()

    # Exit with appropriate code
    exit(0 if result.success else 1)


if __name__ == "__main__":
    asyncio.run(main())
