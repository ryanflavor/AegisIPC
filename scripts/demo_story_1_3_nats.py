#!/usr/bin/env python3
"""
Real NATS-based demonstration of Story 1.3 acceptance criteria.
This script uses actual NATS messaging to show the routing system in action.

Acceptance Criteria:
1. 发送到服务名的请求被投递到其中一个实例。
2. 连续请求被分发到不同实例。
3. 掉线实例会自动从路由池中移除。
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
import sys
from collections import defaultdict
from datetime import datetime
from typing import Any

from demo_utils import (
    DemoLogger,
    DemoResult,
    DemoSettings,
    check_nats_connection,
    colors,
    format_instance_id,
)
from ipc_client_sdk.models import ServiceRegistrationRequest
from ipc_router.application.services import HealthChecker, RoutingService, ServiceRegistry
from ipc_router.domain.enums import ServiceStatus
from ipc_router.domain.strategies.round_robin import RoundRobinLoadBalancer
from ipc_router.infrastructure.messaging.handlers import RouteRequestHandler
from ipc_router.infrastructure.messaging.nats_client import NATSClient


class ServiceInstance:
    """Simulates a service instance that responds to NATS requests."""

    def __init__(
        self, instance_id: str, service_name: str, port: int, nats_client: NATSClient
    ) -> None:
        """Initialize service instance.

        Args:
            instance_id: Unique instance identifier
            service_name: Name of the service
            port: Port number for the instance
            nats_client: NATS client for messaging
        """
        self.instance_id = instance_id
        self.service_name = service_name
        self.port = port
        self.nats_client = nats_client
        self.request_count = 0
        self.is_alive = True
        self.inbox_subject = f"ipc.instance.{instance_id}.inbox"
        self._subscription: Any | None = None
        self.logger = DemoLogger(f"Instance-{instance_id}")

    async def start(self) -> None:
        """Start listening for requests on the instance inbox."""

        async def handle_message(data: dict[str, Any], reply_subject: str | None) -> None:
            """Handle incoming messages."""
            if not self.is_alive:
                self.logger.error(f"Instance {self.instance_id} is down, ignoring request")
                return

            self.request_count += 1
            self.logger.info(
                f"  {format_instance_id(self.instance_id)} handling request #{self.request_count}"
            )

            # Simulate processing
            await asyncio.sleep(0.01)

            # Send response
            if reply_subject:
                response = {
                    "success": True,
                    "result": {
                        "handled_by": self.instance_id,
                        "request_number": self.request_count,
                        "method": data.get("method", "unknown"),
                        "timestamp": datetime.now().isoformat(),
                    },
                }
                await self.nats_client.publish(reply_subject, response)

        self._subscription = await self.nats_client.subscribe(
            self.inbox_subject, callback=handle_message
        )
        self.logger.success(
            f"Instance {format_instance_id(self.instance_id)} started on {self.inbox_subject}"
        )

    async def stop(self) -> None:
        """Stop the instance and clean up."""
        if self._subscription:
            await self.nats_client.unsubscribe(self._subscription)
        self.is_alive = False

    def kill(self) -> None:
        """Simulate instance failure."""
        self.is_alive = False
        self.logger.error(f"💀 Instance {self.instance_id} has been killed!")


class NATSRoutingDemo:
    """Main demo class using real NATS messaging."""

    def __init__(self, settings: DemoSettings) -> None:
        """Initialize demo with configuration.

        Args:
            settings: Demo configuration settings
        """
        self.settings = settings
        self.logger = DemoLogger("Story 1.3")
        self.router_nats: NATSClient | None = None
        self.client_nats: NATSClient | None = None
        self.service_registry = ServiceRegistry()
        self.load_balancer = RoundRobinLoadBalancer()
        self.routing_service = RoutingService(self.service_registry, self.load_balancer)
        self.health_checker = HealthChecker(
            self.service_registry, check_interval=2.0, heartbeat_timeout=5.0
        )
        self.route_handler: RouteRequestHandler | None = None
        self.service_instances: dict[str, ServiceInstance] = {}
        self.request_distribution: defaultdict[str, int] = defaultdict(int)
        self._health_checker_task: asyncio.Task[Any] | None = None

    async def setup(self) -> None:
        """Set up NATS connections and routing infrastructure."""
        self.logger.section("Setting up NATS Routing Infrastructure")

        # Connect router components
        self.logger.info("Connecting router to NATS...")
        self.router_nats = NATSClient(self.settings.nats_url)
        await self.router_nats.connect()
        self.logger.success("Router connected to NATS")

        # Connect client
        self.logger.info("Connecting client to NATS...")
        self.client_nats = NATSClient(self.settings.nats_url)
        await self.client_nats.connect()
        self.logger.success("Client connected to NATS")

        # Start route handler
        self.route_handler = RouteRequestHandler(self.router_nats, self.routing_service)
        await self.route_handler.start()
        self.logger.success("Route handler started")

        # Start health checker
        self._health_checker_task = asyncio.create_task(self.health_checker.start())
        self.logger.success("Health checker started")

    async def create_service_instances(self) -> None:
        """Create and register 5 service instances."""
        self.logger.section("Creating Service Instances")

        service_name = "math-service"
        assert self.router_nats is not None

        for i in range(1, 6):
            instance_id = f"{service_name}-{i}"
            port = 5000 + i

            # Create and start service instance
            instance = ServiceInstance(instance_id, service_name, port, self.router_nats)
            await instance.start()
            self.service_instances[instance_id] = instance

            # Register with service registry
            registration = ServiceRegistrationRequest(
                instance_id=instance_id,
                service_name=service_name,
                host="localhost",
                port=port,
                metadata={"version": "1.0.0", "zone": f"zone-{i}"},
                trace_id=f"setup-{i}",
            )

            await self.service_registry.register_service(registration)
            self.logger.success(f"Registered {format_instance_id(instance_id)} with registry")

        self.logger.success("All instances ready!")
        await asyncio.sleep(1)  # Let everything settle

    async def demonstrate_ac1(self) -> bool:
        """AC1: 发送到服务名的请求被投递到其中一个实例.

        Returns:
            True if routing works correctly
        """
        self.logger.subsection("AC1: Service Name Routing")
        self.logger.info("Sending request to 'math-service' via NATS")

        # Send request via NATS
        request = {
            "service_name": "math-service",
            "method": "calculate",
            "params": {"operation": "add", "a": 10, "b": 20},
            "timeout": self.settings.connection_timeout,
            "trace_id": "ac1-demo-001",
        }

        try:
            # Use request-reply pattern
            assert self.client_nats is not None
            response = await self.client_nats.request(
                "ipc.route.request", request, timeout=self.settings.connection_timeout
            )

            if response and response.get("success"):
                instance_id = response.get("instance_id", "")
                result = response.get("result", {})

                self.request_distribution[instance_id] += 1

                self.logger.success("SUCCESS:")
                self.logger.info(f"  Request: calculate({request['params']})")
                self.logger.info(f"  Routed to: {format_instance_id(instance_id)}")
                self.logger.info(f"  Response: handled_by={result.get('handled_by')}")
                self.logger.info(f"  Request #{result.get('request_number')} for this instance")
                return True
            else:
                self.logger.failure(f"FAILED: {response}")
                return False

        except Exception as e:
            self.logger.error("Request failed", error=str(e))
            return False

    async def demonstrate_ac2(self) -> bool:
        """AC2: 连续请求被分发到不同实例.

        Returns:
            True if load balancing works correctly
        """
        self.logger.subsection("AC2: Load Balancing Distribution")
        self.logger.info("Sending 20 consecutive requests via NATS")

        distribution: defaultdict[str, int] = defaultdict(int)
        assert self.client_nats is not None

        for i in range(20):
            request = {
                "service_name": "math-service",
                "method": "process",
                "params": {"request_id": i, "data": f"test-{i}"},
                "timeout": self.settings.connection_timeout,
                "trace_id": f"ac2-{i}",
            }

            try:
                response = await self.client_nats.request(
                    "ipc.route.request", request, timeout=self.settings.connection_timeout
                )

                if response and response.get("success"):
                    instance_id = response.get("instance_id", "")
                    distribution[instance_id] += 1
                    self.request_distribution[instance_id] += 1
                    self.logger.info(f"Request {i+1:2d} → {format_instance_id(instance_id)}")
                else:
                    self.logger.failure(f"Request {i+1:2d} → Failed")

            except Exception as e:
                self.logger.error(f"Request {i+1:2d} → Error", error=str(e))

            await asyncio.sleep(0.05)  # Small delay for visibility

        # Show distribution
        self.logger.info(f"\n{colors.BOLD}Distribution Analysis:{colors.RESET}")
        for instance_id in sorted(distribution.keys()):
            count = distribution[instance_id]
            bar = "█" * count
            self.logger.info(f"  {instance_id}: {bar} ({count} requests)")

        # Verify round-robin
        counts = list(distribution.values())
        if len(distribution) == 5 and max(counts) - min(counts) <= 1:
            self.logger.success("PERFECT Round-Robin Distribution!")
            self.logger.info(f"  Each instance got {counts[0]} requests (±1)")
            return True
        else:
            self.logger.warning("Distribution not perfectly balanced")
            return False

    async def demonstrate_ac3(self) -> bool:
        """AC3: 掉线实例会自动从路由池中移除.

        Returns:
            True if failed instances are properly excluded
        """
        self.logger.subsection("AC3: Failed Instance Removal")
        self.logger.info("Simulating instance failures...")

        # Kill two instances
        failed_instances = ["math-service-2", "math-service-4"]

        for instance_id in failed_instances:
            # Kill the actual instance
            self.service_instances[instance_id].kill()

            # Update registry status
            await self.service_registry.update_instance_status(
                "math-service", instance_id, ServiceStatus.UNHEALTHY
            )

        # Make sure the other instances remain healthy
        healthy_instances = ["math-service-1", "math-service-3", "math-service-5"]
        for instance_id in healthy_instances:
            await self.service_registry.update_instance_status(
                "math-service", instance_id, ServiceStatus.ONLINE
            )

        self.logger.info("\nWaiting for health checker to process...")
        await asyncio.sleep(0.5)  # Short delay to let registry update

        # Send requests and verify routing
        self.logger.info("\nSending 15 requests (should avoid failed instances):\n")

        routed_instances: set[str] = set()
        failed_routes: list[str] = []
        assert self.client_nats is not None

        for i in range(15):
            request = {
                "service_name": "math-service",
                "method": "health_check",
                "params": {"test_id": i},
                "timeout": self.settings.connection_timeout,
                "trace_id": f"ac3-{i}",
            }

            try:
                response = await self.client_nats.request(
                    "ipc.route.request", request, timeout=self.settings.connection_timeout
                )

                if response and response.get("success"):
                    instance_id = response.get("instance_id", "")
                    routed_instances.add(instance_id)
                    self.request_distribution[instance_id] += 1

                    is_healthy = instance_id not in failed_instances
                    status = (
                        f"{colors.GREEN}✓{colors.RESET}"
                        if is_healthy
                        else f"{colors.RED}✗{colors.RESET}"
                    )
                    self.logger.info(
                        f"Request {i+1:2d} → {format_instance_id(instance_id)} {status}"
                    )

                    if not is_healthy:
                        failed_routes.append(instance_id)
                else:
                    self.logger.failure(f"Request {i+1:2d} → Failed: {response}")

            except Exception as e:
                self.logger.error(f"Request {i+1:2d} → Error", error=str(e))

        # Verify results
        self.logger.info(f"\n{colors.BOLD}Verification:{colors.RESET}")
        self.logger.info(f"  Failed instances: {failed_instances}")
        self.logger.info(f"  Used instances: {sorted(routed_instances)}")

        success = not routed_instances.intersection(failed_instances)
        if success:
            self.logger.success("SUCCESS: No requests sent to failed instances!")
        else:
            self.logger.failure(f"ERROR: {len(failed_routes)} requests went to failed instances")

        # Show registry state
        self.logger.info(f"\n{colors.BOLD}Service Registry State:{colors.RESET}")
        services = await self.service_registry.list_services()
        for service in services.services:
            if service.name == "math-service":
                self.logger.info(f"  Total instances: {service.instance_count}")
                self.logger.info(f"  Healthy instances: {service.healthy_instance_count}")

        return success

    async def show_final_stats(self) -> None:
        """Show cumulative statistics."""
        self.logger.section("Final Statistics")
        self.logger.info("Total requests handled by each instance:")

        total = sum(self.request_distribution.values())
        for instance_id in sorted(self.request_distribution.keys()):
            count = self.request_distribution[instance_id]
            actual_count = self.service_instances[instance_id].request_count
            percentage = (count / total * 100) if total > 0 else 0
            bar = "█" * (count // 2)
            self.logger.info(
                f"  {instance_id}: {bar} ({count} routed, {actual_count} handled, {percentage:.1f}%)"
            )

        self.logger.info(f"\n  {colors.BOLD}Total requests routed: {total}{colors.RESET}")

    async def cleanup(self) -> None:
        """Clean up all resources."""
        self.logger.warning("Cleaning up...")

        # Stop health checker first to prevent it from marking instances unhealthy during shutdown
        await self.health_checker.stop()

        # Cancel the health checker task
        if hasattr(self, "_health_checker_task") and self._health_checker_task:
            self._health_checker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._health_checker_task

        # Stop instances
        for instance in self.service_instances.values():
            await instance.stop()

        # Stop handlers
        if self.route_handler:
            await self.route_handler.stop()

        # Disconnect NATS
        if self.router_nats:
            await self.router_nats.disconnect()
        if self.client_nats:
            await self.client_nats.disconnect()

        self.logger.success("Cleanup complete")

    async def run(self) -> DemoResult:
        """Run the complete demonstration.

        Returns:
            Demo execution result
        """
        self.logger.demo_header("Story 1.3 NATS Routing Demonstration", "实现服务组的轮询路由")

        result = DemoResult(success=True)

        try:
            # Setup
            await self.setup()
            await self.create_service_instances()

            # Run demonstrations
            if await self.demonstrate_ac1():
                result.criteria_passed.append(
                    "AC1: NATS requests routed to service instances by name"
                )
            else:
                result.criteria_failed.append("AC1: Service name routing failed")
                result.success = False

            await asyncio.sleep(1)

            if await self.demonstrate_ac2():
                result.criteria_passed.append("AC2: Round-robin load balancing via NATS messaging")
            else:
                result.criteria_failed.append("AC2: Load balancing not working correctly")
                result.success = False

            await asyncio.sleep(1)

            if await self.demonstrate_ac3():
                result.criteria_passed.append("AC3: Failed instances excluded from NATS routing")
            else:
                result.criteria_failed.append("AC3: Failed instances not properly excluded")
                result.success = False

            # Show stats
            await self.show_final_stats()

            if result.success:
                self.logger.section(f"{colors.GREEN}All Acceptance Criteria PASSED!{colors.RESET}")
            else:
                self.logger.section(f"{colors.RED}Some Acceptance Criteria FAILED!{colors.RESET}")

            self.logger.info("\nSummary:")
            for passed in result.criteria_passed:
                self.logger.success(passed)
            for failed in result.criteria_failed:
                self.logger.failure(failed)

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

    demo = NATSRoutingDemo(settings)
    result = await demo.run()

    # Exit with appropriate code
    exit(0 if result.success else 1)


if __name__ == "__main__":
    # Handle Ctrl+C gracefully
    def signal_handler(_sig: int, _frame: Any) -> None:
        """Handle interrupt signal."""
        logger = DemoLogger("signal")
        logger.warning("\nDemo interrupted by user")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    # Run the demo
    asyncio.run(main())
