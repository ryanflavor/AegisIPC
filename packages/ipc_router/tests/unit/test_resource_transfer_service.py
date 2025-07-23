"""Unit tests for ResourceTransferService."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from ipc_client_sdk.models import ServiceInfo, ServiceInstanceInfo
from ipc_router.application.services import ResourceRegistry, ResourceTransferService
from ipc_router.application.services.service_registry import ServiceRegistry
from ipc_router.domain.entities import Resource, ResourceMetadata
from ipc_router.domain.exceptions import (
    NotFoundError,
    ResourceNotFoundError,
    ValidationError,
)


class TestResourceTransferService:
    """Test ResourceTransferService functionality."""

    @pytest.fixture
    def mock_resource_registry(self) -> MagicMock:
        """Create a mock ResourceRegistry."""
        mock = MagicMock(spec=ResourceRegistry)
        mock.get_resource_owner = AsyncMock()
        mock.get_resource = AsyncMock()
        mock.release_resource = AsyncMock()
        mock.register_resource = AsyncMock()
        mock.transfer_resource = AsyncMock()
        return mock

    @pytest.fixture
    def mock_service_registry(self) -> MagicMock:
        """Create a mock ServiceRegistry."""
        mock = MagicMock(spec=ServiceRegistry)
        mock.get_service = AsyncMock()
        return mock

    @pytest.fixture
    def transfer_service(
        self,
        mock_resource_registry: MagicMock,
        mock_service_registry: MagicMock,
    ) -> ResourceTransferService:
        """Create a ResourceTransferService instance."""
        return ResourceTransferService(
            resource_registry=mock_resource_registry,
            service_registry=mock_service_registry,
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

    @pytest.fixture
    def service_info(self) -> ServiceInfo:
        """Create service info with healthy instances."""
        return ServiceInfo(
            name="test-service",
            instances=[
                ServiceInstanceInfo(
                    instance_id="instance-1",
                    status="ONLINE",
                    registered_at="2025-01-01T00:00:00Z",
                    last_heartbeat="2025-01-01T00:01:00Z",
                    metadata={},
                ),
                ServiceInstanceInfo(
                    instance_id="instance-2",
                    status="ONLINE",
                    registered_at="2025-01-01T00:00:00Z",
                    last_heartbeat="2025-01-01T00:01:00Z",
                    metadata={},
                ),
            ],
            created_at="2025-01-01T00:00:00Z",
            metadata={},
        )

    @pytest.mark.asyncio
    async def test_transfer_resources_success(
        self,
        transfer_service: ResourceTransferService,
        mock_resource_registry: MagicMock,
        mock_service_registry: MagicMock,
        sample_resource: Resource,
        service_info: ServiceInfo,
    ) -> None:
        """Test successful resource transfer."""
        # Setup mocks
        mock_service_registry.get_service.return_value = service_info
        mock_resource_registry.get_resource_owner.return_value = "instance-1"
        mock_resource_registry.get_resource.return_value = sample_resource
        mock_resource_registry.release_resource.return_value = True

        # Perform transfer
        transferred, failed, transfer_id = await transfer_service.transfer_resources(
            service_name="test-service",
            resource_ids=["resource-123"],
            from_instance_id="instance-1",
            to_instance_id="instance-2",
            verify_ownership=True,
            reason="Load balancing",
        )

        # Verify results
        assert len(transferred) == 1
        assert "resource-123" in transferred
        assert len(failed) == 0
        assert transfer_id.startswith("transfer_")

        # Verify service lookup
        mock_service_registry.get_service.assert_called_once_with("test-service")

        # Verify resource operations
        mock_resource_registry.get_resource.assert_called_once_with("resource-123")
        mock_resource_registry.release_resource.assert_called_once_with(
            "resource-123", "instance-1"
        )
        mock_resource_registry.register_resource.assert_called_once()

    @pytest.mark.asyncio
    async def test_transfer_empty_resource_list(
        self,
        transfer_service: ResourceTransferService,
    ) -> None:
        """Test transfer with empty resource list."""
        with pytest.raises(ValidationError) as exc_info:
            await transfer_service.transfer_resources(
                service_name="test-service",
                resource_ids=[],
                from_instance_id="instance-1",
                to_instance_id="instance-2",
            )

        assert "Resource IDs list cannot be empty" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_transfer_same_source_and_target(
        self,
        transfer_service: ResourceTransferService,
    ) -> None:
        """Test transfer to same instance."""
        with pytest.raises(ValidationError) as exc_info:
            await transfer_service.transfer_resources(
                service_name="test-service",
                resource_ids=["resource-123"],
                from_instance_id="instance-1",
                to_instance_id="instance-1",
            )

        assert "Source and target instances cannot be the same" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_transfer_to_nonexistent_instance(
        self,
        transfer_service: ResourceTransferService,
        mock_service_registry: MagicMock,
    ) -> None:
        """Test transfer to non-existent instance."""
        # Service exists but target instance doesn't
        service_info = ServiceInfo(
            name="test-service",
            instances=[
                ServiceInstanceInfo(
                    instance_id="instance-1",
                    status="ONLINE",
                    registered_at="2025-01-01T00:00:00Z",
                    last_heartbeat="2025-01-01T00:01:00Z",
                    metadata={},
                ),
            ],
            created_at="2025-01-01T00:00:00Z",
            metadata={},
        )
        mock_service_registry.get_service.return_value = service_info

        with pytest.raises(NotFoundError) as exc_info:
            await transfer_service.transfer_resources(
                service_name="test-service",
                resource_ids=["resource-123"],
                from_instance_id="instance-1",
                to_instance_id="instance-2",
            )

        assert "instance-2" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_transfer_to_unhealthy_instance(
        self,
        transfer_service: ResourceTransferService,
        mock_service_registry: MagicMock,
    ) -> None:
        """Test transfer to unhealthy instance."""
        # Create service info with unhealthy target
        service_info = ServiceInfo(
            name="test-service",
            instances=[
                ServiceInstanceInfo(
                    instance_id="instance-1",
                    status="ONLINE",
                    registered_at="2025-01-01T00:00:00Z",
                    last_heartbeat="2025-01-01T00:01:00Z",
                    metadata={},
                ),
                ServiceInstanceInfo(
                    instance_id="instance-2",
                    status="OFFLINE",
                    registered_at="2025-01-01T00:00:00Z",
                    last_heartbeat="2025-01-01T00:00:00Z",
                    metadata={},
                ),
            ],
            created_at="2025-01-01T00:00:00Z",
            metadata={},
        )
        mock_service_registry.get_service.return_value = service_info

        with pytest.raises(ValidationError) as exc_info:
            await transfer_service.transfer_resources(
                service_name="test-service",
                resource_ids=["resource-123"],
                from_instance_id="instance-1",
                to_instance_id="instance-2",
            )

        assert "instance-2" in str(exc_info.value)
        assert "not healthy" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_transfer_with_ownership_verification_failure(
        self,
        transfer_service: ResourceTransferService,
        mock_resource_registry: MagicMock,
        mock_service_registry: MagicMock,
        service_info: ServiceInfo,
    ) -> None:
        """Test transfer with ownership verification failure."""
        # Setup mocks
        mock_service_registry.get_service.return_value = service_info
        mock_resource_registry.get_resource_owner.return_value = "instance-3"  # Different owner

        # Perform transfer
        transferred, failed, transfer_id = await transfer_service.transfer_resources(
            service_name="test-service",
            resource_ids=["resource-123"],
            from_instance_id="instance-1",
            to_instance_id="instance-2",
            verify_ownership=True,
        )

        # Verify results
        assert len(transferred) == 0
        assert len(failed) == 1
        assert "resource-123" in failed
        assert "Not owned by source instance" in failed["resource-123"]

    @pytest.mark.asyncio
    async def test_transfer_without_ownership_verification(
        self,
        transfer_service: ResourceTransferService,
        mock_resource_registry: MagicMock,
        mock_service_registry: MagicMock,
        sample_resource: Resource,
        service_info: ServiceInfo,
    ) -> None:
        """Test transfer without ownership verification."""
        # Setup mocks
        mock_service_registry.get_service.return_value = service_info
        mock_resource_registry.get_resource.return_value = sample_resource
        mock_resource_registry.release_resource.return_value = True

        # Perform transfer without verification
        transferred, failed, transfer_id = await transfer_service.transfer_resources(
            service_name="test-service",
            resource_ids=["resource-123"],
            from_instance_id="instance-1",
            to_instance_id="instance-2",
            verify_ownership=False,  # Skip ownership check
        )

        # Verify results
        assert len(transferred) == 1
        assert "resource-123" in transferred

        # Verify ownership was NOT checked
        mock_resource_registry.get_resource_owner.assert_not_called()

    @pytest.mark.asyncio
    async def test_transfer_multiple_resources(
        self,
        transfer_service: ResourceTransferService,
        mock_resource_registry: MagicMock,
        mock_service_registry: MagicMock,
        sample_resource: Resource,
        service_info: ServiceInfo,
    ) -> None:
        """Test transferring multiple resources."""
        resource_ids = ["res-1", "res-2", "res-3"]

        # Setup mocks
        mock_service_registry.get_service.return_value = service_info
        mock_resource_registry.get_resource_owner.side_effect = [
            "instance-1",  # res-1
            "instance-1",  # res-2
            "instance-1",  # res-3
        ]
        mock_resource_registry.get_resource.return_value = sample_resource
        mock_resource_registry.release_resource.return_value = True

        # Perform transfer
        transferred, failed, transfer_id = await transfer_service.transfer_resources(
            service_name="test-service",
            resource_ids=resource_ids,
            from_instance_id="instance-1",
            to_instance_id="instance-2",
            verify_ownership=True,
        )

        # Verify results
        assert len(transferred) == 3
        assert all(res_id in transferred for res_id in resource_ids)
        assert len(failed) == 0

        # Verify all resources were processed
        assert mock_resource_registry.get_resource.call_count == 3
        assert mock_resource_registry.release_resource.call_count == 3
        assert mock_resource_registry.register_resource.call_count == 3

    @pytest.mark.asyncio
    async def test_transfer_with_resource_not_found(
        self,
        transfer_service: ResourceTransferService,
        mock_resource_registry: MagicMock,
        mock_service_registry: MagicMock,
        service_info: ServiceInfo,
    ) -> None:
        """Test transfer when resource doesn't exist."""
        # Setup mocks
        mock_service_registry.get_service.return_value = service_info
        mock_resource_registry.get_resource_owner.side_effect = ResourceNotFoundError(
            "resource-123"
        )

        # Perform transfer
        transferred, failed, transfer_id = await transfer_service.transfer_resources(
            service_name="test-service",
            resource_ids=["resource-123"],
            from_instance_id="instance-1",
            to_instance_id="instance-2",
            verify_ownership=True,
        )

        # Verify results
        assert len(transferred) == 0
        assert len(failed) == 1
        assert "resource-123" in failed
        assert "Resource not found" in failed["resource-123"]

    @pytest.mark.asyncio
    async def test_transfer_with_release_failure(
        self,
        transfer_service: ResourceTransferService,
        mock_resource_registry: MagicMock,
        mock_service_registry: MagicMock,
        sample_resource: Resource,
        service_info: ServiceInfo,
    ) -> None:
        """Test transfer when release fails."""
        # Setup mocks
        mock_service_registry.get_service.return_value = service_info
        mock_resource_registry.get_resource_owner.return_value = "instance-1"
        mock_resource_registry.get_resource.return_value = sample_resource
        mock_resource_registry.release_resource.return_value = False  # Release fails

        # Perform transfer
        transferred, failed, transfer_id = await transfer_service.transfer_resources(
            service_name="test-service",
            resource_ids=["resource-123"],
            from_instance_id="instance-1",
            to_instance_id="instance-2",
            verify_ownership=True,
        )

        # Verify results
        assert len(transferred) == 0
        assert len(failed) == 1
        assert "resource-123" in failed
        assert "Transfer failed" in failed["resource-123"]

        # Verify register was not called after failed release
        mock_resource_registry.register_resource.assert_not_called()

    @pytest.mark.asyncio
    async def test_transfer_with_rollback_on_register_failure(
        self,
        transfer_service: ResourceTransferService,
        mock_resource_registry: MagicMock,
        mock_service_registry: MagicMock,
        sample_resource: Resource,
        service_info: ServiceInfo,
    ) -> None:
        """Test rollback when register fails after release."""
        # Setup mocks
        mock_service_registry.get_service.return_value = service_info
        mock_resource_registry.get_resource_owner.return_value = "instance-1"
        mock_resource_registry.get_resource.return_value = sample_resource
        mock_resource_registry.release_resource.return_value = True
        mock_resource_registry.register_resource.side_effect = [
            Exception("Register failed"),  # First call fails
            sample_resource,  # Rollback call succeeds
        ]

        # Perform transfer
        transferred, failed, transfer_id = await transfer_service.transfer_resources(
            service_name="test-service",
            resource_ids=["resource-123"],
            from_instance_id="instance-1",
            to_instance_id="instance-2",
            verify_ownership=True,
        )

        # Verify results
        assert len(transferred) == 0
        assert len(failed) == 1
        assert "resource-123" in failed

        # Verify rollback was attempted
        assert mock_resource_registry.register_resource.call_count == 2
        # Verify second call was rollback to original owner
        rollback_call = mock_resource_registry.register_resource.call_args_list[1]
        assert rollback_call.kwargs["owner_instance_id"] == "instance-1"
        assert rollback_call.kwargs["force"] is True

    @pytest.mark.asyncio
    async def test_get_transfer_history_empty(
        self,
        transfer_service: ResourceTransferService,
    ) -> None:
        """Test getting transfer history when empty."""
        history = transfer_service.get_transfer_history()
        assert history == []

    @pytest.mark.asyncio
    async def test_get_transfer_history_after_transfer(
        self,
        transfer_service: ResourceTransferService,
        mock_resource_registry: MagicMock,
        mock_service_registry: MagicMock,
        sample_resource: Resource,
        service_info: ServiceInfo,
    ) -> None:
        """Test getting transfer history after a transfer."""
        # Setup mocks
        mock_service_registry.get_service.return_value = service_info
        mock_resource_registry.get_resource_owner.return_value = "instance-1"
        mock_resource_registry.get_resource.return_value = sample_resource
        mock_resource_registry.release_resource.return_value = True

        # Perform transfer
        await transfer_service.transfer_resources(
            service_name="test-service",
            resource_ids=["resource-123"],
            from_instance_id="instance-1",
            to_instance_id="instance-2",
            reason="Test transfer",
        )

        # Get history
        history = transfer_service.get_transfer_history()
        assert len(history) == 1
        assert history[0].service_name == "test-service"
        assert history[0].from_instance_id == "instance-1"
        assert history[0].to_instance_id == "instance-2"
        assert history[0].reason == "Test transfer"
        assert "resource-123" in history[0].resource_ids

    @pytest.mark.asyncio
    async def test_get_transfer_history_with_filters(
        self,
        transfer_service: ResourceTransferService,
        mock_resource_registry: MagicMock,
        mock_service_registry: MagicMock,
        sample_resource: Resource,
        service_info: ServiceInfo,
    ) -> None:
        """Test getting filtered transfer history."""
        # Setup mocks
        mock_service_registry.get_service.return_value = service_info
        mock_resource_registry.get_resource_owner.return_value = "instance-1"
        mock_resource_registry.get_resource.return_value = sample_resource
        mock_resource_registry.release_resource.return_value = True

        # Perform multiple transfers
        await transfer_service.transfer_resources(
            service_name="test-service",
            resource_ids=["res-1"],
            from_instance_id="instance-1",
            to_instance_id="instance-2",
        )

        # For the second transfer, mock the service registry to return a different service
        other_service_info = ServiceInfo(
            name="other-service",
            instances=[
                ServiceInstanceInfo(
                    instance_id="instance-2",
                    status="ONLINE",
                    registered_at="2025-01-01T00:00:00Z",
                    last_heartbeat="2025-01-01T00:01:00Z",
                    metadata={},
                ),
                ServiceInstanceInfo(
                    instance_id="instance-3",
                    status="ONLINE",
                    registered_at="2025-01-01T00:00:00Z",
                    last_heartbeat="2025-01-01T00:01:00Z",
                    metadata={},
                ),
            ],
            created_at="2025-01-01T00:00:00Z",
            metadata={},
        )
        # Reset the mock to use side_effect for multiple calls
        mock_service_registry.get_service.reset_mock()
        mock_service_registry.get_service.side_effect = [other_service_info]

        await transfer_service.transfer_resources(
            service_name="other-service",
            resource_ids=["res-2"],
            from_instance_id="instance-2",
            to_instance_id="instance-3",
        )

        # Filter by service name
        history = transfer_service.get_transfer_history(service_name="test-service")
        assert len(history) == 1
        assert history[0].service_name == "test-service"

        # Filter by instance ID
        history = transfer_service.get_transfer_history(instance_id="instance-2")
        assert len(history) == 2  # instance-2 is involved in both transfers

    @pytest.mark.asyncio
    async def test_concurrent_transfers(
        self,
        transfer_service: ResourceTransferService,
        mock_resource_registry: MagicMock,
        mock_service_registry: MagicMock,
        sample_resource: Resource,
        service_info: ServiceInfo,
    ) -> None:
        """Test concurrent transfer operations are serialized."""
        # Setup mocks
        mock_service_registry.get_service.return_value = service_info
        mock_resource_registry.get_resource_owner.return_value = "instance-1"
        mock_resource_registry.get_resource.return_value = sample_resource
        mock_resource_registry.release_resource.return_value = True

        # Simulate delay in resource operations
        async def delayed_release(*args):
            await asyncio.sleep(0.1)
            return True

        mock_resource_registry.release_resource.side_effect = delayed_release

        # Launch concurrent transfers
        tasks = [
            transfer_service.transfer_resources(
                service_name="test-service",
                resource_ids=[f"res-{i}"],
                from_instance_id="instance-1",
                to_instance_id="instance-2",
            )
            for i in range(3)
        ]

        # Execute concurrently
        results = await asyncio.gather(*tasks)

        # Verify all completed successfully
        assert len(results) == 3
        for transferred, failed, _ in results:
            assert len(transferred) == 1
            assert len(failed) == 0
