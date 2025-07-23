"""Unit tests for resource uniqueness constraints and concurrency."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from ipc_client_sdk.models.service_models import ServiceRegistrationRequest
from ipc_router.application.services import ResourceRegistry
from ipc_router.domain.entities import ResourceMetadata, ServiceInstance
from ipc_router.domain.enums import ServiceStatus
from ipc_router.domain.exceptions import ResourceConflictError, ResourceNotFoundError


class TestResourceConcurrency:
    """Test resource uniqueness constraints and concurrent operations."""

    @pytest.fixture
    def registry(self) -> ResourceRegistry:
        """Create a ResourceRegistry instance."""
        return ResourceRegistry()

    @pytest.fixture
    def metadata(self) -> ResourceMetadata:
        """Create test resource metadata."""
        return ResourceMetadata(
            resource_type="test_resource",
            version=1,
            created_by="test-service",
            last_modified=datetime.now(UTC),
            ttl_seconds=3600,
        )

    async def create_instances(
        self, registry: ResourceRegistry, count: int
    ) -> list[ServiceInstance]:
        """Create and register multiple service instances."""
        instances = []
        for i in range(count):
            instance = ServiceInstance(
                service_name="test-service",
                instance_id=f"instance-{i}",
                status=ServiceStatus.ONLINE,
                registered_at=datetime.now(UTC),
            )
            request = ServiceRegistrationRequest(
                service_name="test-service", instance_id=instance.instance_id, metadata={}
            )
            await registry.register_service(request)
            instances.append(instance)
        return instances

    @pytest.mark.asyncio
    async def test_concurrent_same_resource_registration(
        self, registry: ResourceRegistry, metadata: ResourceMetadata
    ) -> None:
        """Test concurrent registration of the same resource ID from different instances."""
        # Create multiple instances
        _ = await self.create_instances(registry, 5)

        # Define concurrent registration tasks
        resource_id = "resource-1"

        async def register_resource(instance_id: str) -> bool:
            """Try to register a resource."""
            try:
                await registry.register_resource(
                    resource_id=resource_id,
                    owner_instance_id=instance_id,
                    service_name="test-service",
                    metadata=metadata,
                    force=False,
                )
                return True
            except ResourceConflictError:
                return False

        # Create concurrent tasks
        tasks = [asyncio.create_task(register_resource(f"instance-{i}")) for i in range(5)]

        # Wait for all tasks to complete
        results = await asyncio.gather(*tasks)

        # Only one instance should succeed
        assert sum(results) == 1
        assert results.count(True) == 1
        assert results.count(False) == 4

        # Verify the resource is registered to exactly one instance
        owner = await registry.get_resource_owner(resource_id)
        assert owner is not None
        assert owner.startswith("instance-")

    @pytest.mark.asyncio
    async def test_concurrent_different_resource_registration(
        self, registry: ResourceRegistry, metadata: ResourceMetadata
    ) -> None:
        """Test concurrent registration of different resources."""
        # Create multiple instances
        _ = await self.create_instances(registry, 5)

        # Define concurrent registration tasks for different resources
        async def register_resource(instance_id: str, resource_id: str) -> bool:
            """Try to register a resource."""
            try:
                await registry.register_resource(
                    resource_id=resource_id,
                    owner_instance_id=instance_id,
                    service_name="test-service",
                    metadata=metadata,
                    force=False,
                )
                return True
            except ResourceConflictError:
                return False

        # Create concurrent tasks - each instance registers a different resource
        tasks = [
            asyncio.create_task(register_resource(f"instance-{i}", f"resource-{i}"))
            for i in range(5)
        ]

        # Wait for all tasks to complete
        results = await asyncio.gather(*tasks)

        # All should succeed since they're different resources
        assert all(results)
        assert sum(results) == 5

        # Verify each resource is owned by the correct instance
        for i in range(5):
            owner = await registry.get_resource_owner(f"resource-{i}")
            assert owner == f"instance-{i}"

    @pytest.mark.asyncio
    async def test_concurrent_force_registration(
        self, registry: ResourceRegistry, metadata: ResourceMetadata
    ) -> None:
        """Test force registration overwrites existing registrations."""
        # Create instances
        _ = await self.create_instances(registry, 3)

        # Register initial resource
        resource_id = "resource-force"
        initial_owner = "instance-0"
        await registry.register_resource(
            resource_id=resource_id,
            owner_instance_id=initial_owner,
            service_name="test-service",
            metadata=metadata,
            force=False,
        )

        # Verify initial owner
        owner = await registry.get_resource_owner(resource_id)
        assert owner == initial_owner

        # Force register from different instances concurrently
        async def force_register(instance_id: str) -> bool:
            """Force register a resource."""
            await registry.register_resource(
                resource_id=resource_id,
                owner_instance_id=instance_id,
                service_name="test-service",
                metadata=metadata,
                force=True,
            )
            return True

        # Create concurrent force registration tasks
        tasks = [asyncio.create_task(force_register(f"instance-{i}")) for i in range(1, 3)]

        # Wait for all tasks
        results = await asyncio.gather(*tasks)
        assert all(results)

        # One of the force registrations should have won
        final_owner = await registry.get_resource_owner(resource_id)
        assert final_owner in ["instance-1", "instance-2"]
        assert final_owner != initial_owner

    @pytest.mark.asyncio
    async def test_concurrent_register_and_release(
        self, registry: ResourceRegistry, metadata: ResourceMetadata
    ) -> None:
        """Test concurrent registration and release operations."""
        # Create instances
        _ = await self.create_instances(registry, 2)

        resource_id = "resource-concurrent"
        owner_instance = "instance-0"

        # Register initial resource
        await registry.register_resource(
            resource_id=resource_id,
            owner_instance_id=owner_instance,
            service_name="test-service",
            metadata=metadata,
            force=False,
        )

        # Define concurrent operations
        async def release_resource() -> bool:
            """Release the resource."""
            result = await registry.release_resource(resource_id, owner_instance)
            return bool(result)

        async def register_resource() -> bool:
            """Try to register the resource."""
            try:
                await registry.register_resource(
                    resource_id=resource_id,
                    owner_instance_id="instance-1",
                    service_name="test-service",
                    metadata=metadata,
                    force=False,
                )
                return True
            except ResourceConflictError:
                return False

        # Create concurrent tasks
        release_task = asyncio.create_task(release_resource())
        register_task = asyncio.create_task(register_resource())

        # Wait for both
        release_result, register_result = await asyncio.gather(release_task, register_task)

        # Release should succeed
        assert release_result is True

        # The final state depends on timing
        final_owner = await registry.get_resource_owner(resource_id)
        if register_result:
            # If register succeeded, instance-1 should own it
            assert final_owner == "instance-1"
        else:
            # If register failed (happened before release), resource should be unowned
            assert final_owner is None

    @pytest.mark.asyncio
    async def test_concurrent_bulk_operations(
        self, registry: ResourceRegistry, metadata: ResourceMetadata
    ) -> None:
        """Test concurrent bulk resource operations."""
        # Create instances
        _ = await self.create_instances(registry, 3)

        # Define bulk registration
        async def bulk_register(instance_id: str, start_idx: int) -> int:
            """Register multiple resources."""
            success_count = 0
            for i in range(start_idx, start_idx + 10):
                try:
                    await registry.register_resource(
                        resource_id=f"bulk-resource-{i}",
                        owner_instance_id=instance_id,
                        service_name="test-service",
                        metadata=metadata,
                        force=False,
                    )
                    success_count += 1
                except ResourceConflictError:
                    pass
            return success_count

        # Create overlapping bulk registration tasks
        tasks = [
            asyncio.create_task(bulk_register("instance-0", 0)),
            asyncio.create_task(bulk_register("instance-1", 5)),
            asyncio.create_task(bulk_register("instance-2", 10)),
        ]

        # Wait for all tasks
        results = await asyncio.gather(*tasks)

        # Verify results
        total_registered = sum(results)
        assert total_registered == 20  # 0-9, 5-14, 10-19 with overlaps

        # Verify ownership distribution
        for i in range(20):
            owner = await registry.get_resource_owner(f"bulk-resource-{i}")
            assert owner is not None
            assert owner in ["instance-0", "instance-1", "instance-2"]

    @pytest.mark.asyncio
    async def test_high_concurrency_stress(
        self, registry: ResourceRegistry, metadata: ResourceMetadata
    ) -> None:
        """Stress test with high concurrency."""
        # Create many instances
        instance_count = 10
        _ = await self.create_instances(registry, instance_count)

        # Define resource registration with retries
        async def register_with_retry(
            instance_id: str, resource_id: str, max_retries: int = 3
        ) -> bool:
            """Register resource with retries."""
            for _ in range(max_retries):
                try:
                    await registry.register_resource(
                        resource_id=resource_id,
                        owner_instance_id=instance_id,
                        service_name="test-service",
                        metadata=metadata,
                        force=False,
                    )
                    return True
                except ResourceConflictError:
                    await asyncio.sleep(0.01)  # Small delay before retry
            return False

        # Create many concurrent tasks
        resource_count = 50
        tasks = []
        for i in range(resource_count):
            # Multiple instances try to register the same resource
            for j in range(instance_count):
                task = asyncio.create_task(
                    register_with_retry(f"instance-{j}", f"stress-resource-{i}")
                )
                tasks.append(task)

        # Wait for all tasks
        results = await asyncio.gather(*tasks)

        # For each resource, exactly one registration should succeed
        for i in range(resource_count):
            owner = await registry.get_resource_owner(f"stress-resource-{i}")
            assert owner is not None
            assert owner.startswith("instance-")

        # Count successful registrations per resource
        success_per_resource = {}
        for i, result in enumerate(results):
            resource_idx = i // instance_count
            if f"stress-resource-{resource_idx}" not in success_per_resource:
                success_per_resource[f"stress-resource-{resource_idx}"] = 0
            if result:
                success_per_resource[f"stress-resource-{resource_idx}"] += 1

        # Verify exactly one success per resource
        for resource_id, count in success_per_resource.items():
            assert count == 1, f"Resource {resource_id} had {count} successful registrations"

    @pytest.mark.asyncio
    async def test_concurrent_transfer_operations(
        self, registry: ResourceRegistry, metadata: ResourceMetadata
    ) -> None:
        """Test concurrent resource transfer operations."""
        # Create instances
        _ = await self.create_instances(registry, 4)

        # Register initial resources
        resource_count = 10
        for i in range(resource_count):
            await registry.register_resource(
                resource_id=f"transfer-resource-{i}",
                owner_instance_id=f"instance-{i % 2}",  # Split between instance-0 and instance-1
                service_name="test-service",
                metadata=metadata,
                force=False,
            )

        # Define transfer operation
        async def transfer_resource(resource_id: str, from_inst: str, to_inst: str) -> bool:
            """Transfer resource ownership."""
            try:
                # Release from source
                released = await registry.release_resource(resource_id, from_inst)
                if not released:
                    return False

                # Register to target
                await registry.register_resource(
                    resource_id=resource_id,
                    owner_instance_id=to_inst,
                    service_name="test-service",
                    metadata=metadata,
                    force=False,
                )
                return True
            except (ResourceConflictError, ResourceNotFoundError):
                return False

        # Create concurrent transfer tasks
        # Transfer from instance-0/1 to instance-2/3
        tasks = []
        for i in range(resource_count):
            from_instance = f"instance-{i % 2}"
            to_instance = f"instance-{2 + (i % 2)}"
            task = asyncio.create_task(
                transfer_resource(f"transfer-resource-{i}", from_instance, to_instance)
            )
            tasks.append(task)

        # Wait for all transfers
        results = await asyncio.gather(*tasks)

        # All transfers should succeed
        assert all(results)

        # Verify final ownership
        for i in range(resource_count):
            owner = await registry.get_resource_owner(f"transfer-resource-{i}")
            expected_owner = f"instance-{2 + (i % 2)}"
            assert owner == expected_owner

    @pytest.mark.asyncio
    async def test_atomicity_of_operations(
        self, registry: ResourceRegistry, metadata: ResourceMetadata
    ) -> None:
        """Test atomicity of resource operations under concurrent access."""
        # Create instances
        _ = await self.create_instances(registry, 5)

        resource_id = "atomic-resource"

        # Define atomic check-and-register operation
        async def atomic_register_if_free(instance_id: str) -> bool:
            """Atomically check and register if resource is free."""
            # Check if resource exists
            owner = await registry.get_resource_owner(resource_id)
            if owner is not None:
                return False

            # Try to register
            try:
                await registry.register_resource(
                    resource_id=resource_id,
                    owner_instance_id=instance_id,
                    service_name="test-service",
                    metadata=metadata,
                    force=False,
                )
                return True
            except ResourceConflictError:
                return False

        # Create many concurrent atomic operations
        tasks = [
            asyncio.create_task(atomic_register_if_free(f"instance-{i % 5}")) for i in range(50)
        ]

        # Wait for all tasks
        results = await asyncio.gather(*tasks)

        # Exactly one should succeed
        assert sum(results) == 1

        # Verify resource has exactly one owner
        owner = await registry.get_resource_owner(resource_id)
        assert owner is not None
        assert owner.startswith("instance-")
