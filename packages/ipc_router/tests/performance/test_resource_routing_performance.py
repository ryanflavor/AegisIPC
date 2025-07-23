"""Performance and benchmark tests for resource routing."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from statistics import mean, median, stdev
from typing import Any

import pytest
import pytest_asyncio
from ipc_router.application.models import ResourceMetadata, RouteRequest
from ipc_router.application.services import (
    ResourceAwareRoutingService,
    ResourceRegistry,
    ResourceService,
    ServiceRegistry,
)
from ipc_router.domain.entities import ServiceInstance
from ipc_router.infrastructure.logging import get_logger
from ipc_router.infrastructure.messaging.handlers import BulkResourceHandler

logger = get_logger(__name__)


@pytest_asyncio.fixture
async def large_scale_setup() -> dict[str, object]:
    """Set up large-scale test environment."""
    service_registry = ServiceRegistry()
    resource_registry = ResourceRegistry(service_registry)
    resource_service = ResourceService(resource_registry)
    routing_service = ResourceAwareRoutingService(service_registry, resource_registry)

    # Register multiple service instances
    instances = []
    for i in range(10):
        instance = ServiceInstance(
            service_name="perf-service",
            instance_id=f"perf-instance-{i}",
            metadata={},
            registered_at=datetime.now(UTC),
        )
        await service_registry.register(instance)
        instances.append(instance)

    return {
        "service_registry": service_registry,
        "resource_registry": resource_registry,
        "resource_service": resource_service,
        "routing_service": routing_service,
        "instances": instances,
    }


def measure_operation_time(func: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator to measure async operation time."""

    async def wrapper(*args: Any, **kwargs: Any) -> tuple[Any, float]:
        start_time = time.perf_counter()
        result = await func(*args, **kwargs)
        end_time = time.perf_counter()
        return result, (end_time - start_time) * 1000  # Return time in milliseconds

    return wrapper


class TestResourceRoutingPerformance:
    """Performance tests for resource routing operations."""

    async def test_resource_registration_performance(
        self, large_scale_setup: dict[str, Any]
    ) -> None:
        """Test resource registration performance."""
        resource_service = large_scale_setup["resource_service"]
        instances = large_scale_setup["instances"]

        # Prepare metadata
        metadata = ResourceMetadata(
            resource_type="perf_test",
            version=1,
            tags=["benchmark"],
            attributes={},
            created_by="perf-test",
            last_modified=datetime.now(UTC),
            priority=5,
        )

        # Measure individual registration times
        registration_times = []

        @measure_operation_time
        async def register_single_resource(instance_id: str, resource_id: str) -> Any:
            return await resource_service.register_resource(
                service_name="perf-service",
                instance_id=instance_id,
                resource_id=resource_id,
                metadata=metadata,
            )

        # Register 1000 resources across instances
        for i in range(1000):
            instance = instances[i % len(instances)]
            resource_id = f"perf-resource-{i}"
            _, duration = await register_single_resource(instance.instance_id, resource_id)
            registration_times.append(duration)

        # Calculate statistics
        avg_time = mean(registration_times)
        median_time = median(registration_times)
        std_dev = stdev(registration_times) if len(registration_times) > 1 else 0

        # Performance assertions
        assert avg_time < 5.0  # Average registration should be < 5ms
        assert median_time < 3.0  # Median should be < 3ms

        logger.info(
            "Resource registration performance",
            extra={
                "avg_time_ms": avg_time,
                "median_time_ms": median_time,
                "std_dev_ms": std_dev,
                "total_resources": len(registration_times),
            },
        )

    async def test_resource_lookup_performance(self, large_scale_setup: dict[str, Any]) -> None:
        """Test resource lookup performance with O(1) complexity."""
        resource_service = large_scale_setup["resource_service"]
        resource_registry = large_scale_setup["resource_registry"]
        instances = large_scale_setup["instances"]

        # Pre-register many resources
        metadata = ResourceMetadata(
            resource_type="lookup_test",
            version=1,
            tags=["benchmark"],
            attributes={},
            created_by="perf-test",
            last_modified=datetime.now(UTC),
            priority=5,
        )

        # Register 10,000 resources
        resource_ids = []
        for i in range(10000):
            instance = instances[i % len(instances)]
            resource_id = f"lookup-resource-{i}"
            await resource_service.register_resource(
                service_name="perf-service",
                instance_id=instance.instance_id,
                resource_id=resource_id,
                metadata=metadata,
            )
            resource_ids.append(resource_id)

        # Measure lookup times
        lookup_times = []

        @measure_operation_time
        async def lookup_resource(resource_id: str) -> Any:
            return await resource_registry.get_resource_owner(resource_id)

        # Perform 1000 random lookups
        import random

        for _ in range(1000):
            resource_id = random.choice(resource_ids)
            _, duration = await lookup_resource(resource_id)
            lookup_times.append(duration)

        # Calculate statistics
        avg_time = mean(lookup_times)
        median_time = median(lookup_times)
        max_time = max(lookup_times)

        # O(1) performance assertions
        assert avg_time < 1.0  # Average lookup should be < 1ms
        assert median_time < 0.5  # Median should be < 0.5ms
        assert max_time < 5.0  # Even worst case should be < 5ms

        logger.info(
            "Resource lookup performance (O(1) verification)",
            extra={
                "avg_time_ms": avg_time,
                "median_time_ms": median_time,
                "max_time_ms": max_time,
                "total_lookups": len(lookup_times),
                "total_resources": len(resource_ids),
            },
        )

    async def test_resource_routing_performance(self, large_scale_setup: dict[str, Any]) -> None:
        """Test end-to-end routing performance with resources."""
        routing_service = large_scale_setup["routing_service"]
        resource_service = large_scale_setup["resource_service"]
        instances = large_scale_setup["instances"]

        # Pre-register resources
        metadata = ResourceMetadata(
            resource_type="routing_test",
            version=1,
            tags=["benchmark"],
            attributes={},
            created_by="perf-test",
            last_modified=datetime.now(UTC),
            priority=5,
        )

        resource_ids = []
        for i in range(1000):
            instance = instances[i % len(instances)]
            resource_id = f"routing-resource-{i}"
            await resource_service.register_resource(
                service_name="perf-service",
                instance_id=instance.instance_id,
                resource_id=resource_id,
                metadata=metadata,
            )
            resource_ids.append(resource_id)

        # Measure routing times
        routing_times = []

        @measure_operation_time
        async def route_request(resource_id: str) -> Any:
            request = RouteRequest(
                service_name="perf-service",
                resource_id=resource_id,
                method="test_method",
                params={},
                timeout=5.0,
                trace_id=f"trace-{uuid.uuid4().hex[:16]}",
            )
            return await routing_service.select_instance(request)

        # Perform routing requests
        import random

        for _ in range(1000):
            resource_id = random.choice(resource_ids)
            _, duration = await route_request(resource_id)
            routing_times.append(duration)

        # Calculate statistics
        avg_time = mean(routing_times)
        p99_time = sorted(routing_times)[int(len(routing_times) * 0.99)]

        # Performance assertions
        assert avg_time < 2.0  # Average routing should be < 2ms
        assert p99_time < 5.0  # 99th percentile should be < 5ms

        logger.info(
            "Resource routing performance",
            extra={
                "avg_time_ms": avg_time,
                "p99_time_ms": p99_time,
                "total_requests": len(routing_times),
            },
        )

    async def test_bulk_registration_performance(self, large_scale_setup: dict[str, Any]) -> None:
        """Test bulk resource registration performance."""
        resource_service = large_scale_setup["resource_service"]

        # Create bulk handler with mock NATS
        from unittest.mock import AsyncMock

        mock_nats = AsyncMock()
        bulk_handler = BulkResourceHandler(
            nats_client=mock_nats,
            resource_service=resource_service,
            max_concurrent_batches=5,
        )

        # Prepare bulk registration data
        from ipc_router.application.models import (
            BulkResourceRegistrationRequest,
            ResourceRegistrationItem,
        )

        metadata = ResourceMetadata(
            resource_type="bulk_test",
            version=1,
            tags=["benchmark"],
            attributes={},
            created_by="perf-test",
            last_modified=datetime.now(UTC),
            priority=5,
        )

        # Create 1000 resources for bulk registration
        resources = [
            ResourceRegistrationItem(
                resource_id=f"bulk-resource-{i}",
                metadata=metadata,
                force=False,
            )
            for i in range(1000)
        ]

        request = BulkResourceRegistrationRequest(
            service_name="perf-service",
            instance_id="perf-instance-0",
            resources=resources,
            batch_size=100,
            continue_on_error=False,
            trace_id="trace-bulk-perf",
        )

        # Measure bulk registration time
        start_time = time.perf_counter()
        response = await bulk_handler._process_bulk_registration(request)
        end_time = time.perf_counter()
        total_time = (end_time - start_time) * 1000

        # Calculate per-resource time
        per_resource_time = total_time / len(resources)

        # Performance assertions
        assert total_time < 1000  # Total time for 1000 resources < 1 second
        assert per_resource_time < 1.0  # Average < 1ms per resource

        # Verify batch performance
        batch_times = [result.duration_ms for result in response.batch_results]
        avg_batch_time = mean(batch_times)
        assert avg_batch_time < 100  # Average batch (100 resources) < 100ms

        logger.info(
            "Bulk registration performance",
            extra={
                "total_time_ms": total_time,
                "per_resource_ms": per_resource_time,
                "avg_batch_time_ms": avg_batch_time,
                "total_resources": len(resources),
                "batch_count": len(response.batch_results),
            },
        )

    async def test_concurrent_operations_performance(
        self, large_scale_setup: dict[str, Any]
    ) -> None:
        """Test performance under high concurrency."""
        resource_service = large_scale_setup["resource_service"]
        routing_service = large_scale_setup["routing_service"]
        instances = large_scale_setup["instances"]

        metadata = ResourceMetadata(
            resource_type="concurrent_test",
            version=1,
            tags=["benchmark"],
            attributes={},
            created_by="perf-test",
            last_modified=datetime.now(UTC),
            priority=5,
        )

        # Define concurrent operations
        async def concurrent_operation(op_id: int) -> dict[str, float]:
            # Registration
            resource_id = f"concurrent-{op_id}"
            instance = instances[op_id % len(instances)]

            start = time.perf_counter()
            await resource_service.register_resource(
                service_name="perf-service",
                instance_id=instance.instance_id,
                resource_id=resource_id,
                metadata=metadata,
            )
            reg_time = (time.perf_counter() - start) * 1000

            # Routing
            start = time.perf_counter()
            request = RouteRequest(
                service_name="perf-service",
                resource_id=resource_id,
                method="test",
                params={},
                timeout=5.0,
                trace_id=f"trace-{op_id}",
            )
            await routing_service.select_instance(request)
            route_time = (time.perf_counter() - start) * 1000

            # Release
            start = time.perf_counter()
            await resource_service.release_resource(
                service_name="perf-service",
                instance_id=instance.instance_id,
                resource_id=resource_id,
            )
            release_time = (time.perf_counter() - start) * 1000

            return {
                "registration": reg_time,
                "routing": route_time,
                "release": release_time,
            }

        # Run concurrent operations
        start_time = time.perf_counter()
        tasks = [concurrent_operation(i) for i in range(100)]
        results = await asyncio.gather(*tasks)
        total_time = (time.perf_counter() - start_time) * 1000

        # Analyze results
        reg_times = [r["registration"] for r in results]
        route_times = [r["routing"] for r in results]
        release_times = [r["release"] for r in results]

        # Performance assertions under concurrency
        assert mean(reg_times) < 10.0  # Registration avg < 10ms under load
        assert mean(route_times) < 5.0  # Routing avg < 5ms under load
        assert mean(release_times) < 10.0  # Release avg < 10ms under load
        assert total_time < 1000  # 100 concurrent operations < 1 second

        logger.info(
            "Concurrent operations performance",
            extra={
                "total_time_ms": total_time,
                "concurrent_ops": len(results),
                "avg_registration_ms": mean(reg_times),
                "avg_routing_ms": mean(route_times),
                "avg_release_ms": mean(release_times),
            },
        )

    @pytest.mark.parametrize("num_resources", [100, 1000, 10000])
    async def test_scalability_with_resource_count(
        self, large_scale_setup: dict[str, Any], num_resources: int
    ) -> None:
        """Test system scalability with increasing resource counts."""
        resource_service = large_scale_setup["resource_service"]
        resource_registry = large_scale_setup["resource_registry"]
        instances = large_scale_setup["instances"]

        metadata = ResourceMetadata(
            resource_type="scalability_test",
            version=1,
            tags=["benchmark"],
            attributes={},
            created_by="perf-test",
            last_modified=datetime.now(UTC),
            priority=5,
        )

        # Register resources and measure time
        start_time = time.perf_counter()
        for i in range(num_resources):
            instance = instances[i % len(instances)]
            await resource_service.register_resource(
                service_name="perf-service",
                instance_id=instance.instance_id,
                resource_id=f"scale-resource-{i}",
                metadata=metadata,
            )
        registration_time = (time.perf_counter() - start_time) * 1000

        # Measure lookup performance at scale
        lookup_times = []
        for i in range(min(100, num_resources)):
            start = time.perf_counter()
            await resource_registry.get_resource_owner(f"scale-resource-{i}")
            lookup_times.append((time.perf_counter() - start) * 1000)

        avg_lookup = mean(lookup_times)

        # Performance should remain consistent regardless of scale
        assert avg_lookup < 2.0  # Lookup should stay < 2ms even at scale

        logger.info(
            f"Scalability test with {num_resources} resources",
            extra={
                "num_resources": num_resources,
                "total_registration_time_ms": registration_time,
                "avg_lookup_time_ms": avg_lookup,
                "per_resource_registration_ms": registration_time / num_resources,
            },
        )
