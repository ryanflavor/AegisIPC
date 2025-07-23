"""Complete unit tests for ResourceService to achieve 80%+ coverage."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from ipc_client_sdk.models import ServiceInfo, ServiceInstanceInfo
from ipc_router.application.services import ResourceRegistry, ResourceService
from ipc_router.domain.entities import Resource, ResourceMetadata
from ipc_router.domain.events import ServiceEventType
from ipc_router.domain.exceptions import (
    NotFoundError,
    ResourceConflictError,
    ResourceNotFoundError,
    ValidationError,
)


class TestResourceServiceComplete:
    """Complete test suite for ResourceService."""

    @pytest.fixture
    def mock_registry(self) -> MagicMock:
        """Create a mock ResourceRegistry."""
        mock = MagicMock(spec=ResourceRegistry)
        mock.register_resource = AsyncMock()
        mock.release_resource = AsyncMock()
        mock.get_resource = AsyncMock()
        mock.get_service = AsyncMock()
        mock.list_resources_by_instance = AsyncMock()
        mock.list_resources_by_service = AsyncMock()
        mock.transfer_resource = AsyncMock()
        mock.check_resource_health = AsyncMock()
        mock.cleanup_expired_resources = AsyncMock()
        mock._emit_event = AsyncMock()
        return mock

    @pytest.fixture
    def resource_service(self, mock_registry: MagicMock) -> ResourceService:
        """Create a ResourceService instance."""
        return ResourceService(registry=mock_registry)

    @pytest.fixture
    def valid_metadata(self) -> ResourceMetadata:
        """Create valid resource metadata."""
        return ResourceMetadata(
            resource_type="test_resource",
            version=1,
            created_by="test-service",
            last_modified=datetime.now(UTC),
            ttl_seconds=3600,
            priority=5,
            tags=["test", "active"],
            attributes={"key": "value"},
        )

    @pytest.fixture
    def expired_metadata(self) -> ResourceMetadata:
        """Create expired resource metadata."""
        return ResourceMetadata(
            resource_type="test_resource",
            version=1,
            created_by="test-service",
            last_modified=datetime.now(UTC) - timedelta(hours=2),
            ttl_seconds=3600,  # 1 hour TTL
            priority=5,
            tags=["test", "expired"],
            attributes={},
        )

    @pytest.fixture
    def valid_resource(self, valid_metadata: ResourceMetadata) -> Resource:
        """Create a valid resource."""
        return Resource(
            resource_id="resource-123",
            owner_instance_id="instance-1",
            service_name="test-service",
            registered_at=datetime.now(UTC),
            metadata=valid_metadata,
        )

    @pytest.fixture
    def expired_resource(self, expired_metadata: ResourceMetadata) -> Resource:
        """Create an expired resource."""
        return Resource(
            resource_id="expired-123",
            owner_instance_id="instance-1",
            service_name="test-service",
            registered_at=datetime.now(UTC) - timedelta(hours=2),
            metadata=expired_metadata,
        )

    @pytest.fixture
    def service_info(self) -> ServiceInfo:
        """Create a mock service info with multiple instances."""
        instance1 = ServiceInstanceInfo(
            instance_id="instance-1",
            status="ONLINE",
            registered_at=datetime.now(UTC),
            last_heartbeat=datetime.now(UTC),
            metadata={},
        )
        instance2 = ServiceInstanceInfo(
            instance_id="instance-2",
            status="ONLINE",
            registered_at=datetime.now(UTC),
            last_heartbeat=datetime.now(UTC),
            metadata={},
        )
        return ServiceInfo(
            name="test-service",
            instances=[instance1, instance2],
            created_at=datetime.now(UTC),
            metadata={},
        )

    # Test ResourceEvent class
    @pytest.mark.asyncio
    async def test_resource_event_creation(self, valid_resource: Resource) -> None:
        """Test ResourceEvent creation."""
        from ipc_router.application.services.resource_service import ResourceEvent

        event = ResourceEvent(
            event_type=ServiceEventType.INSTANCE_REGISTERED,
            resource_id="res-123",
            service_name="test-service",
            instance_id="inst-1",
            metadata={"action": "test"},
        )

        assert event.resource_id == "res-123"
        assert event.service_name == "test-service"
        assert event.instance_id == "inst-1"
        assert event.metadata["resource_id"] == "res-123"
        assert event.metadata["action"] == "test"
        assert event.event_type == ServiceEventType.INSTANCE_REGISTERED

    # Test register_resource method
    @pytest.mark.asyncio
    async def test_register_resource_success(
        self,
        resource_service: ResourceService,
        mock_registry: MagicMock,
        valid_resource: Resource,
        valid_metadata: ResourceMetadata,
        service_info: ServiceInfo,
    ) -> None:
        """Test successful resource registration."""
        # Setup mocks
        mock_registry.get_service.return_value = service_info
        mock_registry.get_resource.return_value = None  # No existing resource
        mock_registry.register_resource.return_value = valid_resource

        # Register resource
        result = await resource_service.register_resource(
            service_name="test-service",
            instance_id="instance-1",
            resource_id="resource-123",
            metadata=valid_metadata,
        )

        assert result == valid_resource
        mock_registry.register_resource.assert_called_once_with(
            resource_id="resource-123",
            owner_instance_id="instance-1",
            service_name="test-service",
            metadata=valid_metadata,
            force=False,
        )
        # Verify event was emitted
        mock_registry._emit_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_register_resource_service_not_found(
        self,
        resource_service: ResourceService,
        mock_registry: MagicMock,
        valid_metadata: ResourceMetadata,
    ) -> None:
        """Test resource registration when service not found."""
        # Setup service not found
        mock_registry.get_service.side_effect = NotFoundError(
            resource_type="Service", resource_id="test-service"
        )

        # Try to register
        with pytest.raises(ValidationError) as exc_info:
            await resource_service.register_resource(
                service_name="test-service",
                instance_id="instance-1",
                resource_id="resource-123",
                metadata=valid_metadata,
            )

        assert "Service 'test-service' not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_register_resource_instance_not_found(
        self,
        resource_service: ResourceService,
        mock_registry: MagicMock,
        valid_metadata: ResourceMetadata,
        service_info: ServiceInfo,
    ) -> None:
        """Test resource registration when instance not found."""
        # Setup service exists but instance doesn't
        mock_registry.get_service.return_value = service_info

        # Try to register with non-existent instance
        with pytest.raises(ValidationError) as exc_info:
            await resource_service.register_resource(
                service_name="test-service",
                instance_id="instance-999",  # Non-existent
                resource_id="resource-123",
                metadata=valid_metadata,
            )

        assert "Instance 'instance-999' not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_register_resource_conflict(
        self,
        resource_service: ResourceService,
        mock_registry: MagicMock,
        valid_metadata: ResourceMetadata,
        service_info: ServiceInfo,
    ) -> None:
        """Test resource registration conflict."""
        # Setup mocks
        mock_registry.get_service.return_value = service_info
        mock_registry.get_resource.return_value = None
        mock_registry.register_resource.side_effect = ResourceConflictError(
            resource_id="resource-123", current_owner="instance-2"
        )

        # Try to register
        with pytest.raises(ResourceConflictError):
            await resource_service.register_resource(
                service_name="test-service",
                instance_id="instance-1",
                resource_id="resource-123",
                metadata=valid_metadata,
            )

    @pytest.mark.asyncio
    async def test_register_resource_with_force(
        self,
        resource_service: ResourceService,
        mock_registry: MagicMock,
        valid_resource: Resource,
        valid_metadata: ResourceMetadata,
        service_info: ServiceInfo,
    ) -> None:
        """Test force resource registration with existing resource."""
        # Setup existing resource owned by different instance
        existing_resource = Resource(
            resource_id="resource-123",
            owner_instance_id="instance-2",
            service_name="test-service",
            registered_at=datetime.now(UTC),
            metadata=valid_metadata,
        )
        mock_registry.get_service.return_value = service_info
        mock_registry.get_resource.return_value = existing_resource
        mock_registry.register_resource.return_value = valid_resource

        # Register with force
        result = await resource_service.register_resource(
            service_name="test-service",
            instance_id="instance-1",
            resource_id="resource-123",
            metadata=valid_metadata,
            force=True,
        )

        assert result == valid_resource
        mock_registry.register_resource.assert_called_once_with(
            resource_id="resource-123",
            owner_instance_id="instance-1",
            service_name="test-service",
            metadata=valid_metadata,
            force=True,
        )

    @pytest.mark.asyncio
    async def test_register_resource_no_notify(
        self,
        resource_service: ResourceService,
        mock_registry: MagicMock,
        valid_resource: Resource,
        valid_metadata: ResourceMetadata,
        service_info: ServiceInfo,
    ) -> None:
        """Test resource registration without notification."""
        # Setup mocks
        mock_registry.get_service.return_value = service_info
        mock_registry.get_resource.return_value = None
        mock_registry.register_resource.return_value = valid_resource

        # Register without notification
        result = await resource_service.register_resource(
            service_name="test-service",
            instance_id="instance-1",
            resource_id="resource-123",
            metadata=valid_metadata,
            notify=False,
        )

        assert result == valid_resource
        # Verify no event was emitted
        mock_registry._emit_event.assert_not_called()

    # Test release_resource method
    @pytest.mark.asyncio
    async def test_release_resource_success(
        self,
        resource_service: ResourceService,
        mock_registry: MagicMock,
        valid_resource: Resource,
    ) -> None:
        """Test successful resource release."""
        # Setup mocks
        mock_registry.get_resource.return_value = valid_resource
        mock_registry.release_resource.return_value = True

        # Release resource
        result = await resource_service.release_resource(
            resource_id="resource-123",
            instance_id="instance-1",
        )

        assert result is True
        mock_registry.release_resource.assert_called_once_with("resource-123", "instance-1")
        # Verify event was emitted
        mock_registry._emit_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_release_resource_not_found(
        self,
        resource_service: ResourceService,
        mock_registry: MagicMock,
    ) -> None:
        """Test releasing non-existent resource."""
        # Setup resource not found
        mock_registry.get_resource.return_value = None

        # Release resource
        result = await resource_service.release_resource(
            resource_id="resource-123",
            instance_id="instance-1",
        )

        assert result is False
        mock_registry.release_resource.assert_not_called()

    @pytest.mark.asyncio
    async def test_release_resource_no_notify(
        self,
        resource_service: ResourceService,
        mock_registry: MagicMock,
        valid_resource: Resource,
    ) -> None:
        """Test resource release without notification."""
        # Setup mocks
        mock_registry.get_resource.return_value = valid_resource
        mock_registry.release_resource.return_value = True

        # Release without notification
        result = await resource_service.release_resource(
            resource_id="resource-123",
            instance_id="instance-1",
            notify=False,
        )

        assert result is True
        # Verify no event was emitted
        mock_registry._emit_event.assert_not_called()

    # Test query_resources method
    @pytest.mark.asyncio
    async def test_query_resources_by_instance(
        self,
        resource_service: ResourceService,
        mock_registry: MagicMock,
        valid_resource: Resource,
    ) -> None:
        """Test querying resources by instance."""
        # Setup mocks
        mock_registry.list_resources_by_instance.return_value = [valid_resource]

        # Query by instance
        resources = await resource_service.query_resources(instance_id="instance-1")

        assert len(resources) == 1
        assert resources[0] == valid_resource
        mock_registry.list_resources_by_instance.assert_called_once_with("instance-1")

    @pytest.mark.asyncio
    async def test_query_resources_by_service(
        self,
        resource_service: ResourceService,
        mock_registry: MagicMock,
        valid_resource: Resource,
    ) -> None:
        """Test querying resources by service."""
        # Setup mocks
        mock_registry.list_resources_by_service.return_value = [valid_resource]

        # Query by service
        resources = await resource_service.query_resources(
            service_name="test-service",
            resource_type="test_resource",
            tags=["active"],
        )

        assert len(resources) == 1
        assert resources[0] == valid_resource
        mock_registry.list_resources_by_service.assert_called_once_with(
            "test-service", "test_resource", ["active"]
        )

    @pytest.mark.asyncio
    async def test_query_resources_with_both_filters(
        self,
        resource_service: ResourceService,
        mock_registry: MagicMock,
        valid_resource: Resource,
    ) -> None:
        """Test querying resources with both service and instance filters."""
        # Create resources for different services
        resource1 = valid_resource  # test-service
        resource2 = Resource(
            resource_id="resource-456",
            owner_instance_id="instance-1",
            service_name="other-service",
            registered_at=datetime.now(UTC),
            metadata=valid_resource.metadata,
        )

        mock_registry.list_resources_by_instance.return_value = [resource1, resource2]

        # Query with both filters
        resources = await resource_service.query_resources(
            service_name="test-service", instance_id="instance-1"
        )

        assert len(resources) == 1
        assert resources[0].service_name == "test-service"

    @pytest.mark.asyncio
    async def test_query_resources_exclude_expired(
        self,
        resource_service: ResourceService,
        mock_registry: MagicMock,
        valid_resource: Resource,
        expired_resource: Resource,
    ) -> None:
        """Test querying resources excludes expired by default."""
        # Setup mix of valid and expired resources
        mock_registry.list_resources_by_instance.return_value = [
            valid_resource,
            expired_resource,
        ]

        # Query without include_expired
        resources = await resource_service.query_resources(instance_id="instance-1")

        assert len(resources) == 1
        assert resources[0] == valid_resource

    @pytest.mark.asyncio
    async def test_query_resources_include_expired(
        self,
        resource_service: ResourceService,
        mock_registry: MagicMock,
        valid_resource: Resource,
        expired_resource: Resource,
    ) -> None:
        """Test querying resources includes expired when requested."""
        # Setup mix of valid and expired resources
        mock_registry.list_resources_by_instance.return_value = [
            valid_resource,
            expired_resource,
        ]

        # Query with include_expired
        resources = await resource_service.query_resources(
            instance_id="instance-1",
            include_expired=True,
        )

        assert len(resources) == 2

    @pytest.mark.asyncio
    async def test_query_resources_no_filter(
        self,
        resource_service: ResourceService,
        mock_registry: MagicMock,
    ) -> None:
        """Test querying resources without filter returns empty."""
        # Query without any filter
        resources = await resource_service.query_resources()

        assert resources == []
        mock_registry.list_resources_by_instance.assert_not_called()
        mock_registry.list_resources_by_service.assert_not_called()

    # Test transfer_resource method
    @pytest.mark.asyncio
    async def test_transfer_resource_success(
        self,
        resource_service: ResourceService,
        mock_registry: MagicMock,
        valid_resource: Resource,
        service_info: ServiceInfo,
    ) -> None:
        """Test successful resource transfer."""
        # Setup mocks
        mock_registry.get_resource.return_value = valid_resource
        mock_registry.get_service.return_value = service_info

        # Create transferred resource
        transferred_resource = Resource(
            resource_id=valid_resource.resource_id,
            owner_instance_id="instance-2",  # New owner
            service_name=valid_resource.service_name,
            registered_at=valid_resource.registered_at,
            metadata=valid_resource.metadata,
        )
        mock_registry.transfer_resource.return_value = transferred_resource

        # Transfer resource
        result = await resource_service.transfer_resource(
            resource_id="resource-123",
            from_instance_id="instance-1",
            to_instance_id="instance-2",
            reason="Load balancing",
        )

        assert result == transferred_resource
        mock_registry.transfer_resource.assert_called_once_with(
            resource_id="resource-123",
            from_instance_id="instance-1",
            to_instance_id="instance-2",
        )
        # Verify event was emitted
        mock_registry._emit_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_transfer_resource_not_found(
        self,
        resource_service: ResourceService,
        mock_registry: MagicMock,
    ) -> None:
        """Test transferring non-existent resource."""
        # Setup resource not found
        mock_registry.get_resource.return_value = None

        # Try to transfer
        with pytest.raises(ResourceNotFoundError):
            await resource_service.transfer_resource(
                resource_id="resource-123",
                from_instance_id="instance-1",
                to_instance_id="instance-2",
                reason="Test",
            )

    @pytest.mark.asyncio
    async def test_transfer_resource_target_not_found(
        self,
        resource_service: ResourceService,
        mock_registry: MagicMock,
        valid_resource: Resource,
        service_info: ServiceInfo,
    ) -> None:
        """Test transfer when target instance not found."""
        # Setup mocks
        mock_registry.get_resource.return_value = valid_resource
        mock_registry.get_service.return_value = service_info

        # Try to transfer to non-existent instance
        with pytest.raises(ValidationError) as exc_info:
            await resource_service.transfer_resource(
                resource_id="resource-123",
                from_instance_id="instance-1",
                to_instance_id="instance-999",  # Non-existent
                reason="Test",
            )

        assert "Target instance 'instance-999' not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_transfer_resource_service_not_found(
        self,
        resource_service: ResourceService,
        mock_registry: MagicMock,
        valid_resource: Resource,
    ) -> None:
        """Test transfer when service not found."""
        # Setup mocks
        mock_registry.get_resource.return_value = valid_resource
        mock_registry.get_service.side_effect = NotFoundError(
            resource_type="Service", resource_id="test-service"
        )

        # Try to transfer
        with pytest.raises(ValidationError) as exc_info:
            await resource_service.transfer_resource(
                resource_id="resource-123",
                from_instance_id="instance-1",
                to_instance_id="instance-2",
                reason="Test",
            )

        assert "Service 'test-service' not found" in str(exc_info.value)

    # Test check_resource_health method
    @pytest.mark.asyncio
    async def test_check_resource_health_not_found(
        self,
        resource_service: ResourceService,
        mock_registry: MagicMock,
    ) -> None:
        """Test health check for non-existent resource."""
        # Setup resource not found
        mock_registry.get_resource.return_value = None

        # Check health
        result = await resource_service.check_resource_health("resource-123")

        assert result == {
            "healthy": False,
            "exists": False,
            "resource_id": "resource-123",
        }

    @pytest.mark.asyncio
    async def test_check_resource_health_success(
        self,
        resource_service: ResourceService,
        mock_registry: MagicMock,
        valid_resource: Resource,
        service_info: ServiceInfo,
    ) -> None:
        """Test successful health check."""
        # Setup mocks
        mock_registry.get_resource.return_value = valid_resource
        mock_registry.check_resource_health.return_value = True
        mock_registry.get_service.return_value = service_info

        # Check health
        result = await resource_service.check_resource_health("resource-123")

        assert result["healthy"] is True
        assert result["exists"] is True
        assert result["resource_id"] == "resource-123"
        assert result["owner_instance_id"] == "instance-1"
        assert result["service_name"] == "test-service"
        assert result["instance_status"] == "ONLINE"
        assert result["is_expired"] is False
        assert result["resource_type"] == "test_resource"
        assert result["priority"] == 5
        assert result["tags"] == ["test", "active"]

    @pytest.mark.asyncio
    async def test_check_resource_health_expired(
        self,
        resource_service: ResourceService,
        mock_registry: MagicMock,
        expired_resource: Resource,
        service_info: ServiceInfo,
    ) -> None:
        """Test health check for expired resource."""
        # Setup mocks
        mock_registry.get_resource.return_value = expired_resource
        mock_registry.check_resource_health.return_value = True
        mock_registry.get_service.return_value = service_info

        # Check health
        result = await resource_service.check_resource_health("expired-123")

        assert result["healthy"] is True  # Instance is healthy
        assert result["is_expired"] is True  # But resource is expired
        assert result["time_until_expiry_seconds"] is None  # Already expired

    @pytest.mark.asyncio
    async def test_check_resource_health_with_ttl(
        self,
        resource_service: ResourceService,
        mock_registry: MagicMock,
        valid_resource: Resource,
        service_info: ServiceInfo,
    ) -> None:
        """Test health check shows time until expiry."""
        # Setup mocks
        mock_registry.get_resource.return_value = valid_resource
        mock_registry.check_resource_health.return_value = True
        mock_registry.get_service.return_value = service_info

        # Check health
        result = await resource_service.check_resource_health("resource-123")

        assert result["time_until_expiry_seconds"] is not None
        assert result["time_until_expiry_seconds"] > 0  # Should have time left

    @pytest.mark.asyncio
    async def test_check_resource_health_service_error(
        self,
        resource_service: ResourceService,
        mock_registry: MagicMock,
        valid_resource: Resource,
    ) -> None:
        """Test health check when service lookup fails."""
        # Setup mocks
        mock_registry.get_resource.return_value = valid_resource
        mock_registry.check_resource_health.return_value = True
        mock_registry.get_service.side_effect = Exception("Service error")

        # Check health
        result = await resource_service.check_resource_health("resource-123")

        # Should still return basic health info
        assert result["healthy"] is True
        assert result["exists"] is True
        assert result["instance_status"] is None  # Couldn't get status

    # Test cleanup_expired_resources method
    @pytest.mark.asyncio
    async def test_cleanup_expired_resources_success(
        self,
        resource_service: ResourceService,
        mock_registry: MagicMock,
        expired_resource: Resource,
    ) -> None:
        """Test successful cleanup of expired resources."""
        # Setup mocks
        resource_service.query_resources = AsyncMock(return_value=[expired_resource])
        mock_registry.cleanup_expired_resources.return_value = 1

        # Cleanup
        count = await resource_service.cleanup_expired_resources()

        assert count == 1
        mock_registry.cleanup_expired_resources.assert_called_once()
        # Verify event was emitted for expired resource
        mock_registry._emit_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_expired_resources_no_notify(
        self,
        resource_service: ResourceService,
        mock_registry: MagicMock,
    ) -> None:
        """Test cleanup without notifications."""
        # Setup mocks
        mock_registry.cleanup_expired_resources.return_value = 3

        # Cleanup without notify
        count = await resource_service.cleanup_expired_resources(notify=False)

        assert count == 3
        # Verify no events were emitted
        mock_registry._emit_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_cleanup_expired_resources_none_expired(
        self,
        resource_service: ResourceService,
        mock_registry: MagicMock,
    ) -> None:
        """Test cleanup when no resources are expired."""
        # Setup mocks
        resource_service.query_resources = AsyncMock(return_value=[])
        mock_registry.cleanup_expired_resources.return_value = 0

        # Cleanup
        count = await resource_service.cleanup_expired_resources()

        assert count == 0
        # No events should be emitted
        mock_registry._emit_event.assert_not_called()

    # Test event subscription methods
    @pytest.mark.asyncio
    async def test_subscribe_to_resource_events(
        self,
        resource_service: ResourceService,
    ) -> None:
        """Test subscribing to resource events."""
        # Create a handler
        handler = AsyncMock()

        # Subscribe
        resource_service.subscribe_to_resource_events("registered", handler)

        assert len(resource_service._event_handlers) == 1
        assert resource_service._event_handlers[0] == ("registered", handler)

    @pytest.mark.asyncio
    async def test_unsubscribe_from_resource_events(
        self,
        resource_service: ResourceService,
    ) -> None:
        """Test unsubscribing from resource events."""
        # Create handlers
        handler1 = AsyncMock()
        handler2 = AsyncMock()

        # Subscribe both
        resource_service.subscribe_to_resource_events("*", handler1)
        resource_service.subscribe_to_resource_events("released", handler2)

        assert len(resource_service._event_handlers) == 2

        # Unsubscribe handler1
        resource_service.unsubscribe_from_resource_events(handler1)

        assert len(resource_service._event_handlers) == 1
        assert resource_service._event_handlers[0][1] == handler2

    # Test _emit_resource_event method
    @pytest.mark.asyncio
    async def test_emit_resource_event_async_handler(
        self,
        resource_service: ResourceService,
        mock_registry: MagicMock,
        valid_resource: Resource,
    ) -> None:
        """Test emitting events to async handlers."""
        # Create async handler
        handler = AsyncMock()
        resource_service.subscribe_to_resource_events("registered", handler)

        # Emit event
        await resource_service._emit_resource_event(
            event_type=ServiceEventType.INSTANCE_REGISTERED,
            resource=valid_resource,
            metadata={"action": "registered"},
        )

        # Verify handler was called
        handler.assert_called_once()
        event = handler.call_args[0][0]
        assert event.resource_id == "resource-123"
        assert event.metadata["action"] == "registered"

    @pytest.mark.asyncio
    async def test_emit_resource_event_sync_handler(
        self,
        resource_service: ResourceService,
        mock_registry: MagicMock,
        valid_resource: Resource,
    ) -> None:
        """Test emitting events to sync handlers."""
        # Create sync handler
        handler = Mock()
        resource_service.subscribe_to_resource_events("released", handler)

        # Emit event
        await resource_service._emit_resource_event(
            event_type=ServiceEventType.INSTANCE_UNREGISTERED,
            resource=valid_resource,
            metadata={"action": "released"},
        )

        # Give time for executor to run
        await asyncio.sleep(0.1)

        # Verify handler was called
        handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_emit_resource_event_wildcard_filter(
        self,
        resource_service: ResourceService,
        mock_registry: MagicMock,
        valid_resource: Resource,
    ) -> None:
        """Test wildcard event filter."""
        # Create handler with wildcard
        handler = AsyncMock()
        resource_service.subscribe_to_resource_events("*", handler)

        # Emit different events
        await resource_service._emit_resource_event(
            event_type=ServiceEventType.INSTANCE_REGISTERED,
            resource=valid_resource,
            metadata={"action": "registered"},
        )

        await resource_service._emit_resource_event(
            event_type=ServiceEventType.INSTANCE_UNREGISTERED,
            resource=valid_resource,
            metadata={"action": "released"},
        )

        # Handler should be called for both
        assert handler.call_count == 2

    @pytest.mark.asyncio
    async def test_emit_resource_event_handler_exception(
        self,
        resource_service: ResourceService,
        mock_registry: MagicMock,
        valid_resource: Resource,
    ) -> None:
        """Test event emission continues despite handler exceptions."""
        # Create handlers - one fails, one succeeds
        failing_handler = AsyncMock(side_effect=Exception("Handler error"))
        working_handler = AsyncMock()

        resource_service.subscribe_to_resource_events("*", failing_handler)
        resource_service.subscribe_to_resource_events("*", working_handler)

        # Emit event
        await resource_service._emit_resource_event(
            event_type=ServiceEventType.INSTANCE_REGISTERED,
            resource=valid_resource,
            metadata={"action": "registered"},
        )

        # Both handlers should be called despite exception
        failing_handler.assert_called_once()
        working_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_emit_resource_event_filter_matching(
        self,
        resource_service: ResourceService,
        mock_registry: MagicMock,
        valid_resource: Resource,
    ) -> None:
        """Test event filter matching logic."""
        # Create handlers with different filters
        registered_handler = AsyncMock()
        released_handler = AsyncMock()
        wildcard_handler = AsyncMock()

        resource_service.subscribe_to_resource_events("registered", registered_handler)
        resource_service.subscribe_to_resource_events("released", released_handler)
        resource_service.subscribe_to_resource_events("*", wildcard_handler)

        # Emit registered event
        await resource_service._emit_resource_event(
            event_type=ServiceEventType.INSTANCE_REGISTERED,
            resource=valid_resource,
            metadata={"action": "registered"},
        )

        # Only registered and wildcard handlers should be called
        registered_handler.assert_called_once()
        released_handler.assert_not_called()
        wildcard_handler.assert_called_once()

    # Integration test for full workflow
    @pytest.mark.asyncio
    async def test_full_resource_lifecycle(
        self,
        resource_service: ResourceService,
        mock_registry: MagicMock,
        valid_resource: Resource,
        valid_metadata: ResourceMetadata,
        service_info: ServiceInfo,
    ) -> None:
        """Test complete resource lifecycle."""
        # Setup event handler to track events
        events_received = []

        async def event_handler(event):
            events_received.append(event)

        resource_service.subscribe_to_resource_events("*", event_handler)

        # 1. Register resource
        mock_registry.get_service.return_value = service_info
        mock_registry.get_resource.return_value = None
        mock_registry.register_resource.return_value = valid_resource

        registered = await resource_service.register_resource(
            service_name="test-service",
            instance_id="instance-1",
            resource_id="resource-123",
            metadata=valid_metadata,
        )

        assert registered.resource_id == "resource-123"

        # 2. Check health
        mock_registry.get_resource.return_value = valid_resource
        mock_registry.check_resource_health.return_value = True

        health = await resource_service.check_resource_health("resource-123")
        assert health["healthy"] is True

        # 3. Transfer resource
        transferred_resource = Resource(
            resource_id="resource-123",
            owner_instance_id="instance-2",
            service_name="test-service",
            registered_at=valid_resource.registered_at,
            metadata=valid_resource.metadata,
        )
        mock_registry.transfer_resource.return_value = transferred_resource

        transferred = await resource_service.transfer_resource(
            resource_id="resource-123",
            from_instance_id="instance-1",
            to_instance_id="instance-2",
            reason="Load balancing",
        )

        assert transferred.owner_instance_id == "instance-2"

        # 4. Release resource
        mock_registry.get_resource.return_value = transferred_resource
        mock_registry.release_resource.return_value = True

        released = await resource_service.release_resource(
            resource_id="resource-123",
            instance_id="instance-2",
        )

        assert released is True

        # Verify events were emitted
        assert len(events_received) == 3  # register, transfer, release
