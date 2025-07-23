"""Unit tests for resource transfer permissions and atomicity."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, call

import pytest
import pytest_asyncio
from ipc_router.application.events import EventBus
from ipc_router.application.services import (
    ResourceRegistry,
    ResourceService,
    ResourceTransferService,
)
from ipc_router.domain.entities import Resource, ResourceMetadata, ServiceInstance
from ipc_router.domain.exceptions import (
    NotFoundError,
    ValidationError,
)


class TestResourceTransferPermissions:
    """Test resource transfer permission validation."""

    @pytest.fixture
    def event_bus(self) -> MagicMock:
        """Create a mock event bus."""
        mock = MagicMock(spec=EventBus)
        mock.publish = AsyncMock()
        return mock

    @pytest.fixture
    def resource_registry(self) -> MagicMock:
        """Create a mock resource registry."""
        mock = MagicMock(spec=ResourceRegistry)
        mock.get_instance = AsyncMock()
        mock.get_resource_owner = AsyncMock()
        mock.transfer_resource = AsyncMock()
        return mock

    @pytest.fixture
    def resource_service(self) -> MagicMock:
        """Create a mock resource service."""
        mock = MagicMock(spec=ResourceService)
        mock.get_resource_owner = AsyncMock()
        return mock

    @pytest.fixture
    def transfer_service(
        self,
        resource_registry: MagicMock,
        resource_service: MagicMock,
        event_bus: MagicMock,
    ) -> ResourceTransferService:
        """Create a ResourceTransferService instance."""
        return ResourceTransferService(
            resource_registry=resource_registry,
            resource_service=resource_service,
            event_bus=event_bus,
        )

    @pytest.fixture
    def sample_resource(self) -> Resource:
        """Create a sample resource."""
        return Resource(
            resource_id="resource-123",
            owner_instance_id="instance-1",
            service_name="test-service",
            registered_at=datetime.now(UTC),
            metadata=ResourceMetadata(
                resource_type="test_resource",
                version=1,
                created_by="test-service",
                last_modified=datetime.now(UTC),
            ),
        )

    @pytest.mark.asyncio
    async def test_transfer_with_valid_ownership(
        self,
        transfer_service: ResourceTransferService,
        resource_registry: MagicMock,
        resource_service: MagicMock,
        event_bus: MagicMock,
        sample_resource: Resource,
    ) -> None:
        """Test successful transfer with valid ownership."""
        # Setup mocks
        resource_service.get_resource_owner.return_value = "instance-1"
        resource_registry.get_instance.side_effect = [
            ServiceInstance(  # From instance
                service_name="test-service",
                instance_id="instance-1",
                registered_at=datetime.now(UTC),
            ),
            ServiceInstance(  # To instance
                service_name="test-service",
                instance_id="instance-2",
                registered_at=datetime.now(UTC),
            ),
        ]
        resource_registry.transfer_resource.return_value = sample_resource

        # Perform transfer
        transfer_id = await transfer_service.transfer_resources(
            resource_ids=["resource-123"],
            from_instance_id="instance-1",
            to_instance_id="instance-2",
            verify_ownership=True,
            reason="Load balancing",
        )

        # Verify transfer ID generated
        assert transfer_id.startswith("transfer_")

        # Verify ownership was checked
        resource_service.get_resource_owner.assert_called_once_with("resource-123")

        # Verify instances were validated
        assert resource_registry.get_instance.call_count == 2
        resource_registry.get_instance.assert_any_call("test-service", "instance-1")
        resource_registry.get_instance.assert_any_call("test-service", "instance-2")

        # Verify transfer was executed
        resource_registry.transfer_resource.assert_called_once_with(
            resource_id="resource-123",
            from_instance_id="instance-1",
            to_instance_id="instance-2",
        )

        # Verify event was published
        event_bus.publish.assert_called_once()
        event = event_bus.publish.call_args[0][0]
        assert event.event_type == "resource.transferred"
        assert event.data["transfer_id"] == transfer_id
        assert event.data["resource_ids"] == ["resource-123"]

    @pytest.mark.asyncio
    async def test_transfer_without_ownership_verification(
        self,
        transfer_service: ResourceTransferService,
        resource_registry: MagicMock,
        resource_service: MagicMock,
        sample_resource: Resource,
    ) -> None:
        """Test transfer without ownership verification."""
        # Setup mocks
        resource_registry.get_instance.side_effect = [
            ServiceInstance(
                service_name="test-service",
                instance_id="instance-1",
                registered_at=datetime.now(UTC),
            ),
            ServiceInstance(
                service_name="test-service",
                instance_id="instance-2",
                registered_at=datetime.now(UTC),
            ),
        ]
        resource_registry.transfer_resource.return_value = sample_resource

        # Perform transfer without verification
        await transfer_service.transfer_resources(
            resource_ids=["resource-123"],
            from_instance_id="instance-1",
            to_instance_id="instance-2",
            verify_ownership=False,  # Skip ownership check
            reason="Admin transfer",
        )

        # Verify ownership was NOT checked
        resource_service.get_resource_owner.assert_not_called()

        # Verify transfer was still executed
        resource_registry.transfer_resource.assert_called_once()

    @pytest.mark.asyncio
    async def test_transfer_with_invalid_ownership(
        self,
        transfer_service: ResourceTransferService,
        resource_service: MagicMock,
        resource_registry: MagicMock,
    ) -> None:
        """Test transfer fails with invalid ownership."""
        # Setup mocks - resource owned by different instance
        resource_service.get_resource_owner.return_value = "instance-3"
        resource_registry.get_instance.return_value = ServiceInstance(
            service_name="test-service",
            instance_id="instance-1",
            registered_at=datetime.now(UTC),
        )

        # Attempt transfer
        with pytest.raises(ValidationError) as exc_info:
            await transfer_service.transfer_resources(
                resource_ids=["resource-123"],
                from_instance_id="instance-1",
                to_instance_id="instance-2",
                verify_ownership=True,
                reason="Invalid transfer",
            )

        assert "not owned by instance-1" in str(exc_info.value)

        # Verify transfer was NOT attempted
        resource_registry.transfer_resource.assert_not_called()

    @pytest.mark.asyncio
    async def test_transfer_to_non_existent_instance(
        self,
        transfer_service: ResourceTransferService,
        resource_service: MagicMock,
        resource_registry: MagicMock,
    ) -> None:
        """Test transfer fails when target instance doesn't exist."""
        # Setup mocks
        resource_service.get_resource_owner.return_value = "instance-1"
        resource_registry.get_instance.side_effect = [
            ServiceInstance(  # From instance exists
                service_name="test-service",
                instance_id="instance-1",
                registered_at=datetime.now(UTC),
            ),
            None,  # To instance doesn't exist
        ]

        # Attempt transfer
        with pytest.raises(NotFoundError) as exc_info:
            await transfer_service.transfer_resources(
                resource_ids=["resource-123"],
                from_instance_id="instance-1",
                to_instance_id="instance-2",
                verify_ownership=True,
                reason="Transfer to non-existent",
            )

        assert "Target instance instance-2 not found" in str(exc_info.value)

        # Verify transfer was NOT attempted
        resource_registry.transfer_resource.assert_not_called()

    @pytest.mark.asyncio
    async def test_transfer_multiple_resources(
        self,
        transfer_service: ResourceTransferService,
        resource_service: MagicMock,
        resource_registry: MagicMock,
        event_bus: MagicMock,
    ) -> None:
        """Test transferring multiple resources."""
        resource_ids = ["res-1", "res-2", "res-3"]

        # Setup mocks
        resource_service.get_resource_owner.side_effect = [
            "instance-1",  # res-1
            "instance-1",  # res-2
            "instance-1",  # res-3
        ]
        resource_registry.get_instance.side_effect = [
            ServiceInstance(
                service_name="test-service",
                instance_id="instance-1",
                registered_at=datetime.now(UTC),
            ),
            ServiceInstance(
                service_name="test-service",
                instance_id="instance-2",
                registered_at=datetime.now(UTC),
            ),
        ]
        resource_registry.transfer_resource.return_value = MagicMock()

        # Perform transfer
        _ = await transfer_service.transfer_resources(
            resource_ids=resource_ids,
            from_instance_id="instance-1",
            to_instance_id="instance-2",
            verify_ownership=True,
            reason="Batch transfer",
        )

        # Verify all ownership checks
        assert resource_service.get_resource_owner.call_count == 3

        # Verify all transfers executed
        assert resource_registry.transfer_resource.call_count == 3
        calls = [
            call(
                resource_id="res-1",
                from_instance_id="instance-1",
                to_instance_id="instance-2",
            ),
            call(
                resource_id="res-2",
                from_instance_id="instance-1",
                to_instance_id="instance-2",
            ),
            call(
                resource_id="res-3",
                from_instance_id="instance-1",
                to_instance_id="instance-2",
            ),
        ]
        resource_registry.transfer_resource.assert_has_calls(calls, any_order=False)

        # Verify event includes all resources
        event = event_bus.publish.call_args[0][0]
        assert event.data["resource_ids"] == resource_ids
        assert event.data["success_count"] == 3
        assert event.data["failure_count"] == 0

    @pytest.mark.asyncio
    async def test_partial_transfer_failure(
        self,
        transfer_service: ResourceTransferService,
        resource_service: MagicMock,
        resource_registry: MagicMock,
        event_bus: MagicMock,
    ) -> None:
        """Test handling partial transfer failures."""
        resource_ids = ["res-1", "res-2", "res-3"]

        # Setup mocks
        resource_service.get_resource_owner.side_effect = [
            "instance-1",  # res-1
            "instance-1",  # res-2
            "instance-2",  # res-3 owned by different instance
        ]
        resource_registry.get_instance.side_effect = [
            ServiceInstance(
                service_name="test-service",
                instance_id="instance-1",
                registered_at=datetime.now(UTC),
            ),
            ServiceInstance(
                service_name="test-service",
                instance_id="instance-2",
                registered_at=datetime.now(UTC),
            ),
        ]
        resource_registry.transfer_resource.return_value = MagicMock()

        # Perform transfer - should partially succeed
        _ = await transfer_service.transfer_resources(
            resource_ids=resource_ids,
            from_instance_id="instance-1",
            to_instance_id="instance-2",
            verify_ownership=True,
            reason="Partial transfer",
        )

        # Verify only valid resources were transferred
        assert resource_registry.transfer_resource.call_count == 2

        # Verify event shows partial success
        event = event_bus.publish.call_args[0][0]
        assert event.data["success_count"] == 2
        assert event.data["failure_count"] == 1
        assert "res-3" in event.data["failed_resources"]


class TestResourceTransferAtomicity:
    """Test atomicity of resource transfer operations."""

    @pytest.fixture
    def registry(self) -> ResourceRegistry:
        """Create a real ResourceRegistry for atomicity testing."""
        return ResourceRegistry()

    @pytest_asyncio.fixture
    async def instances(self, registry: ResourceRegistry) -> list[ServiceInstance]:
        """Create and register test instances."""
        instances = []
        for i in range(3):
            instance = ServiceInstance(
                service_name="test-service",
                instance_id=f"instance-{i}",
                registered_at=datetime.now(UTC),
            )
            await registry.register_instance(instance)
            instances.append(instance)
        return instances

    @pytest.mark.asyncio
    async def test_atomic_transfer_success(
        self, registry: ResourceRegistry, instances: list[ServiceInstance]
    ) -> None:
        """Test that successful transfers are atomic."""
        # Register a resource
        _ = await registry.register_resource(
            service_name="test-service",
            instance_id="instance-0",
            resource_id="atomic-resource",
            metadata=ResourceMetadata(
                resource_type="test",
                version=1,
                created_by="test",
                last_modified=datetime.now(UTC),
            ),
        )

        # Perform atomic transfer
        transferred = await registry.transfer_resource(
            resource_id="atomic-resource",
            from_instance_id="instance-0",
            to_instance_id="instance-1",
        )

        # Verify atomicity - resource has new owner
        assert transferred.owner_instance_id == "instance-1"

        # Verify ownership is consistent
        owner = await registry.get_resource_owner("atomic-resource")
        assert owner == "instance-1"

        # Verify old instance no longer owns it
        instance0_resources = await registry.get_instance_resources("test-service", "instance-0")
        assert len(instance0_resources) == 0

        # Verify new instance owns it
        instance1_resources = await registry.get_instance_resources("test-service", "instance-1")
        assert len(instance1_resources) == 1
        assert instance1_resources[0].resource_id == "atomic-resource"

    @pytest.mark.asyncio
    async def test_concurrent_transfer_atomicity(
        self, registry: ResourceRegistry, instances: list[ServiceInstance]
    ) -> None:
        """Test atomicity under concurrent transfer attempts."""
        # Register a resource
        await registry.register_resource(
            service_name="test-service",
            instance_id="instance-0",
            resource_id="concurrent-transfer",
            metadata=ResourceMetadata(
                resource_type="test",
                version=1,
                created_by="test",
                last_modified=datetime.now(UTC),
            ),
        )

        # Attempt concurrent transfers to different instances
        async def transfer_to_instance(target_idx: int) -> Resource | None:
            try:
                return await registry.transfer_resource(
                    resource_id="concurrent-transfer",
                    from_instance_id="instance-0",
                    to_instance_id=f"instance-{target_idx}",
                )
            except Exception:
                return None

        # Run concurrent transfers
        results = await asyncio.gather(
            transfer_to_instance(1),
            transfer_to_instance(2),
            return_exceptions=False,
        )

        # Only one should succeed
        successful = [r for r in results if r is not None]
        assert len(successful) == 1

        # Verify final state is consistent
        final_owner = await registry.get_resource_owner("concurrent-transfer")
        assert final_owner in ["instance-1", "instance-2"]
        assert final_owner == successful[0].owner_instance_id

    @pytest.mark.asyncio
    async def test_transfer_rollback_on_error(
        self, registry: ResourceRegistry, instances: list[ServiceInstance]
    ) -> None:
        """Test that failed transfers don't leave inconsistent state."""
        # Register a resource
        await registry.register_resource(
            service_name="test-service",
            instance_id="instance-0",
            resource_id="rollback-test",
            metadata=ResourceMetadata(
                resource_type="test",
                version=1,
                created_by="test",
                last_modified=datetime.now(UTC),
            ),
        )

        # Attempt transfer to non-existent instance
        with pytest.raises(NotFoundError):
            await registry.transfer_resource(
                resource_id="rollback-test",
                from_instance_id="instance-0",
                to_instance_id="non-existent",
            )

        # Verify resource still owned by original instance
        owner = await registry.get_resource_owner("rollback-test")
        assert owner == "instance-0"

        # Verify instance still has the resource
        resources = await registry.get_instance_resources("test-service", "instance-0")
        assert len(resources) == 1
        assert resources[0].resource_id == "rollback-test"

    @pytest.mark.asyncio
    async def test_transfer_expired_resource_fails(
        self, registry: ResourceRegistry, instances: list[ServiceInstance]
    ) -> None:
        """Test that expired resources cannot be transferred."""
        # Register a resource with short TTL
        past_time = datetime.now(UTC) - timedelta(hours=2)
        metadata = ResourceMetadata(
            resource_type="session",
            version=1,
            created_by="test",
            last_modified=past_time,
            ttl_seconds=3600,  # 1 hour TTL
        )

        # Manually add expired resource
        resource = Resource(
            resource_id="expired-resource",
            owner_instance_id="instance-0",
            service_name="test-service",
            registered_at=past_time,
            metadata=metadata,
        )
        registry._resources["expired-resource"] = resource
        registry._instance_resources["instance-0"] = {"expired-resource"}

        # Attempt to transfer expired resource
        with pytest.raises(ValidationError) as exc_info:
            await registry.transfer_resource(
                resource_id="expired-resource",
                from_instance_id="instance-0",
                to_instance_id="instance-1",
            )

        assert "expired" in str(exc_info.value).lower()

        # Verify resource wasn't transferred
        owner = await registry.get_resource_owner("expired-resource")
        assert owner == "instance-0"

    @pytest.mark.asyncio
    async def test_transfer_chain_atomicity(
        self, registry: ResourceRegistry, instances: list[ServiceInstance]
    ) -> None:
        """Test atomicity of chained transfers."""
        # Register a resource
        await registry.register_resource(
            service_name="test-service",
            instance_id="instance-0",
            resource_id="chain-test",
            metadata=ResourceMetadata(
                resource_type="test",
                version=1,
                created_by="test",
                last_modified=datetime.now(UTC),
            ),
        )

        # Perform chain of transfers
        # 0 -> 1
        await registry.transfer_resource(
            resource_id="chain-test",
            from_instance_id="instance-0",
            to_instance_id="instance-1",
        )

        # 1 -> 2
        await registry.transfer_resource(
            resource_id="chain-test",
            from_instance_id="instance-1",
            to_instance_id="instance-2",
        )

        # 2 -> 0 (back to start)
        await registry.transfer_resource(
            resource_id="chain-test",
            from_instance_id="instance-2",
            to_instance_id="instance-0",
        )

        # Verify final state
        owner = await registry.get_resource_owner("chain-test")
        assert owner == "instance-0"

        # Verify only final owner has the resource
        for i in range(3):
            resources = await registry.get_instance_resources("test-service", f"instance-{i}")
            if i == 0:
                assert len(resources) == 1
                assert resources[0].resource_id == "chain-test"
            else:
                assert len(resources) == 0

    @pytest.mark.asyncio
    async def test_audit_trail_integrity(
        self,
        registry: ResourceRegistry,
        instances: list[ServiceInstance],
    ) -> None:
        """Test that transfer audit trail maintains integrity."""
        event_bus = MagicMock(spec=EventBus)
        event_bus.publish = AsyncMock()

        # Create services with event bus
        resource_service = ResourceService(
            resource_registry=registry,
            resource_validator=MagicMock(),
            event_bus=event_bus,
        )

        transfer_service = ResourceTransferService(
            resource_registry=registry,
            resource_service=resource_service,
            event_bus=event_bus,
        )

        # Register resource
        await registry.register_resource(
            service_name="test-service",
            instance_id="instance-0",
            resource_id="audit-test",
            metadata=ResourceMetadata(
                resource_type="test",
                version=1,
                created_by="test",
                last_modified=datetime.now(UTC),
            ),
        )

        # Perform transfer
        transfer_id = await transfer_service.transfer_resources(
            resource_ids=["audit-test"],
            from_instance_id="instance-0",
            to_instance_id="instance-1",
            verify_ownership=False,
            reason="Audit test transfer",
        )

        # Verify audit event
        event_bus.publish.assert_called()
        event = event_bus.publish.call_args[0][0]

        assert event.event_type == "resource.transferred"
        assert event.data["transfer_id"] == transfer_id
        assert event.data["from_instance_id"] == "instance-0"
        assert event.data["to_instance_id"] == "instance-1"
        assert event.data["reason"] == "Audit test transfer"
        assert event.data["resource_ids"] == ["audit-test"]
        assert event.data["success_count"] == 1
        assert event.data["failure_count"] == 0
