"""End-to-end tests with real NATS cluster and multiple service instances."""

from __future__ import annotations

import asyncio
import os
import subprocess
import time
from collections import defaultdict
from datetime import UTC, datetime

import pytest
from ipc_client_sdk import ServiceClient as IPCClient
from ipc_router.application.services import HealthChecker, RoutingService, ServiceRegistry
from ipc_router.infrastructure.messaging import NATSClient
from ipc_router.infrastructure.messaging.handlers import RegistrationHandler
from ipc_router.infrastructure.messaging.handlers import RouteRequestHandler as RouteHandler


@pytest.mark.e2e
@pytest.mark.skipif(
    os.environ.get("RUN_E2E_TESTS", "false").lower() != "true",
    reason="E2E tests require RUN_E2E_TESTS=true environment variable",
)
class TestE2ENATSCluster:
    """End-to-end tests with real NATS cluster."""

    @classmethod
    def setup_class(cls) -> None:
        """Start the test environment."""
        # Start docker-compose test environment
        compose_file = os.path.join(
            os.path.dirname(__file__), "..", "environments", "docker-compose.test.yaml"
        )

        print("Starting test environment...")
        subprocess.run(
            ["docker-compose", "-f", compose_file, "down", "-v"],
            check=False,
            capture_output=True,
        )
        subprocess.run(
            ["docker-compose", "-f", compose_file, "up", "-d"],
            check=True,
            capture_output=True,
        )

        # Wait for NATS to be ready
        print("Waiting for NATS to be ready...")
        time.sleep(10)

    @classmethod
    def teardown_class(cls) -> None:
        """Stop the test environment."""
        compose_file = os.path.join(
            os.path.dirname(__file__), "..", "environments", "docker-compose.test.yaml"
        )

        print("Stopping test environment...")
        subprocess.run(
            ["docker-compose", "-f", compose_file, "down", "-v"],
            check=True,
            capture_output=True,
        )

    @pytest.mark.asyncio
    async def test_multi_instance_load_balancing(self) -> None:
        """Test load balancing across multiple real service instances."""
        # Connect to test NATS server
        nats_url = os.environ.get("NATS_TEST_URL", "nats://localhost:4223")

        async with IPCClient(nats_urls=[nats_url]) as client:
            # Wait for services to register
            await asyncio.sleep(5)

            # Send many requests to verify load balancing
            results: dict[str, int] = defaultdict(int)
            num_requests = 30

            for i in range(num_requests):
                try:
                    response = await client.call(
                        service="multi-instance-service",
                        method="ping",
                        params={"id": i},
                        timeout=5.0,
                    )

                    # Track which instance handled the request
                    if "instance_id" in response:
                        results[response["instance_id"]] += 1
                except Exception as e:
                    print(f"Request {i} failed: {e}")

            # Verify load is distributed
            print(f"Load distribution: {dict(results)}")

            # Should have responses from all 3 instances
            assert len(results) == 3

            # Each instance should handle roughly equal load (±20%)
            expected_per_instance = num_requests / 3
            for _instance_id, count in results.items():
                assert abs(count - expected_per_instance) <= expected_per_instance * 0.2

    @pytest.mark.asyncio
    async def test_instance_failure_recovery(self) -> None:
        """Test system behavior when instances fail."""
        nats_url = os.environ.get("NATS_TEST_URL", "nats://localhost:4223")

        # Set up router components
        nats_client = NATSClient([nats_url])
        await nats_client.connect()

        registry = ServiceRegistry()
        routing_service = RoutingService(registry)
        health_checker = HealthChecker(
            registry,
            check_interval=1.0,  # 1 second checks
            heartbeat_timeout=3.0,  # 3 second timeout
        )

        # Start handlers
        route_handler = RouteHandler(nats_client, routing_service)
        reg_handler = RegistrationHandler(nats_client, registry)

        await route_handler.start()
        await reg_handler.start()
        await health_checker.start()

        try:
            # Kill one instance
            print("Killing test-service-2...")
            subprocess.run(
                ["docker", "kill", "aegis-test-service-2"],
                check=True,
                capture_output=True,
            )

            # Wait for health checker to detect failure
            await asyncio.sleep(5)

            # Send requests - should only go to healthy instances
            async with IPCClient(nats_urls=[nats_url]) as client:
                results: dict[str, int] = defaultdict(int)

                for i in range(20):
                    try:
                        response = await client.call(
                            service="multi-instance-service",
                            method="ping",
                            params={"id": i},
                            timeout=5.0,
                        )

                        if "instance_id" in response:
                            results[response["instance_id"]] += 1
                    except Exception as e:
                        print(f"Request {i} failed: {e}")

                print(f"Load distribution after failure: {dict(results)}")

                # Should only have 2 instances responding
                assert len(results) == 2
                assert "test-service-2" not in results

                # Restart the failed instance
                print("Restarting test-service-2...")
                subprocess.run(
                    ["docker", "start", "aegis-test-service-2"],
                    check=True,
                    capture_output=True,
                )

                # Wait for recovery
                await asyncio.sleep(10)

                # Send more requests - should now include all instances
                results_after_recovery: dict[str, int] = defaultdict(int)

                for i in range(30):
                    try:
                        response = await client.call(
                            service="multi-instance-service",
                            method="ping",
                            params={"id": i},
                            timeout=5.0,
                        )

                        if "instance_id" in response:
                            results_after_recovery[response["instance_id"]] += 1
                    except Exception as e:
                        print(f"Request {i} failed: {e}")

                print(f"Load distribution after recovery: {dict(results_after_recovery)}")

                # Should have all 3 instances again
                assert len(results_after_recovery) == 3

        finally:
            await health_checker.stop()
            await route_handler.stop()
            await reg_handler.stop()
            await nats_client.disconnect()

    @pytest.mark.asyncio
    async def test_network_partition_simulation(self) -> None:
        """Test behavior during network partitions."""
        nats_url = os.environ.get("NATS_TEST_URL", "nats://localhost:4223")

        async with IPCClient(nats_urls=[nats_url]) as client:
            # Simulate network partition by adding latency
            print("Adding network latency to test-service-1...")
            subprocess.run(
                [
                    "docker",
                    "exec",
                    "aegis-test-service-1",
                    "tc",
                    "qdisc",
                    "add",
                    "dev",
                    "eth0",
                    "root",
                    "netem",
                    "delay",
                    "500ms",
                    "50ms",  # 500ms ± 50ms delay
                ],
                check=False,  # May fail if tc not available
                capture_output=True,
            )

            try:
                # Send requests and measure response times
                response_times = []

                for i in range(10):
                    start = datetime.now(UTC)
                    try:
                        await client.call(
                            service="multi-instance-service",
                            method="ping",
                            params={"id": i},
                            timeout=2.0,
                        )
                        elapsed = (datetime.now(UTC) - start).total_seconds()
                        response_times.append(elapsed)
                    except TimeoutError:
                        print(f"Request {i} timed out")

                # Some requests should be fast (from healthy instances)
                fast_responses = [t for t in response_times if t < 0.5]
                assert len(fast_responses) > 0

            finally:
                # Remove network latency
                print("Removing network latency...")
                subprocess.run(
                    [
                        "docker",
                        "exec",
                        "aegis-test-service-1",
                        "tc",
                        "qdisc",
                        "del",
                        "dev",
                        "eth0",
                        "root",
                    ],
                    check=False,
                    capture_output=True,
                )

    @pytest.mark.asyncio
    async def test_sustained_load_performance(self) -> None:
        """Test system performance under sustained load."""
        nats_url = os.environ.get("NATS_TEST_URL", "nats://localhost:4223")

        async with IPCClient(nats_urls=[nats_url]) as client:
            # Warm up
            for _ in range(10):
                await client.call(
                    service="multi-instance-service",
                    method="ping",
                    params={},
                    timeout=5.0,
                )

            # Measure performance under load
            num_requests = 1000
            response_times = []
            errors = 0

            print(f"Sending {num_requests} requests...")
            start_time = datetime.now(UTC)

            # Use semaphore to limit concurrent requests
            semaphore = asyncio.Semaphore(50)  # 50 concurrent requests max

            async def send_request(request_id: int) -> tuple[float | None, Exception | None]:
                async with semaphore:
                    req_start = datetime.now(UTC)
                    try:
                        await client.call(
                            service="multi-instance-service",
                            method="process",
                            params={"id": request_id, "data": "x" * 100},
                            timeout=5.0,
                        )
                        elapsed = (datetime.now(UTC) - req_start).total_seconds()
                        return (elapsed, None)
                    except Exception as e:
                        return (None, e)

            # Send requests concurrently
            tasks = [send_request(i) for i in range(num_requests)]
            results = await asyncio.gather(*tasks)

            end_time = datetime.now(UTC)
            total_time = (end_time - start_time).total_seconds()

            # Analyze results
            for elapsed, error in results:
                if error:
                    errors += 1
                elif elapsed:
                    response_times.append(elapsed)

            # Calculate metrics
            if response_times:
                response_times.sort()
                p50 = response_times[int(len(response_times) * 0.5)]
                p95 = response_times[int(len(response_times) * 0.95)]
                p99 = response_times[int(len(response_times) * 0.99)]

                print("\nPerformance Results:")
                print(f"Total requests: {num_requests}")
                print(f"Successful: {len(response_times)}")
                print(f"Errors: {errors}")
                print(f"Total time: {total_time:.2f}s")
                print(f"Throughput: {num_requests / total_time:.2f} req/s")
                print(f"P50 latency: {p50 * 1000:.2f}ms")
                print(f"P95 latency: {p95 * 1000:.2f}ms")
                print(f"P99 latency: {p99 * 1000:.2f}ms")

                # Performance assertions
                assert errors / num_requests < 0.01  # Less than 1% error rate
                assert p99 < 0.1  # P99 under 100ms
                assert num_requests / total_time > 100  # At least 100 req/s

    @pytest.mark.asyncio
    async def test_chaos_instance_cycling(self) -> None:
        """Test system stability when instances are constantly cycling."""
        nats_url = os.environ.get("NATS_TEST_URL", "nats://localhost:4223")

        # Start a background task that cycles instances
        cycling = True
        errors = []

        async def cycle_instances() -> None:
            """Randomly stop and start instances."""
            instances = ["aegis-test-service-1", "aegis-test-service-2", "aegis-test-service-3"]
            cycle_count = 0

            while cycling and cycle_count < 5:
                # Pick a random instance to cycle
                import random

                instance = random.choice(instances)

                try:
                    print(f"Cycling {instance}...")
                    # Stop instance
                    subprocess.run(
                        ["docker", "stop", instance],
                        check=True,
                        capture_output=True,
                    )

                    # Wait a bit
                    await asyncio.sleep(3)

                    # Start instance
                    subprocess.run(
                        ["docker", "start", instance],
                        check=True,
                        capture_output=True,
                    )

                    # Wait for it to register
                    await asyncio.sleep(5)

                except Exception as e:
                    errors.append(f"Failed to cycle {instance}: {e}")

                cycle_count += 1
                await asyncio.sleep(5)

        # Start cycling task
        cycle_task = asyncio.create_task(cycle_instances())

        try:
            async with IPCClient(nats_urls=[nats_url]) as client:
                # Send continuous requests during cycling
                successful_requests = 0
                failed_requests = 0

                for i in range(100):
                    try:
                        await client.call(
                            service="multi-instance-service",
                            method="ping",
                            params={"id": i},
                            timeout=3.0,
                        )
                        successful_requests += 1
                    except Exception as e:
                        failed_requests += 1
                        print(f"Request {i} failed during chaos: {e}")

                    await asyncio.sleep(0.1)  # Small delay between requests

                print("\nChaos test results:")
                print(f"Successful requests: {successful_requests}")
                print(f"Failed requests: {failed_requests}")
                print(f"Success rate: {successful_requests / 100 * 100:.1f}%")

                # System should maintain reasonable availability even during chaos
                assert successful_requests / 100 > 0.8  # At least 80% success rate

        finally:
            cycling = False
            await cycle_task
