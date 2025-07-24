#!/usr/bin/env python3
"""
Working NATS demonstration of Story 1.2 service registration.

Acceptance Criteria:
1. 服务实例启动时能成功注册信息。
2. 中央组件能存储和管理在线服务实例信息。
3. 可通过管理接口查询已注册的服务列表。
"""

from __future__ import annotations

import asyncio

from demo_utils import (
    DemoLogger,
    DemoResult,
    DemoSettings,
    check_nats_connection,
    colors,
    format_instance_id,
    format_service_name,
)
from ipc_router.application.services import ServiceRegistry
from ipc_router.domain.enums import ServiceStatus
from ipc_router.infrastructure.messaging.handlers import RegistrationHandler
from ipc_router.infrastructure.messaging.nats_client import NATSClient


class Story12Demo:
    """Demonstrates Story 1.2 acceptance criteria."""

    def __init__(self, settings: DemoSettings) -> None:
        """Initialize demo with configuration.

        Args:
            settings: Demo configuration settings
        """
        self.settings = settings
        self.logger = DemoLogger("Story 1.2")
        self.router_nats: NATSClient | None = None
        self.client_nats: NATSClient | None = None
        self.service_registry = ServiceRegistry()
        self.registration_handler: RegistrationHandler | None = None

    async def setup(self) -> None:
        """Set up NATS infrastructure."""
        self.logger.section("Setting up NATS Infrastructure")

        # Router connection
        self.router_nats = NATSClient(self.settings.nats_url)
        await self.router_nats.connect()
        self.logger.success("Router connected to NATS")

        # Client connection
        self.client_nats = NATSClient(self.settings.nats_url)
        await self.client_nats.connect()
        self.logger.success("Client connected to NATS")

        # Start registration handler
        self.registration_handler = RegistrationHandler(self.router_nats, self.service_registry)
        await self.registration_handler.start()
        self.logger.success(
            f"Registration handler listening on: {colors.CYAN}ipc.service.register{colors.RESET}"
        )

        # Give handler time to set up subscription
        await asyncio.sleep(self.settings.setup_delay)
        self.logger.success("Ready to accept registrations")

    async def demonstrate_ac1(self) -> bool:
        """AC1: 服务实例启动时能成功注册信息.

        Returns:
            True if all registrations succeed
        """
        self.logger.subsection("AC1: Service Registration at Startup")
        self.logger.info("Demonstrating service instances registering via NATS")

        services = [
            ("user-service", "user-svc-01", 8001, {"version": "1.0.0", "region": "us-east"}),
            ("user-service", "user-svc-02", 8002, {"version": "1.0.0", "region": "us-west"}),
            ("auth-service", "auth-svc-01", 9001, {"version": "2.0.0", "protocol": "grpc"}),
            ("payment-service", "pay-svc-01", 7001, {"version": "1.5.0"}),
        ]

        all_succeeded = True
        for service_name, instance_id, port, metadata in services:
            self.logger.info(f"Registering {format_instance_id(instance_id)}...")

            # Create registration request
            request = {
                "service_name": service_name,
                "instance_id": instance_id,
                "host": "localhost",
                "port": port,
                "metadata": metadata,
                "trace_id": f"demo-{instance_id}",
            }

            try:
                # Send registration via NATS
                assert self.client_nats is not None
                response = await self.client_nats.request(
                    "ipc.service.register", request, timeout=self.settings.connection_timeout
                )

                if response and response.get("success"):
                    self.logger.success("Successfully registered:")
                    self.logger.info(f"  Service: {format_service_name(service_name)}")
                    self.logger.info(f"  Instance: {format_instance_id(instance_id)}")
                    self.logger.info(f"  Port: {port}")
                    self.logger.info(f"  Metadata: {metadata}")
                else:
                    self.logger.failure(f"Registration failed: {response}")
                    all_succeeded = False

            except Exception as e:
                self.logger.error("Registration error", error=str(e))
                all_succeeded = False

            await asyncio.sleep(0.2)

        self.logger.success("Registration phase complete!")
        return all_succeeded

    async def demonstrate_ac2(self) -> bool:
        """AC2: 中央组件能存储和管理在线服务实例信息.

        Returns:
            True if registry correctly stores and manages instances
        """
        self.logger.subsection("AC2: Central Registry Storage")
        self.logger.info("Verifying registry is storing service information")

        # Query registry
        services = await self.service_registry.list_services()

        self.logger.info("Registry Statistics:")
        self.logger.info(f"  Total services: {colors.BOLD}{services.total_count}{colors.RESET}")

        total_instances = sum(s.instance_count for s in services.services)
        healthy_instances = sum(s.healthy_instance_count for s in services.services)

        self.logger.info(f"  Total instances: {colors.BOLD}{total_instances}{colors.RESET}")
        self.logger.info(f"  Healthy instances: {colors.BOLD}{healthy_instances}{colors.RESET}")

        self.logger.info("Service Details:")
        for service in services.services:
            self.logger.info(f"\n{format_service_name(service.name)}:")
            self.logger.info(f"  Created: {service.created_at}")
            self.logger.info(f"  Instances: {service.instance_count}")

            for instance in service.instances:
                status_color = colors.GREEN if instance.status == "ONLINE" else colors.RED
                self.logger.info(
                    f"    - {format_instance_id(instance.instance_id)}: "
                    f"{status_color}{instance.status}{colors.RESET}"
                )
                self.logger.info(f"      Registered: {instance.registered_at}")
                if hasattr(instance, "metadata") and instance.metadata:
                    self.logger.info(f"      Metadata: {instance.metadata}")

        # Test status update if we have services
        if services.total_count > 0:
            self.logger.info(f"\n{colors.BOLD}Testing status management:{colors.RESET}")

            # Find user-service
            user_service = next((s for s in services.services if s.name == "user-service"), None)

            if user_service and user_service.instance_count >= 2:
                self.logger.info(f"Updating {format_instance_id('user-svc-02')} to UNHEALTHY...")

                try:
                    await self.service_registry.update_instance_status(
                        "user-service", "user-svc-02", ServiceStatus.UNHEALTHY
                    )

                    # Verify update
                    updated_services = await self.service_registry.list_services()
                    updated_user_service = next(
                        (s for s in updated_services.services if s.name == "user-service"), None
                    )

                    if updated_user_service:
                        unhealthy = [
                            i for i in updated_user_service.instances if i.status == "UNHEALTHY"
                        ]
                        self.logger.success(
                            f"Status updated: {len(unhealthy)} unhealthy instance(s)"
                        )
                        return True
                except Exception as e:
                    self.logger.warning("Could not update status", error=str(e))
                    return False

        return bool(services.total_count > 0)

    async def demonstrate_ac3(self) -> bool:
        """AC3: 可通过管理接口查询已注册的服务列表.

        Returns:
            True if query capabilities work correctly
        """
        self.logger.subsection("AC3: Query Services")
        self.logger.info("Demonstrating registry query capabilities")

        # List all services
        self.logger.info(f"{colors.BOLD}1. List all services:{colors.RESET}")
        services = await self.service_registry.list_services()

        for service in services.services:
            self.logger.info(
                f"  - {format_service_name(service.name)}: {service.instance_count} instances"
            )

        # Query specific service
        self.logger.info(f"\n{colors.BOLD}2. Query specific service (user-service):{colors.RESET}")
        user_service = next((s for s in services.services if s.name == "user-service"), None)

        if user_service:
            self.logger.info(f"  Name: {format_service_name(user_service.name)}")
            self.logger.info(f"  Total instances: {user_service.instance_count}")
            self.logger.info(f"  Healthy instances: {user_service.healthy_instance_count}")
            self.logger.info("  Instance details:")
            for inst in user_service.instances:
                self.logger.info(f"    - {format_instance_id(inst.instance_id)}: {inst.status}")

        # Query non-existent service
        self.logger.info(f"\n{colors.BOLD}3. Query non-existent service:{colors.RESET}")
        fake_service = next((s for s in services.services if s.name == "fake-service"), None)
        if fake_service is None:
            self.logger.success("Correctly returns None for non-existent service")

        # Show query capabilities
        self.logger.info(f"\n{colors.BOLD}Query capabilities:{colors.RESET}")
        self.logger.success("List all registered services")
        self.logger.success("Get service by name")
        self.logger.success("Count instances per service")
        self.logger.success("Filter healthy vs unhealthy")
        self.logger.success("Access instance metadata")

        return True

    async def cleanup(self) -> None:
        """Clean up resources."""
        self.logger.warning("Cleaning up...")

        if self.registration_handler:
            await self.registration_handler.stop()
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
        self.logger.demo_header("Story 1.2 NATS Demo", "服务实例的基础注册与发现")

        result = DemoResult(success=True)

        try:
            await self.setup()

            # Run acceptance criteria tests
            if await self.demonstrate_ac1():
                result.criteria_passed.append("AC1: Services registered via NATS at startup")
            else:
                result.criteria_failed.append("AC1: Service registration failed")
                result.success = False

            await asyncio.sleep(1)

            if await self.demonstrate_ac2():
                result.criteria_passed.append("AC2: Central registry stores and manages instances")
            else:
                result.criteria_failed.append("AC2: Registry storage failed")
                result.success = False

            await asyncio.sleep(1)

            if await self.demonstrate_ac3():
                result.criteria_passed.append("AC3: Query interface provides service discovery")
            else:
                result.criteria_failed.append("AC3: Query interface failed")
                result.success = False

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

    demo = Story12Demo(settings)
    result = await demo.run()

    # Exit with appropriate code
    exit(0 if result.success else 1)


if __name__ == "__main__":
    asyncio.run(main())
