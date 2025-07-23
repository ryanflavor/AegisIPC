"""Unit tests for ResourceRegistry service."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from ipc_router.application.services import ResourceRegistry
from ipc_router.domain.entities import Resource, ResourceMetadata, ServiceInstance
from ipc_router.domain.enums import ServiceStatus
from ipc_router.domain.exceptions import (
    ResourceConflictError,
    ResourceLimitExceededError,
    ResourceOwnershipError,
)


class TestResourceRegistry:
    """Test ResourceRegistry service."""

    @pytest.fixture
    def registry(self) -> ResourceRegistry:
        """Create a ResourceRegistry instance."""
        return ResourceRegistry()

    @pytest.fixture
    def service_instance(self) -> ServiceInstance:
        """Create a test service instance."""
        return ServiceInstance(
            service_name="test-service",
            instance_id="instance-1",
            registered_at=datetime.now(UTC),
            status=ServiceStatus.ONLINE,
        )

    @pytest.fixture
    def resource_metadata(self) -> ResourceMetadata:
        """Create test resource metadata."""
        return ResourceMetadata(
            resource_type="test_resource",
            version=1,
            created_by="test-service",
            last_modified=datetime.now(UTC),
            ttl_seconds=3600,
            priority=5,
        )

    @pytest.mark.asyncio
    async def test_register_resource_success(
        self,
        registry: ResourceRegistry,
        service_instance: ServiceInstance,
        resource_metadata: ResourceMetadata,
    ) -> None:
        """Test successful resource registration."""
        # Register a resource
        resource = await registry.register_resource(
            resource_id="resource-123",
            owner_instance_id="instance-1",
            service_name="test-service",
            metadata=resource_metadata,
        )

        assert resource.resource_id == "resource-123"
        assert resource.owner_instance_id == "instance-1"
        assert resource.service_name == "test-service"
        assert resource.metadata == resource_metadata

        # Verify resource is stored
        owner = await registry.get_resource_owner("resource-123")
        assert owner == "instance-1"

    @pytest.mark.asyncio
    async def test_register_resource_without_metadata(
        self,
        registry: ResourceRegistry,
        service_instance: ServiceInstance,
        resource_metadata: ResourceMetadata,
    ) -> None:
        """Test registering resource without metadata."""
        resource = await registry.register_resource(
            resource_id="resource-456",
            owner_instance_id="instance-1",
            service_name="test-service",
            metadata=resource_metadata,
        )

        assert resource.resource_id == "resource-456"
        assert resource.metadata == resource_metadata

    @pytest.mark.asyncio
    async def test_register_resource_conflict(
        self,
        registry: ResourceRegistry,
        service_instance: ServiceInstance,
        resource_metadata: ResourceMetadata,
    ) -> None:
        """Test registering resource that's already owned."""
        # Register first resource
        await registry.register_resource(
            resource_id="resource-123",
            owner_instance_id="instance-1",
            service_name="test-service",
            metadata=resource_metadata,
        )

        # Try to register same resource from different instance
        with pytest.raises(ResourceConflictError) as exc_info:
            await registry.register_resource(
                resource_id="resource-123",
                owner_instance_id="instance-2",
                service_name="test-service",
                metadata=resource_metadata,
            )

        assert exc_info.value.details["resource_id"] == "resource-123"
        assert exc_info.value.details["current_owner"] == "instance-1"

    @pytest.mark.asyncio
    async def test_register_resource_with_force(
        self,
        registry: ResourceRegistry,
        service_instance: ServiceInstance,
        resource_metadata: ResourceMetadata,
    ) -> None:
        """Test force registering resource that's already owned."""
        # Register first resource
        await registry.register_resource(
            resource_id="resource-123",
            owner_instance_id="instance-1",
            service_name="test-service",
            metadata=resource_metadata,
        )

        # Force register same resource from different instance
        resource = await registry.register_resource(
            resource_id="resource-123",
            owner_instance_id="instance-2",
            service_name="test-service",
            metadata=resource_metadata,
            force=True,
        )

        assert resource.owner_instance_id == "instance-2"

        # Verify ownership changed
        owner = await registry.get_resource_owner("resource-123")
        assert owner == "instance-2"

    @pytest.mark.asyncio
    async def test_register_resource_invalid_id(
        self, registry: ResourceRegistry, resource_metadata: ResourceMetadata
    ) -> None:
        """Test registering resource with invalid ID."""
        from ipc_router.domain.exceptions import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            await registry.register_resource(
                resource_id="",  # Empty resource ID
                owner_instance_id="instance-1",
                service_name="test-service",
                metadata=resource_metadata,
            )

        assert "Resource ID cannot be empty" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_release_resource_success(
        self,
        registry: ResourceRegistry,
        service_instance: ServiceInstance,
        resource_metadata: ResourceMetadata,
    ) -> None:
        """Test successful resource release."""
        # Register a resource
        await registry.register_resource(
            resource_id="resource-123",
            owner_instance_id="instance-1",
            service_name="test-service",
            metadata=resource_metadata,
        )

        # Release the resource
        await registry.release_resource(
            resource_id="resource-123",
            instance_id="instance-1",
        )

        # Verify resource is no longer registered
        owner = await registry.get_resource_owner("resource-123")
        assert owner is None

    @pytest.mark.asyncio
    async def test_release_resource_not_owner(
        self,
        registry: ResourceRegistry,
        service_instance: ServiceInstance,
        resource_metadata: ResourceMetadata,
    ) -> None:
        """Test releasing resource by non-owner."""
        # Register resource
        await registry.register_resource(
            resource_id="resource-123",
            owner_instance_id="instance-1",
            service_name="test-service",
            metadata=resource_metadata,
        )

        # Try to release from non-owner instance
        with pytest.raises(ResourceOwnershipError) as exc_info:
            await registry.release_resource(
                resource_id="resource-123",
                instance_id="instance-2",
            )

        assert "does not own" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_release_resource_not_found(
        self, registry: ResourceRegistry, service_instance: ServiceInstance
    ) -> None:
        """Test releasing non-existent resource."""
        # Try to release non-existent resource - should return False
        result = await registry.release_resource(
            resource_id="non-existent",
            instance_id="instance-1",
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_get_resource_owner(
        self,
        registry: ResourceRegistry,
        service_instance: ServiceInstance,
        resource_metadata: ResourceMetadata,
    ) -> None:
        """Test getting resource owner."""
        # No owner initially
        owner = await registry.get_resource_owner("resource-123")
        assert owner is None

        # Register resource
        await registry.register_resource(
            resource_id="resource-123",
            owner_instance_id="instance-1",
            service_name="test-service",
            metadata=resource_metadata,
        )

        # Check owner
        owner = await registry.get_resource_owner("resource-123")
        assert owner == "instance-1"

    @pytest.mark.asyncio
    async def test_get_instance_resources(
        self,
        registry: ResourceRegistry,
        service_instance: ServiceInstance,
        resource_metadata: ResourceMetadata,
    ) -> None:
        """Test getting all resources for an instance."""
        # Register multiple resources
        resource_ids = ["res-1", "res-2", "res-3"]
        for resource_id in resource_ids:
            await registry.register_resource(
                resource_id=resource_id,
                owner_instance_id="instance-1",
                service_name="test-service",
                metadata=resource_metadata,
            )

        # Get instance resources
        resources = await registry.list_resources_by_instance("instance-1")
        assert len(resources) == 3
        assert all(r.owner_instance_id == "instance-1" for r in resources)
        assert {r.resource_id for r in resources} == set(resource_ids)

    @pytest.mark.asyncio
    async def test_release_instance_resources(
        self,
        registry: ResourceRegistry,
        service_instance: ServiceInstance,
        resource_metadata: ResourceMetadata,
    ) -> None:
        """Test releasing all resources for an instance."""
        # Register multiple resources
        resource_ids = ["res-1", "res-2", "res-3"]
        for resource_id in resource_ids:
            await registry.register_resource(
                resource_id=resource_id,
                owner_instance_id="instance-1",
                service_name="test-service",
                metadata=resource_metadata,
            )

        # Release all instance resources
        released_count = await registry.release_all_instance_resources("instance-1")
        assert released_count == 3

        # Verify all resources are released
        for resource_id in resource_ids:
            owner = await registry.get_resource_owner(resource_id)
            assert owner is None

    @pytest.mark.asyncio
    async def test_cleanup_expired_resources(
        self, registry: ResourceRegistry, service_instance: ServiceInstance
    ) -> None:
        """Test cleaning up expired resources."""
        # Register resource with short TTL
        past_time = datetime.now(UTC) - timedelta(seconds=10)
        metadata = ResourceMetadata(
            resource_type="cache",
            version=1,
            created_by="cache-service",
            last_modified=past_time,
            ttl_seconds=5,  # 5 second TTL
        )

        # Manually create expired resource
        resource = Resource(
            resource_id="expired-res",
            owner_instance_id="instance-1",
            service_name="test-service",
            registered_at=past_time,
            metadata=metadata,
        )

        # Add directly to registry storage
        registry._resources["expired-res"] = resource

        # Register non-expired resource
        current_metadata = ResourceMetadata(
            resource_type="cache",
            version=1,
            created_by="cache-service",
            last_modified=datetime.now(UTC),
            ttl_seconds=3600,
        )

        await registry.register_resource(
            resource_id="active-res",
            owner_instance_id="instance-1",
            service_name="test-service",
            metadata=current_metadata,
        )

        # Cleanup expired resources
        cleaned = await registry.cleanup_expired_resources()
        assert cleaned == 1

        # Verify expired resource is gone
        owner = await registry.get_resource_owner("expired-res")
        assert owner is None

        # Verify non-expired resource remains
        owner = await registry.get_resource_owner("active-res")
        assert owner == "instance-1"

    @pytest.mark.asyncio
    async def test_transfer_resource(
        self,
        registry: ResourceRegistry,
        service_instance: ServiceInstance,
        resource_metadata: ResourceMetadata,
    ) -> None:
        """Test transferring resource between instances."""
        # Register resource
        await registry.register_resource(
            resource_id="resource-123",
            owner_instance_id="instance-1",
            service_name="test-service",
            metadata=resource_metadata,
        )

        # Transfer resource
        resource = await registry.transfer_resource(
            resource_id="resource-123",
            from_instance_id="instance-1",
            to_instance_id="instance-2",
        )

        assert resource.owner_instance_id == "instance-2"

        # Verify ownership changed
        owner = await registry.get_resource_owner("resource-123")
        assert owner == "instance-2"

        # Verify resource lists updated
        instance1_resources = await registry.list_resources_by_instance("instance-1")
        assert len(instance1_resources) == 0

        instance2_resources = await registry.list_resources_by_instance("instance-2")
        assert len(instance2_resources) == 1
        assert instance2_resources[0].resource_id == "resource-123"

    @pytest.mark.asyncio
    async def test_concurrent_resource_registration(
        self,
        registry: ResourceRegistry,
        service_instance: ServiceInstance,
        resource_metadata: ResourceMetadata,
    ) -> None:
        """Test concurrent resource registration for same resource ID."""

        # Try to register same resource concurrently from both instances
        async def register_from_instance(instance_id: str) -> Resource | None:
            try:
                return await registry.register_resource(
                    resource_id="contested-resource",
                    owner_instance_id=instance_id,
                    service_name="test-service",
                    metadata=resource_metadata,
                )
            except ResourceConflictError:
                return None

        # Run concurrent registrations
        results = await asyncio.gather(
            register_from_instance("instance-1"),
            register_from_instance("instance-2"),
            return_exceptions=False,
        )

        # Only one should succeed
        successful_registrations = [r for r in results if r is not None]
        assert len(successful_registrations) == 1

        # Verify resource has single owner
        owner = await registry.get_resource_owner("contested-resource")
        assert owner in ["instance-1", "instance-2"]

    @pytest.mark.asyncio
    async def test_query_resources_by_type(
        self,
        registry: ResourceRegistry,
        service_instance: ServiceInstance,
    ) -> None:
        """Test querying resources by type."""
        # Register resources with different types
        types_and_ids = [
            ("session", "sess-1"),
            ("session", "sess-2"),
            ("document", "doc-1"),
            ("cache", "cache-1"),
        ]

        for resource_type, resource_id in types_and_ids:
            metadata = ResourceMetadata(
                resource_type=resource_type,
                version=1,
                created_by="test",
                last_modified=datetime.now(UTC),
            )
            await registry.register_resource(
                resource_id=resource_id,
                owner_instance_id="instance-1",
                service_name="test-service",
                metadata=metadata,
            )

        # Query by type
        session_resources = await registry.list_resources_by_service(
            service_name="test-service", resource_type="session"
        )
        assert len(session_resources) == 2
        assert all(r.metadata.resource_type == "session" for r in session_resources)

        document_resources = await registry.list_resources_by_service(
            service_name="test-service", resource_type="document"
        )
        assert len(document_resources) == 1
        assert document_resources[0].resource_id == "doc-1"

    @pytest.mark.asyncio
    async def test_query_resources_by_tags(
        self,
        registry: ResourceRegistry,
        service_instance: ServiceInstance,
    ) -> None:
        """Test querying resources by tags."""
        # Register resources with different tags
        tags_and_ids = [
            (["active", "premium"], "res-1"),
            (["active", "basic"], "res-2"),
            (["inactive", "premium"], "res-3"),
            ([], "res-4"),
        ]

        for tags, resource_id in tags_and_ids:
            metadata = ResourceMetadata(
                resource_type="test",
                version=1,
                tags=tags,
                created_by="test",
                last_modified=datetime.now(UTC),
            )
            await registry.register_resource(
                resource_id=resource_id,
                owner_instance_id="instance-1",
                service_name="test-service",
                metadata=metadata,
            )

        # Query by single tag
        active_resources = await registry.list_resources_by_service(
            service_name="test-service", tags=["active"]
        )
        assert len(active_resources) == 2
        assert {r.resource_id for r in active_resources} == {"res-1", "res-2"}

        # Query by multiple tags (any match)
        premium_resources = await registry.list_resources_by_service(
            service_name="test-service", tags=["premium"]
        )
        assert len(premium_resources) == 2
        assert {r.resource_id for r in premium_resources} == {"res-1", "res-3"}

    @pytest.mark.asyncio
    async def test_get_resource(
        self, registry: ResourceRegistry, resource_metadata: ResourceMetadata
    ) -> None:
        """Test getting a resource by ID."""
        # Test getting non-existent resource
        resource = await registry.get_resource("non-existent")
        assert resource is None

        # Register resource
        await registry.register_resource(
            resource_id="resource-123",
            owner_instance_id="instance-1",
            service_name="test-service",
            metadata=resource_metadata,
        )

        # Get resource
        resource = await registry.get_resource("resource-123")
        assert resource is not None
        assert resource.resource_id == "resource-123"
        assert resource.owner_instance_id == "instance-1"
        assert resource.service_name == "test-service"
        assert resource.metadata == resource_metadata

    @pytest.mark.asyncio
    async def test_check_resource_health(
        self, registry: ResourceRegistry, resource_metadata: ResourceMetadata
    ) -> None:
        """Test checking resource health."""
        # Non-existent resource should be unhealthy
        is_healthy = await registry.check_resource_health("non-existent")
        assert is_healthy is False

        # Register resource
        await registry.register_resource(
            resource_id="resource-123",
            owner_instance_id="instance-1",
            service_name="test-service",
            metadata=resource_metadata,
        )

        # For now, resource health is based on whether it exists and is not expired
        # Since we just created it, it should be healthy
        is_healthy = await registry.check_resource_health("resource-123")
        assert is_healthy is True

        # Test expired resource
        past_time = datetime.now(UTC) - timedelta(hours=2)
        expired_metadata = ResourceMetadata(
            resource_type="cache",
            version=1,
            created_by="test",
            last_modified=past_time,
            ttl_seconds=3600,  # 1 hour TTL
        )
        expired_resource = Resource(
            resource_id="expired-res",
            owner_instance_id="instance-1",
            service_name="test-service",
            registered_at=past_time,
            metadata=expired_metadata,
        )
        registry._resources["expired-res"] = expired_resource

        is_healthy = await registry.check_resource_health("expired-res")
        assert is_healthy is False

    @pytest.mark.asyncio
    async def test_bulk_register_resources_limit_exceeded(
        self, registry: ResourceRegistry, resource_metadata: ResourceMetadata
    ) -> None:
        """Test bulk registration when resource limit is exceeded."""
        # Create a registry with low limit
        limited_registry = ResourceRegistry(max_resources_per_instance=5)

        # Prepare resources that exceed the limit
        resources = [(f"resource-{i}", resource_metadata) for i in range(10)]

        # Without continue_on_error, should raise exception
        with pytest.raises(ResourceLimitExceededError):
            await limited_registry.bulk_register_resources(
                resources=resources,
                owner_instance_id="instance-1",
                service_name="test-service",
                continue_on_error=False,
            )

        # With continue_on_error, should register up to limit
        registered, failed = await limited_registry.bulk_register_resources(
            resources=resources,
            owner_instance_id="instance-1",
            service_name="test-service",
            continue_on_error=True,
        )

        assert len(registered) == 5  # Max limit
        assert len(failed) == 5  # Remaining resources

    @pytest.mark.asyncio
    async def test_bulk_register_resources_with_failures(
        self, registry: ResourceRegistry, resource_metadata: ResourceMetadata
    ) -> None:
        """Test bulk registration with some failures."""
        # Pre-register some resources to cause conflicts
        await registry.register_resource(
            resource_id="resource-1",
            owner_instance_id="instance-2",
            service_name="test-service",
            metadata=resource_metadata,
        )
        await registry.register_resource(
            resource_id="resource-3",
            owner_instance_id="instance-2",
            service_name="test-service",
            metadata=resource_metadata,
        )

        # Try to bulk register including conflicting resources
        resources = [(f"resource-{i}", resource_metadata) for i in range(5)]

        # Without continue_on_error, should rollback all
        with pytest.raises(ResourceConflictError):
            await registry.bulk_register_resources(
                resources=resources,
                owner_instance_id="instance-1",
                service_name="test-service",
                continue_on_error=False,
            )

        # Verify no resources were registered for instance-1
        instance_resources = await registry.list_resources_by_instance("instance-1")
        assert len(instance_resources) == 0

        # With continue_on_error, should register non-conflicting ones
        registered, failed = await registry.bulk_register_resources(
            resources=resources,
            owner_instance_id="instance-1",
            service_name="test-service",
            continue_on_error=True,
        )

        assert len(registered) == 3  # resources 0, 2, 4
        assert len(failed) == 2  # resources 1, 3 (conflicts)
        assert all(r.resource_id in ["resource-0", "resource-2", "resource-4"] for r in registered)

    @pytest.mark.asyncio
    async def test_get_resource_count_by_instance(
        self, registry: ResourceRegistry, resource_metadata: ResourceMetadata
    ) -> None:
        """Test getting resource count for an instance."""
        # Initially should be 0
        count = await registry.get_resource_count_by_instance("instance-1")
        assert count == 0

        # Register some resources
        for i in range(5):
            await registry.register_resource(
                resource_id=f"resource-{i}",
                owner_instance_id="instance-1",
                service_name="test-service",
                metadata=resource_metadata,
            )

        count = await registry.get_resource_count_by_instance("instance-1")
        assert count == 5

        # Register resources for another instance
        for i in range(3):
            await registry.register_resource(
                resource_id=f"other-resource-{i}",
                owner_instance_id="instance-2",
                service_name="test-service",
                metadata=resource_metadata,
            )

        # Count should still be 5 for instance-1
        count = await registry.get_resource_count_by_instance("instance-1")
        assert count == 5

        count = await registry.get_resource_count_by_instance("instance-2")
        assert count == 3

    @pytest.mark.asyncio
    async def test_transfer_resource_errors(
        self, registry: ResourceRegistry, resource_metadata: ResourceMetadata
    ) -> None:
        """Test resource transfer error cases."""
        from ipc_router.domain.exceptions import ResourceNotFoundError

        # Transfer non-existent resource
        with pytest.raises(ResourceNotFoundError):
            await registry.transfer_resource(
                resource_id="non-existent",
                from_instance_id="instance-1",
                to_instance_id="instance-2",
            )

        # Register resource
        await registry.register_resource(
            resource_id="resource-123",
            owner_instance_id="instance-1",
            service_name="test-service",
            metadata=resource_metadata,
        )

        # Transfer from wrong owner
        with pytest.raises(ResourceOwnershipError):
            await registry.transfer_resource(
                resource_id="resource-123",
                from_instance_id="instance-2",  # Wrong owner
                to_instance_id="instance-3",
            )

    @pytest.mark.asyncio
    async def test_transfer_resource_limit_exceeded(
        self, registry: ResourceRegistry, resource_metadata: ResourceMetadata
    ) -> None:
        """Test resource transfer when target instance would exceed limit."""
        # Create registry with low limit
        limited_registry = ResourceRegistry(max_resources_per_instance=2)

        # Register resources for instance-2 up to limit
        for i in range(2):
            await limited_registry.register_resource(
                resource_id=f"existing-{i}",
                owner_instance_id="instance-2",
                service_name="test-service",
                metadata=resource_metadata,
            )

        # Register resource for instance-1
        await limited_registry.register_resource(
            resource_id="resource-to-transfer",
            owner_instance_id="instance-1",
            service_name="test-service",
            metadata=resource_metadata,
        )

        # Try to transfer - should fail due to limit
        with pytest.raises(ResourceLimitExceededError):
            await limited_registry.transfer_resource(
                resource_id="resource-to-transfer",
                from_instance_id="instance-1",
                to_instance_id="instance-2",
            )

    @pytest.mark.asyncio
    async def test_list_resources_by_service_empty(self, registry: ResourceRegistry) -> None:
        """Test listing resources for a service with no resources."""
        resources = await registry.list_resources_by_service("empty-service")
        assert resources == []

        # With filters
        resources = await registry.list_resources_by_service(
            "empty-service",
            resource_type="session",
            tags=["active"],
        )
        assert resources == []

    @pytest.mark.asyncio
    async def test_cleanup_expired_resources_with_custom_time(
        self, registry: ResourceRegistry
    ) -> None:
        """Test cleanup with custom current time."""
        # Create resources with different expiration times
        base_time = datetime.now(UTC)

        # Resource that expires in 1 hour
        metadata1 = ResourceMetadata(
            resource_type="cache",
            version=1,
            created_by="test",
            last_modified=base_time - timedelta(minutes=30),
            ttl_seconds=3600,  # 1 hour
        )
        resource1 = Resource(
            resource_id="future-expire",
            owner_instance_id="instance-1",
            service_name="test-service",
            registered_at=base_time - timedelta(minutes=30),
            metadata=metadata1,
        )
        registry._resources["future-expire"] = resource1

        # Resource that's already expired
        metadata2 = ResourceMetadata(
            resource_type="cache",
            version=1,
            created_by="test",
            last_modified=base_time - timedelta(hours=2),
            ttl_seconds=3600,  # 1 hour
        )
        resource2 = Resource(
            resource_id="already-expired",
            owner_instance_id="instance-1",
            service_name="test-service",
            registered_at=base_time - timedelta(hours=2),
            metadata=metadata2,
        )
        registry._resources["already-expired"] = resource2

        # Cleanup with current time - only expired resource should be removed
        cleaned = await registry.cleanup_expired_resources(base_time)
        assert cleaned == 1

        # Check what remains
        assert await registry.get_resource("future-expire") is not None
        assert await registry.get_resource("already-expired") is None

        # Cleanup with future time - remaining resource should be removed
        future_time = base_time + timedelta(hours=2)
        cleaned = await registry.cleanup_expired_resources(future_time)
        assert cleaned == 1
        assert await registry.get_resource("future-expire") is None

    @pytest.mark.asyncio
    async def test_bulk_register_rollback_on_error(
        self, registry: ResourceRegistry, resource_metadata: ResourceMetadata
    ) -> None:
        """Test that bulk registration rollback works correctly on error."""
        # Pre-register a resource to cause conflict
        await registry.register_resource(
            resource_id="conflict-resource",
            owner_instance_id="instance-2",
            service_name="test-service",
            metadata=resource_metadata,
        )

        # Try to register including the conflicting resource
        resources = [
            ("new-resource-1", resource_metadata),
            ("new-resource-2", resource_metadata),
            ("conflict-resource", resource_metadata),  # This will cause conflict
            ("new-resource-3", resource_metadata),
        ]

        # Without continue_on_error, should rollback all
        with pytest.raises(ResourceConflictError):
            await registry.bulk_register_resources(
                resources=resources,
                owner_instance_id="instance-1",
                service_name="test-service",
                continue_on_error=False,
            )

        # Verify that the first two resources were rolled back
        assert await registry.get_resource_owner("new-resource-1") is None
        assert await registry.get_resource_owner("new-resource-2") is None
        assert await registry.get_resource_owner("conflict-resource") == "instance-2"
        assert await registry.get_resource_owner("new-resource-3") is None

    @pytest.mark.asyncio
    async def test_bulk_register_with_empty_list(self, registry: ResourceRegistry) -> None:
        """Test bulk registration with empty resource list."""
        registered, failed = await registry.bulk_register_resources(
            resources=[],
            owner_instance_id="instance-1",
            service_name="test-service",
            continue_on_error=True,
        )

        assert len(registered) == 0
        assert len(failed) == 0

    @pytest.mark.asyncio
    async def test_bulk_release_with_ownership_errors(
        self, registry: ResourceRegistry, resource_metadata: ResourceMetadata
    ) -> None:
        """Test bulk release with ownership validation errors."""
        # Register resources for different instances
        await registry.register_resource(
            resource_id="resource-1",
            owner_instance_id="instance-1",
            service_name="test-service",
            metadata=resource_metadata,
        )
        await registry.register_resource(
            resource_id="resource-2",
            owner_instance_id="instance-2",
            service_name="test-service",
            metadata=resource_metadata,
        )
        await registry.register_resource(
            resource_id="resource-3",
            owner_instance_id="instance-1",
            service_name="test-service",
            metadata=resource_metadata,
        )

        # Try to release resources, including one not owned by instance-1
        resource_ids = ["resource-1", "resource-2", "resource-3", "non-existent"]
        released, failed = await registry.bulk_release_resources(
            resource_ids=resource_ids,
            instance_id="instance-1",
        )

        # Should release only resources owned by instance-1
        assert set(released) == {"resource-1", "resource-3"}
        assert set(failed) == {"resource-2", "non-existent"}

        # Verify resources are in correct state
        assert await registry.get_resource_owner("resource-1") is None
        assert await registry.get_resource_owner("resource-2") == "instance-2"
        assert await registry.get_resource_owner("resource-3") is None

    @pytest.mark.asyncio
    async def test_resource_metadata_validation_edge_cases(
        self, registry: ResourceRegistry
    ) -> None:
        """Test resource registration with various metadata edge cases."""
        # Test with minimal metadata
        minimal_metadata = ResourceMetadata(
            resource_type="test",
            version=1,
            created_by="test",
            last_modified=datetime.now(UTC),
        )

        resource = await registry.register_resource(
            resource_id="minimal-resource",
            owner_instance_id="instance-1",
            service_name="test-service",
            metadata=minimal_metadata,
        )

        assert resource.metadata.tags == []
        assert resource.metadata.attributes == {}
        assert resource.metadata.ttl_seconds is None
        assert resource.metadata.priority == 0

        # Test with complex attributes
        complex_metadata = ResourceMetadata(
            resource_type="complex",
            version=1,
            tags=["tag1", "tag2", "tag3"],
            attributes={
                "nested": {"key": "value"},
                "list": [1, 2, 3],
                "bool": True,
            },
            created_by="test",
            last_modified=datetime.now(UTC),
            ttl_seconds=7200,
            priority=10,
        )

        complex_resource = await registry.register_resource(
            resource_id="complex-resource",
            owner_instance_id="instance-1",
            service_name="test-service",
            metadata=complex_metadata,
        )

        assert len(complex_resource.metadata.tags) == 3
        assert complex_resource.metadata.attributes["nested"]["key"] == "value"
        assert complex_resource.metadata.priority == 10

    @pytest.mark.asyncio
    async def test_concurrent_bulk_operations(
        self, registry: ResourceRegistry, resource_metadata: ResourceMetadata
    ) -> None:
        """Test concurrent bulk registration operations."""
        # Prepare two sets of resources for concurrent registration
        set1 = [(f"set1-resource-{i}", resource_metadata) for i in range(10)]
        set2 = [(f"set2-resource-{i}", resource_metadata) for i in range(10)]

        # Run bulk registrations concurrently
        results: list[
            tuple[list[Resource], list[tuple[str, str]]] | BaseException
        ] = await asyncio.gather(
            registry.bulk_register_resources(
                resources=set1,
                owner_instance_id="instance-1",
                service_name="test-service",
                continue_on_error=True,
            ),
            registry.bulk_register_resources(
                resources=set2,
                owner_instance_id="instance-2",
                service_name="test-service",
                continue_on_error=True,
            ),
            return_exceptions=True,
        )

        # Both operations should succeed
        assert len(results) == 2
        assert not any(isinstance(r, Exception) for r in results)

        # Verify resources are registered to correct instances
        result1 = results[0]
        result2 = results[1]

        # Type guard to ensure they're not exceptions
        if isinstance(result1, BaseException) or isinstance(result2, BaseException):
            raise Exception("Bulk operations failed")

        set1_registered, _ = result1
        set2_registered, _ = result2

        assert len(set1_registered) == 10
        assert len(set2_registered) == 10

        for resource in set1_registered:
            assert resource.owner_instance_id == "instance-1"
        for resource in set2_registered:
            assert resource.owner_instance_id == "instance-2"

    @pytest.mark.asyncio
    async def test_resource_registry_with_invalid_resource_id_chars(
        self, registry: ResourceRegistry, resource_metadata: ResourceMetadata
    ) -> None:
        """Test registration with various invalid resource ID characters."""
        from ipc_router.domain.exceptions import ValidationError

        invalid_ids = [
            "",  # Empty string
            " ",  # Just whitespace
            "resource\nwith\nnewlines",
            "resource\twith\ttabs",
            "resource#with#special",
            None,  # None should be handled
        ]

        for invalid_id in invalid_ids:
            if invalid_id is None:
                # Skip None as it would fail at type checking
                continue

            with pytest.raises(ValidationError):
                await registry.register_resource(
                    resource_id=invalid_id,
                    owner_instance_id="instance-1",
                    service_name="test-service",
                    metadata=resource_metadata,
                )

    @pytest.mark.asyncio
    async def test_list_resources_by_instance_concurrent_modifications(
        self, registry: ResourceRegistry, resource_metadata: ResourceMetadata
    ) -> None:
        """Test listing resources while concurrent modifications happen."""
        # Register initial resources
        for i in range(10):
            await registry.register_resource(
                resource_id=f"resource-{i}",
                owner_instance_id="instance-1",
                service_name="test-service",
                metadata=resource_metadata,
            )

        # Define concurrent operations
        async def list_resources() -> list[Resource]:
            result: list[Resource] = await registry.list_resources_by_instance("instance-1")
            return result

        async def add_resource(idx: int) -> None:
            await registry.register_resource(
                resource_id=f"new-resource-{idx}",
                owner_instance_id="instance-1",
                service_name="test-service",
                metadata=resource_metadata,
            )

        async def remove_resource(idx: int) -> None:
            import contextlib

            with contextlib.suppress(Exception):
                await registry.release_resource(
                    resource_id=f"resource-{idx}",
                    instance_id="instance-1",
                )

        # Run operations concurrently
        tasks = [
            list_resources(),
            add_resource(100),
            remove_resource(0),
            list_resources(),
            add_resource(101),
            remove_resource(1),
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Verify no exceptions occurred
        for result in results:
            if isinstance(result, Exception):
                raise result

        # Final list should reflect all operations
        final_resources = await registry.list_resources_by_instance("instance-1")
        resource_ids = {r.resource_id for r in final_resources}

        # Should have original resources minus removed, plus added
        assert "resource-0" not in resource_ids
        assert "resource-1" not in resource_ids
        assert "new-resource-100" in resource_ids
        assert "new-resource-101" in resource_ids

    @pytest.mark.asyncio
    async def test_bulk_register_partial_limit_exceeded(
        self, registry: ResourceRegistry, resource_metadata: ResourceMetadata
    ) -> None:
        """Test bulk registration when limit is partially exceeded."""
        # Create registry with limit of 3
        limited_registry = ResourceRegistry(max_resources_per_instance=3)

        # First register 2 resources
        await limited_registry.register_resource(
            resource_id="existing-1",
            owner_instance_id="instance-1",
            service_name="test-service",
            metadata=resource_metadata,
        )
        await limited_registry.register_resource(
            resource_id="existing-2",
            owner_instance_id="instance-1",
            service_name="test-service",
            metadata=resource_metadata,
        )

        # Try to bulk register 5 more (should only allow 1)
        resources = [(f"new-{i}", resource_metadata) for i in range(5)]

        registered, failed = await limited_registry.bulk_register_resources(
            resources=resources,
            owner_instance_id="instance-1",
            service_name="test-service",
            continue_on_error=True,
        )

        # Should register only 1 resource (to reach limit of 3)
        assert len(registered) == 1
        assert registered[0].resource_id == "new-0"
        assert len(failed) == 4

        # Verify we're at the limit
        count = await limited_registry.get_resource_count_by_instance("instance-1")
        assert count == 3

    @pytest.mark.asyncio
    async def test_cleanup_expired_resources_with_no_ttl(self, registry: ResourceRegistry) -> None:
        """Test that resources without TTL are not cleaned up."""
        # Create resources with and without TTL
        metadata_with_ttl = ResourceMetadata(
            resource_type="cache",
            version=1,
            created_by="test",
            last_modified=datetime.now(UTC) - timedelta(hours=2),
            ttl_seconds=3600,  # 1 hour TTL, expired
        )

        metadata_no_ttl = ResourceMetadata(
            resource_type="persistent",
            version=1,
            created_by="test",
            last_modified=datetime.now(UTC) - timedelta(hours=2),
            ttl_seconds=None,  # No TTL
        )

        # Register both types
        await registry.register_resource(
            resource_id="expired-resource",
            owner_instance_id="instance-1",
            service_name="test-service",
            metadata=metadata_with_ttl,
        )

        await registry.register_resource(
            resource_id="persistent-resource",
            owner_instance_id="instance-1",
            service_name="test-service",
            metadata=metadata_no_ttl,
        )

        # Run cleanup
        cleaned = await registry.cleanup_expired_resources()

        # Only expired resource should be cleaned
        assert cleaned == 1
        assert await registry.get_resource("expired-resource") is None
        assert await registry.get_resource("persistent-resource") is not None
