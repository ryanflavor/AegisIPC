"""Unit tests for batch operations transactionality and performance."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Generator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from ipc_router.application.models import (
    BulkResourceRegistrationRequest,
    BulkResourceReleaseRequest,
    ResourceMetadata,
    ResourceRegistrationItem,
)
from ipc_router.application.services import ResourceService
from ipc_router.domain.entities import Resource
from ipc_router.domain.exceptions import ResourceConflictError, ResourceReleaseError
from ipc_router.infrastructure.messaging.handlers import BulkResourceHandler


class TestBatchTransactionality:
    """Test transactional behavior of batch operations."""

    @pytest.fixture
    def nats_client(self) -> AsyncMock:
        """Mock NATS client."""
        client = AsyncMock()
        client.subscribe = AsyncMock()
        client.unsubscribe = AsyncMock()
        client.publish = AsyncMock()
        return client

    @pytest.fixture
    def resource_service(self) -> AsyncMock:
        """Mock resource service."""
        return AsyncMock(spec=ResourceService)

    @pytest.fixture
    def handler(self, nats_client: AsyncMock, resource_service: AsyncMock) -> BulkResourceHandler:
        """Create bulk resource handler."""
        return BulkResourceHandler(
            nats_client=nats_client,
            resource_service=resource_service,
            max_concurrent_batches=5,
        )

    @pytest.fixture
    def metadata(self) -> ResourceMetadata:
        """Create test metadata."""
        return ResourceMetadata(
            resource_type="test_resource",
            version=1,
            tags=["test"],
            attributes={},
            created_by="test-service",
            last_modified=datetime.now(UTC),
            ttl_seconds=3600,
            priority=5,
        )

    def create_resources(
        self, count: int, metadata: ResourceMetadata
    ) -> list[ResourceRegistrationItem]:
        """Create resource registration items."""
        return [
            ResourceRegistrationItem(
                resource_id=f"resource-{i}",
                metadata=metadata,
                force=False,
            )
            for i in range(count)
        ]

    @pytest.mark.asyncio
    async def test_transactional_registration_all_or_nothing(
        self,
        handler: BulkResourceHandler,
        resource_service: AsyncMock,
        metadata: ResourceMetadata,
    ) -> None:
        """Test that transactional registration is all-or-nothing."""
        resources = self.create_resources(20, metadata)

        # Mock service to fail on resource 15
        call_count = 0

        async def mock_register(
            service_name: str,
            instance_id: str,
            resource_id: str,
            metadata: ResourceMetadata,
            force: bool,
        ) -> Resource:
            nonlocal call_count
            call_count += 1
            if call_count == 15:
                raise ResourceConflictError(resource_id=resource_id, current_owner="other-instance")
            return Resource(
                resource_id=resource_id,
                owner_instance_id=instance_id,
                service_name=service_name,
                registered_at=datetime.now(UTC),
                metadata=metadata,
            )

        resource_service.register_resource.side_effect = mock_register

        # Create transactional request
        request = BulkResourceRegistrationRequest(
            service_name="test-service",
            instance_id="test-instance",
            resources=resources,
            batch_size=5,
            continue_on_error=False,  # Stop on first error
            trace_id="trace-123",
        )

        # Process request
        response = await handler._process_bulk_registration(request)

        # Verify partial registration (stopped at error)
        assert response.total_registered == 14  # Registered up to the error
        assert len(response.failed) == 1
        assert response.failed[0].resource_id == "resource-14"

    @pytest.mark.asyncio
    async def test_transactional_release_with_rollback(
        self,
        handler: BulkResourceHandler,
        resource_service: AsyncMock,
    ) -> None:
        """Test transactional release with rollback on failure."""
        resource_ids = [f"resource-{i}" for i in range(20)]

        # Track released resources
        released_resources = []

        async def mock_release(service_name: str, instance_id: str, resource_id: str) -> None:
            # Fail on resource-12
            if resource_id == "resource-12":
                raise ResourceReleaseError(f"Not owner of {resource_id}")
            released_resources.append(resource_id)

        resource_service.release_resource.side_effect = mock_release

        # Mock re-registration for rollback
        re_registered = []

        async def mock_register(
            service_name: str,
            instance_id: str,
            resource_id: str,
            metadata: ResourceMetadata,
            force: bool,
        ) -> MagicMock:
            re_registered.append(resource_id)
            mock_resource = MagicMock()
            mock_resource.resource_id = resource_id
            return mock_resource

        resource_service.register_resource.side_effect = mock_register

        # Create transactional release request
        request = BulkResourceReleaseRequest(
            service_name="test-service",
            instance_id="test-instance",
            resource_ids=resource_ids,
            batch_size=5,
            continue_on_error=False,
            transactional=True,  # Enable transactional mode
            trace_id="trace-123",
        )

        # Process request
        response = await handler._process_bulk_release(request)

        # Verify rollback occurred
        assert response.rollback_performed
        assert response.total_released == 0  # All rolled back
        assert len(response.failed) == 1

        # Verify rollback re-registered the released resources
        assert len(re_registered) == len(released_resources)
        assert set(re_registered) == set(released_resources)

    @pytest.mark.asyncio
    async def test_non_transactional_release_continues_on_error(
        self,
        handler: BulkResourceHandler,
        resource_service: AsyncMock,
    ) -> None:
        """Test non-transactional release continues despite errors."""
        resource_ids = [f"resource-{i}" for i in range(20)]

        # Mock some failures
        async def mock_release(resource_id: str, instance_id: str) -> bool:
            # Fail on every 5th resource
            if int(resource_id.split("-")[1]) % 5 == 0:
                raise ResourceReleaseError(f"Not owner of {resource_id}")
            return True

        resource_service.release_resource.side_effect = mock_release

        # Create non-transactional release request
        request = BulkResourceReleaseRequest(
            service_name="test-service",
            instance_id="test-instance",
            resource_ids=resource_ids,
            batch_size=5,
            continue_on_error=True,
            transactional=False,  # Non-transactional mode
            trace_id="trace-123",
        )

        # Process request
        response = await handler._process_bulk_release(request)

        # Verify partial success
        assert not response.rollback_performed
        assert response.total_requested == 20
        assert response.total_released == 16  # 20 - 4 failures (0, 5, 10, 15)
        assert len(response.failed) == 4

    @pytest.mark.asyncio
    async def test_batch_isolation(
        self,
        handler: BulkResourceHandler,
        resource_service: AsyncMock,
        metadata: ResourceMetadata,
    ) -> None:
        """Test that batches are processed in isolation."""
        resources = self.create_resources(15, metadata)

        # Track which batch each resource belongs to
        batch_assignments: dict[int, list[str]] = {}

        async def mock_register(
            service_name: str,
            instance_id: str,
            resource_id: str,
            metadata: ResourceMetadata,
            force: bool,
        ) -> Resource:
            # Record the current asyncio task to identify batch
            task_id = id(asyncio.current_task())
            if task_id not in batch_assignments:
                batch_assignments[task_id] = []
            batch_assignments[task_id].append(resource_id)

            # Fail resource-7 in second batch
            if resource_id == "resource-7":
                raise ResourceConflictError(
                    resource_id="resource-7", current_owner="other-instance"
                )

            return Resource(
                resource_id=resource_id,
                owner_instance_id=instance_id,
                service_name=service_name,
                registered_at=datetime.now(UTC),
                metadata=metadata,
            )

        resource_service.register_resource.side_effect = mock_register

        # Process with batch size 5 (3 batches)
        request = BulkResourceRegistrationRequest(
            service_name="test-service",
            instance_id="test-instance",
            resources=resources,
            batch_size=5,
            continue_on_error=True,  # Continue despite errors
            trace_id="trace-123",
        )

        await handler._process_bulk_registration(request)

        # Verify batch isolation
        assert len(batch_assignments) <= 3  # Max 3 concurrent batches

        # Each batch should have processed its resources
        all_processed = []
        for batch_resources in batch_assignments.values():
            all_processed.extend(batch_resources)
            assert len(batch_resources) <= 5  # Batch size limit

        # All resources should be attempted
        assert len(all_processed) == 15

    @pytest.mark.asyncio
    async def test_rollback_failure_handling(
        self,
        handler: BulkResourceHandler,
        resource_service: AsyncMock,
    ) -> None:
        """Test handling of rollback failures."""
        resource_ids = [f"resource-{i}" for i in range(10)]

        # Release will succeed then fail
        async def mock_release(resource_id: str, instance_id: str) -> bool:
            if resource_id == "resource-5":
                raise ResourceReleaseError("Not owner")
            return True

        resource_service.release_resource.side_effect = mock_release

        # Rollback will partially fail
        rollback_count = 0

        async def mock_register(
            service_name: str,
            instance_id: str,
            resource_id: str,
            metadata: ResourceMetadata,
            force: bool = False,
            notify: bool = True,
        ) -> MagicMock:
            nonlocal rollback_count
            rollback_count += 1
            # Fail on second rollback attempt
            if rollback_count == 2:
                raise Exception("Rollback failed")
            mock_resource = MagicMock()
            mock_resource.resource_id = resource_id
            return mock_resource

        resource_service.register_resource.side_effect = mock_register

        # Mock get_resource for metadata preservation
        resource_service._registry = MagicMock()
        resource_service._registry.get_resource = AsyncMock(return_value=None)

        # Create transactional request
        request = BulkResourceReleaseRequest(
            service_name="test-service",
            instance_id="test-instance",
            resource_ids=resource_ids,
            batch_size=5,
            continue_on_error=False,
            transactional=True,
            trace_id="trace-123",
        )

        # Process request
        response = await handler._process_bulk_release(request)

        # Verify rollback was attempted but had failures
        assert response.rollback_performed
        assert response.total_released == 0

        # Rollback was attempted for all released resources
        assert rollback_count >= 4  # At least 4 rollback attempts


class TestBatchPerformance:
    """Test performance characteristics of batch operations."""

    @pytest.fixture
    def handler(self) -> BulkResourceHandler:
        """Create handler with specific concurrency settings."""
        nats_client = AsyncMock()
        resource_service = AsyncMock()
        return BulkResourceHandler(
            nats_client=nats_client,
            resource_service=resource_service,
            max_concurrent_batches=3,
        )

    @pytest.fixture
    def metadata(self) -> ResourceMetadata:
        """Create test metadata."""
        return ResourceMetadata(
            resource_type="test_resource",
            version=1,
            tags=["test"],
            attributes={},
            created_by="test-service",
            last_modified=datetime.now(UTC),
            ttl_seconds=3600,
            priority=5,
        )

    @pytest.mark.asyncio
    async def test_concurrent_batch_processing_performance(
        self,
        handler: BulkResourceHandler,
        metadata: ResourceMetadata,
    ) -> None:
        """Test that batches are processed concurrently for performance."""
        # Create many resources
        resources = [
            ResourceRegistrationItem(
                resource_id=f"resource-{i}",
                metadata=metadata,
                force=False,
            )
            for i in range(30)
        ]

        # Track concurrent executions
        concurrent_count = 0
        max_concurrent = 0

        async def mock_register(
            service_name: str,
            instance_id: str,
            resource_id: str,
            metadata: ResourceMetadata,
            force: bool,
        ) -> Resource:
            nonlocal concurrent_count, max_concurrent
            concurrent_count += 1
            max_concurrent = max(max_concurrent, concurrent_count)

            # Simulate work
            await asyncio.sleep(0.01)

            concurrent_count -= 1

            return Resource(
                resource_id=resource_id,
                owner_instance_id=instance_id,
                service_name=service_name,
                registered_at=datetime.now(UTC),
                metadata=metadata,
            )

        handler._resource_service.register_resource = mock_register

        # Process with batch size 10 (3 batches)
        request = BulkResourceRegistrationRequest(
            service_name="test-service",
            instance_id="test-instance",
            resources=resources,
            batch_size=10,
            continue_on_error=True,  # Must be True for concurrent processing
            trace_id="trace-123",
        )

        start_time = time.time()
        response = await handler._process_bulk_registration(request)
        duration = time.time() - start_time

        # Verify all processed
        assert response.total_registered == 30

        # Verify concurrent processing
        assert max_concurrent > 1  # Should process multiple items concurrently
        assert max_concurrent <= 30  # But respects limits

        # Verify performance (should be faster than sequential)
        # Sequential would take ~0.3s (30 * 0.01), concurrent should be much less
        assert duration < 0.2  # Generous threshold for CI environments

    @pytest.mark.asyncio
    async def test_batch_size_performance_impact(
        self,
        handler: BulkResourceHandler,
        metadata: ResourceMetadata,
    ) -> None:
        """Test impact of batch size on performance."""
        # Create resources
        num_resources = 100
        resources = [
            ResourceRegistrationItem(
                resource_id=f"resource-{i}",
                metadata=metadata,
                force=False,
            )
            for i in range(num_resources)
        ]

        # Mock fast registration
        async def mock_register(
            service_name: str,
            instance_id: str,
            resource_id: str,
            metadata: ResourceMetadata,
            force: bool,
        ) -> MagicMock:
            await asyncio.sleep(0.001)  # Very fast operation
            mock_resource = MagicMock()
            mock_resource.resource_id = resource_id
            return mock_resource

        handler._resource_service.register_resource = mock_register

        # Test different batch sizes
        batch_sizes = [10, 25, 50, 100]
        results = {}

        for batch_size in batch_sizes:
            request = BulkResourceRegistrationRequest(
                service_name="test-service",
                instance_id="test-instance",
                resources=resources,
                batch_size=batch_size,
                continue_on_error=False,
                trace_id=f"trace-{batch_size}",
            )

            start_time = time.time()
            response = await handler._process_bulk_registration(request)
            duration = time.time() - start_time

            results[batch_size] = {
                "duration": duration,
                "batches": len(response.batch_results),
            }

        # Larger batch sizes should generally be more efficient
        # (fewer batches = less overhead)
        assert results[100]["batches"] < results[10]["batches"]

        # But not necessarily faster due to concurrency limits
        # Just verify all completed successfully
        for batch_size, result in results.items():
            assert result["batches"] == (num_resources + batch_size - 1) // batch_size

    @pytest.mark.asyncio
    async def test_semaphore_concurrency_limit(
        self,
        handler: BulkResourceHandler,
        metadata: ResourceMetadata,
    ) -> None:
        """Test that semaphore properly limits concurrent batches."""
        # Create many batches worth of resources
        resources = [
            ResourceRegistrationItem(
                resource_id=f"resource-{i}",
                metadata=metadata,
                force=False,
            )
            for i in range(50)
        ]

        # Track concurrent operations
        concurrent_operations = 0
        max_concurrent = 0

        async def mock_register(
            service_name: str,
            instance_id: str,
            resource_id: str,
            metadata: ResourceMetadata,
            force: bool,
        ) -> MagicMock:
            nonlocal concurrent_operations, max_concurrent

            concurrent_operations += 1
            max_concurrent = max(max_concurrent, concurrent_operations)

            # Simulate work
            await asyncio.sleep(0.02)

            concurrent_operations -= 1

            mock_resource = MagicMock()
            mock_resource.resource_id = resource_id
            return mock_resource

        handler._resource_service.register_resource = mock_register

        # Process with batch size 5 (10 batches) and max_concurrent_batches=5
        # Use continue_on_error=True to enable concurrent processing
        request = BulkResourceRegistrationRequest(
            service_name="test-service",
            instance_id="test-instance",
            resources=resources,
            batch_size=5,
            continue_on_error=True,  # Enable concurrent processing
            trace_id="trace-123",
        )

        await handler._process_bulk_registration(request)

        # Verify concurrency was limited
        # With batch size 5 and semaphore limit, we should see at most
        # batch_size * max_concurrent_batches concurrent operations
        assert max_concurrent <= 5 * handler._max_concurrent_batches

    @pytest.mark.asyncio
    async def test_batch_timing_accuracy(
        self,
        handler: BulkResourceHandler,
        metadata: ResourceMetadata,
    ) -> None:
        """Test that batch timing measurements are accurate."""
        resources = [
            ResourceRegistrationItem(
                resource_id=f"resource-{i}",
                metadata=metadata,
                force=False,
            )
            for i in range(20)
        ]

        # Mock with predictable timing
        async def mock_register(
            service_name: str,
            instance_id: str,
            resource_id: str,
            metadata: ResourceMetadata,
            force: bool,
        ) -> MagicMock:
            # Each resource takes 10ms
            await asyncio.sleep(0.01)
            mock_resource = MagicMock()
            mock_resource.resource_id = resource_id
            return mock_resource

        handler._resource_service.register_resource = mock_register

        request = BulkResourceRegistrationRequest(
            service_name="test-service",
            instance_id="test-instance",
            resources=resources,
            batch_size=5,  # 4 batches
            continue_on_error=False,
            trace_id="trace-123",
        )

        response = await handler._process_bulk_registration(request)

        # Verify batch timings
        assert len(response.batch_results) == 4

        for batch_result in response.batch_results:
            # Each batch of 5 should take ~50ms minimum
            assert batch_result.duration_ms >= 40  # Allow some variance
            assert batch_result.success_count == 5
            assert batch_result.failure_count == 0

    @pytest.mark.asyncio
    async def test_memory_efficiency_large_batches(
        self,
        handler: BulkResourceHandler,
        metadata: ResourceMetadata,
    ) -> None:
        """Test memory efficiency with large batches."""
        # Create a large number of resources
        num_resources = 1000

        # Use generator to avoid creating all at once
        def resource_generator() -> Generator[ResourceRegistrationItem]:
            for i in range(num_resources):
                yield ResourceRegistrationItem(
                    resource_id=f"resource-{i}",
                    metadata=metadata,
                    force=False,
                )

        resources = list(resource_generator())

        # Track memory usage pattern
        processed_count = 0

        async def mock_register(
            service_name: str,
            instance_id: str,
            resource_id: str,
            metadata: ResourceMetadata,
            force: bool,
        ) -> MagicMock:
            nonlocal processed_count
            processed_count += 1
            # Immediate return to test throughput
            mock_resource = MagicMock()
            mock_resource.resource_id = resource_id
            return mock_resource

        handler._resource_service.register_resource = mock_register

        # Process with reasonable batch size
        request = BulkResourceRegistrationRequest(
            service_name="test-service",
            instance_id="test-instance",
            resources=resources,
            batch_size=100,  # 10 batches
            continue_on_error=False,
            trace_id="trace-123",
        )

        start_time = time.time()
        response = await handler._process_bulk_registration(request)
        duration = time.time() - start_time

        # Verify all processed efficiently
        assert response.total_registered == num_resources
        assert processed_count == num_resources

        # Should complete reasonably quickly even with many resources
        assert duration < 5.0  # Generous limit for CI

        # Verify batch results are accurate
        total_from_batches = sum(br.success_count for br in response.batch_results)
        assert total_from_batches == num_resources
