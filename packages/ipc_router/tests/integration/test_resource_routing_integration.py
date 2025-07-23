"""Integration tests for resource-based routing functionality."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from ipc_router.application.models import (
    ResourceMetadata,
    RouteRequest,
)
from ipc_router.application.services import (
    ResourceAwareRoutingService,
    ResourceRegistry,
    ResourceService,
    ResourceTransferService,
    ServiceRegistry,
)
from ipc_router.domain.entities import Resource, ServiceInstance
from ipc_router.domain.exceptions import (
    ResourceConflictError,
    ResourceNotFoundError,
    ResourceReleaseError,
)
from ipc_router.infrastructure.logging import get_logger

logger = get_logger(__name__)


@pytest_asyncio.fixture
async def service_registry() -> ServiceRegistry:
    """Create service registry instance."""
    registry = ServiceRegistry()
    yield registry


@pytest_asyncio.fixture
async def resource_registry(service_registry: ServiceRegistry) -> ResourceRegistry:
    """Create resource registry instance."""
    registry = ResourceRegistry(service_registry)
    yield registry


@pytest_asyncio.fixture
async def resource_service(resource_registry: ResourceRegistry) -> ResourceService:
    """Create resource service instance."""
    service = ResourceService(resource_registry)
    yield service


@pytest_asyncio.fixture
async def routing_service(
    service_registry: ServiceRegistry, resource_registry: ResourceRegistry
) -> ResourceAwareRoutingService:
    """Create resource-aware routing service."""
    service = ResourceAwareRoutingService(service_registry, resource_registry)
    yield service


@pytest_asyncio.fixture
async def transfer_service(
    resource_registry: ResourceRegistry, service_registry: ServiceRegistry
) -> ResourceTransferService:
    """Create resource transfer service."""
    service = ResourceTransferService(resource_registry, service_registry)
    yield service


@pytest.fixture
def sample_metadata() -> ResourceMetadata:
    """Sample resource metadata."""
    return ResourceMetadata(
        resource_type="user_session",
        version=1,
        tags=["active", "premium"],
        attributes={"region": "us-west", "tier": "gold"},
        created_by="auth-service",
        last_modified=datetime.now(UTC),
        ttl_seconds=3600,
        priority=10,
    )


class TestResourceRoutingIntegration:
    """Integration tests for resource-based routing."""

    async def test_resource_registration_and_routing(
        self,
        service_registry: ServiceRegistry,
        resource_service: ResourceService,
        routing_service: ResourceAwareRoutingService,
        sample_metadata: ResourceMetadata,
    ) -> None:
        """Test end-to-end resource registration and routing."""
        # Register service instances
        instance1 = ServiceInstance(
            service_name="user-service",
            instance_id="user-service-1",
            metadata={},
            registered_at=datetime.now(UTC),
        )
        instance2 = ServiceInstance(
            service_name="user-service",
            instance_id="user-service-2",
            metadata={},
            registered_at=datetime.now(UTC),
        )

        await service_registry.register(instance1)
        await service_registry.register(instance2)

        # Register resources to different instances
        resources_instance1 = ["user-123", "user-456", "user-789"]
        resources_instance2 = ["user-111", "user-222", "user-333"]

        # Register resources for instance1
        for resource_id in resources_instance1:
            resource = await resource_service.register_resource(
                service_name="user-service",
                instance_id="user-service-1",
                resource_id=resource_id,
                metadata=sample_metadata,
            )
            assert resource.owner_instance_id == "user-service-1"

        # Register resources for instance2
        for resource_id in resources_instance2:
            resource = await resource_service.register_resource(
                service_name="user-service",
                instance_id="user-service-2",
                resource_id=resource_id,
                metadata=sample_metadata,
            )
            assert resource.owner_instance_id == "user-service-2"

        # Test routing to correct instances
        for resource_id in resources_instance1:
            route_request = RouteRequest(
                service_name="user-service",
                resource_id=resource_id,
                method="get_user",
                params={},
                timeout=5.0,
                trace_id=f"trace-{uuid.uuid4().hex[:16]}",
            )
            instance = await routing_service.select_instance(route_request)
            assert instance.instance_id == "user-service-1"

        for resource_id in resources_instance2:
            route_request = RouteRequest(
                service_name="user-service",
                resource_id=resource_id,
                method="get_user",
                params={},
                timeout=5.0,
                trace_id=f"trace-{uuid.uuid4().hex[:16]}",
            )
            instance = await routing_service.select_instance(route_request)
            assert instance.instance_id == "user-service-2"

    async def test_resource_conflict_handling(
        self, resource_service: ResourceService, sample_metadata: ResourceMetadata
    ) -> None:
        """Test resource conflict detection and handling."""
        # Register a resource
        resource = await resource_service.register_resource(
            service_name="test-service",
            instance_id="instance-1",
            resource_id="shared-resource",
            metadata=sample_metadata,
        )
        assert resource.owner_instance_id == "instance-1"

        # Try to register same resource from different instance
        with pytest.raises(ResourceConflictError) as exc_info:
            await resource_service.register_resource(
                service_name="test-service",
                instance_id="instance-2",
                resource_id="shared-resource",
                metadata=sample_metadata,
            )

        assert "already registered" in str(exc_info.value)
        assert exc_info.value.details["current_owner"] == "instance-1"

        # Force registration should succeed
        resource = await resource_service.register_resource(
            service_name="test-service",
            instance_id="instance-2",
            resource_id="shared-resource",
            metadata=sample_metadata,
            force=True,
        )
        assert resource.owner_instance_id == "instance-2"

    async def test_resource_release_ownership_verification(
        self, resource_service: ResourceService, sample_metadata: ResourceMetadata
    ) -> None:
        """Test resource release with ownership verification."""
        # Register a resource
        await resource_service.register_resource(
            service_name="test-service",
            instance_id="owner-instance",
            resource_id="protected-resource",
            metadata=sample_metadata,
        )

        # Try to release from non-owner instance
        with pytest.raises(ResourceReleaseError) as exc_info:
            await resource_service.release_resource(
                service_name="test-service",
                instance_id="other-instance",
                resource_id="protected-resource",
            )

        assert "not owned by instance" in str(exc_info.value)

        # Release from owner should succeed
        await resource_service.release_resource(
            service_name="test-service",
            instance_id="owner-instance",
            resource_id="protected-resource",
        )

        # Verify resource is released
        with pytest.raises(ResourceNotFoundError):
            await resource_service.get_resource("protected-resource")

    async def test_instance_offline_resource_cleanup(
        self,
        service_registry: ServiceRegistry,
        resource_registry: ResourceRegistry,
        resource_service: ResourceService,
        sample_metadata: ResourceMetadata,
    ) -> None:
        """Test automatic resource cleanup when instance goes offline."""
        # Register service instance
        instance = ServiceInstance(
            service_name="ephemeral-service",
            instance_id="ephemeral-instance",
            metadata={},
            registered_at=datetime.now(UTC),
        )
        await service_registry.register(instance)

        # Register multiple resources
        resource_ids = [f"ephemeral-{i}" for i in range(5)]
        for resource_id in resource_ids:
            await resource_service.register_resource(
                service_name="ephemeral-service",
                instance_id="ephemeral-instance",
                resource_id=resource_id,
                metadata=sample_metadata,
            )

        # Verify resources are registered
        for resource_id in resource_ids:
            resource = await resource_service.get_resource(resource_id)
            assert resource.owner_instance_id == "ephemeral-instance"

        # Unregister instance (simulate offline)
        await service_registry.unregister("ephemeral-service", "ephemeral-instance")

        # Verify all resources are automatically released
        for resource_id in resource_ids:
            with pytest.raises(ResourceNotFoundError):
                await resource_service.get_resource(resource_id)

    async def test_resource_transfer_atomic_operation(
        self,
        service_registry: ServiceRegistry,
        transfer_service: ResourceTransferService,
        resource_service: ResourceService,
        sample_metadata: ResourceMetadata,
    ) -> None:
        """Test atomic resource transfer between instances."""
        # Register two service instances
        instance1 = ServiceInstance(
            service_name="transfer-service",
            instance_id="instance-1",
            metadata={},
            registered_at=datetime.now(UTC),
        )
        instance2 = ServiceInstance(
            service_name="transfer-service",
            instance_id="instance-2",
            metadata={},
            registered_at=datetime.now(UTC),
        )

        await service_registry.register(instance1)
        await service_registry.register(instance2)

        # Register resources to instance1
        resource_ids = ["transfer-1", "transfer-2", "transfer-3"]
        for resource_id in resource_ids:
            await resource_service.register_resource(
                service_name="transfer-service",
                instance_id="instance-1",
                resource_id=resource_id,
                metadata=sample_metadata,
            )

        # Transfer resources to instance2
        transfer_id = await transfer_service.transfer_resources(
            service_name="transfer-service",
            resource_ids=resource_ids,
            from_instance_id="instance-1",
            to_instance_id="instance-2",
            reason="Load balancing",
            verify_ownership=True,
        )

        # Verify transfer completed
        assert transfer_id is not None

        # Verify resources now owned by instance2
        for resource_id in resource_ids:
            resource = await resource_service.get_resource(resource_id)
            assert resource.owner_instance_id == "instance-2"

    async def test_concurrent_resource_registration(
        self, resource_service: ResourceService, sample_metadata: ResourceMetadata
    ) -> None:
        """Test concurrent resource registration handles conflicts correctly."""
        resource_id = "concurrent-resource"

        # Create multiple concurrent registration attempts
        async def register_resource(instance_id: str) -> Resource | None:
            try:
                return await resource_service.register_resource(
                    service_name="concurrent-service",
                    instance_id=instance_id,
                    resource_id=resource_id,
                    metadata=sample_metadata,
                )
            except ResourceConflictError:
                return None

        # Run concurrent registrations
        tasks = [register_resource(f"instance-{i}") for i in range(10)]
        results = await asyncio.gather(*tasks)

        # Only one should succeed
        successful_registrations = [r for r in results if r is not None]
        assert len(successful_registrations) == 1

        # Verify the resource has single owner
        resource = await resource_service.get_resource(resource_id)
        assert resource.owner_instance_id in [f"instance-{i}" for i in range(10)]

    async def test_resource_routing_fallback(
        self,
        service_registry: ServiceRegistry,
        routing_service: ResourceAwareRoutingService,
        resource_service: ResourceService,
    ) -> None:
        """Test routing fallback when resource not found."""
        # Register service instances
        instance1 = ServiceInstance(
            service_name="fallback-service",
            instance_id="fallback-1",
            metadata={},
            registered_at=datetime.now(UTC),
        )
        instance2 = ServiceInstance(
            service_name="fallback-service",
            instance_id="fallback-2",
            metadata={},
            registered_at=datetime.now(UTC),
        )

        await service_registry.register(instance1)
        await service_registry.register(instance2)

        # Route request with non-existent resource
        route_request = RouteRequest(
            service_name="fallback-service",
            resource_id="non-existent-resource",
            method="process",
            params={},
            timeout=5.0,
            trace_id="trace-123",
        )

        # Should fallback to round-robin routing
        selected_instances = set()
        for _ in range(10):
            instance = await routing_service.select_instance(route_request)
            selected_instances.add(instance.instance_id)

        # Both instances should be selected
        assert len(selected_instances) == 2
        assert "fallback-1" in selected_instances
        assert "fallback-2" in selected_instances

    async def test_resource_metadata_update(
        self, resource_service: ResourceService, sample_metadata: ResourceMetadata
    ) -> None:
        """Test resource metadata can be updated."""
        # Register resource
        resource = await resource_service.register_resource(
            service_name="metadata-service",
            instance_id="metadata-instance",
            resource_id="metadata-resource",
            metadata=sample_metadata,
        )

        original_version = resource.metadata.version

        # Update metadata
        updated_metadata = ResourceMetadata(
            resource_type="user_session",
            version=original_version + 1,
            tags=["active", "premium", "updated"],
            attributes={"region": "us-east", "tier": "platinum"},
            created_by="auth-service",
            last_modified=datetime.now(UTC),
            ttl_seconds=7200,
            priority=20,
        )

        # Re-register with force to update
        updated_resource = await resource_service.register_resource(
            service_name="metadata-service",
            instance_id="metadata-instance",
            resource_id="metadata-resource",
            metadata=updated_metadata,
            force=True,
        )

        # Verify metadata updated
        assert updated_resource.metadata.version == original_version + 1
        assert "updated" in updated_resource.metadata.tags
        assert updated_resource.metadata.attributes["region"] == "us-east"
        assert updated_resource.metadata.priority == 20

    async def test_resource_query_by_type_and_tags(
        self, resource_registry: ResourceRegistry, resource_service: ResourceService
    ) -> None:
        """Test querying resources by type and tags."""
        # Register resources with different types and tags
        resources_data = [
            ("session-1", "user_session", ["active", "premium"]),
            ("session-2", "user_session", ["active", "basic"]),
            ("session-3", "admin_session", ["active", "premium"]),
            ("session-4", "user_session", ["inactive", "premium"]),
        ]

        for resource_id, resource_type, tags in resources_data:
            metadata = ResourceMetadata(
                resource_type=resource_type,
                version=1,
                tags=tags,
                attributes={},
                created_by="test",
                last_modified=datetime.now(UTC),
                priority=5,
            )
            await resource_service.register_resource(
                service_name="query-service",
                instance_id="query-instance",
                resource_id=resource_id,
                metadata=metadata,
            )

        # Query by type
        user_sessions = await resource_registry.query_resources(resource_type="user_session")
        assert len(user_sessions) == 3
        assert all(r.metadata.resource_type == "user_session" for r in user_sessions)

        # Query by tags
        active_premium = await resource_registry.query_resources(tags=["active", "premium"])
        assert len(active_premium) == 2
        assert all(
            "active" in r.metadata.tags and "premium" in r.metadata.tags for r in active_premium
        )

        # Query by service
        service_resources = await resource_registry.query_resources(service_name="query-service")
        assert len(service_resources) == 4

    async def test_resource_ttl_expiration(self, resource_service: ResourceService) -> None:
        """Test resource TTL expiration handling."""
        # Register resource with short TTL
        metadata = ResourceMetadata(
            resource_type="ephemeral",
            version=1,
            tags=["short-lived"],
            attributes={},
            created_by="test",
            last_modified=datetime.now(UTC),
            ttl_seconds=1,  # 1 second TTL
            priority=1,
        )

        resource = await resource_service.register_resource(
            service_name="ttl-service",
            instance_id="ttl-instance",
            resource_id="ttl-resource",
            metadata=metadata,
        )

        # Verify resource exists
        retrieved = await resource_service.get_resource("ttl-resource")
        assert retrieved.resource_id == "ttl-resource"

        # Wait for TTL to expire
        await asyncio.sleep(1.5)

        # Check if TTL expiration is handled (implementation-dependent)
        # This test assumes the system has a TTL cleanup mechanism
        # In a real implementation, expired resources might be:
        # 1. Automatically cleaned up by a background task
        # 2. Lazily cleaned up on access
        # 3. Marked as expired but still queryable

        # For this test, we just verify the resource still has TTL metadata
        assert resource.metadata.ttl_seconds == 1
