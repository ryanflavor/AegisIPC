"""Unit tests for bulk resource management handler."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from ipc_router.application.models import (
    BulkResourceRegistrationRequest,
    BulkResourceRegistrationResponse,
    BulkResourceReleaseRequest,
    BulkResourceReleaseResponse,
    ResourceMetadata,
    ResourceRegistrationItem,
)
from ipc_router.domain.entities import Resource
from ipc_router.domain.exceptions import (
    ResourceConflictError,
    ResourceReleaseError,
    ValidationError,
)
from ipc_router.infrastructure.messaging.handlers import BulkResourceHandler


@pytest.fixture
def nats_client() -> AsyncMock:
    """Mock NATS client."""
    client = AsyncMock()
    client.subscribe = AsyncMock()
    client.unsubscribe = AsyncMock()
    client.publish = AsyncMock()
    return client


@pytest.fixture
def resource_service() -> AsyncMock:
    """Mock resource service."""
    service = AsyncMock()
    return service


@pytest.fixture
def handler(nats_client: AsyncMock, resource_service: AsyncMock) -> BulkResourceHandler:
    """Create bulk resource handler instance."""
    return BulkResourceHandler(
        nats_client=nats_client,
        resource_service=resource_service,
        max_concurrent_batches=3,
    )


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


@pytest.fixture
def sample_resources(sample_metadata: ResourceMetadata) -> list[ResourceRegistrationItem]:
    """Sample resource registration items."""
    return [
        ResourceRegistrationItem(
            resource_id=f"resource-{i}",
            metadata=sample_metadata,
            force=False,
        )
        for i in range(10)
    ]


class TestBulkResourceHandler:
    """Test bulk resource handler operations."""

    @pytest.mark.asyncio
    async def test_start_subscribes_to_subjects(
        self, handler: BulkResourceHandler, nats_client: AsyncMock
    ) -> None:
        """Test handler subscribes to correct subjects on start."""
        await handler.start()

        # Verify subscriptions
        calls = nats_client.subscribe.call_args_list
        assert len(calls) == 2

        # Check bulk registration subscription
        assert calls[0][1]["subject"] == "ipc.resource.bulk_register"
        assert calls[0][1]["queue"] == "bulk-resource-registry"

        # Check bulk release subscription
        assert calls[1][1]["subject"] == "ipc.resource.bulk_release"
        assert calls[1][1]["queue"] == "bulk-resource-registry"

    @pytest.mark.asyncio
    async def test_stop_unsubscribes_from_subjects(
        self, handler: BulkResourceHandler, nats_client: AsyncMock
    ) -> None:
        """Test handler unsubscribes on stop."""
        await handler.stop()

        # Verify unsubscriptions
        calls = nats_client.unsubscribe.call_args_list
        assert len(calls) == 2
        assert calls[0][0][0] == "ipc.resource.bulk_register"
        assert calls[1][0][0] == "ipc.resource.bulk_release"

    @pytest.mark.asyncio
    async def test_bulk_registration_success(
        self,
        handler: BulkResourceHandler,
        nats_client: AsyncMock,
        resource_service: AsyncMock,
        sample_resources: list[ResourceRegistrationItem],
    ) -> None:
        """Test successful bulk resource registration."""
        # Mock resource service to return successful registrations
        resource_service.register_resource.side_effect = [
            Resource(
                resource_id=item.resource_id,
                owner_instance_id="test-instance",
                service_name="test-service",
                registered_at=datetime.now(UTC),
                metadata=item.metadata,
            )
            for item in sample_resources
        ]

        # Create request
        request = BulkResourceRegistrationRequest(
            service_name="test-service",
            instance_id="test-instance",
            resources=sample_resources,
            batch_size=5,
            continue_on_error=False,
            trace_id="trace-123",
        )

        # Process request
        response = await handler._process_bulk_registration(request)

        # Verify response
        assert isinstance(response, BulkResourceRegistrationResponse)
        assert response.total_requested == 10
        assert response.total_registered == 10
        assert len(response.registered) == 10
        assert len(response.failed) == 0
        assert len(response.batch_results) == 2  # 10 resources / 5 batch_size

        # Verify batch results
        for batch_result in response.batch_results:
            assert batch_result.success_count == 5
            assert batch_result.failure_count == 0
            assert batch_result.duration_ms > 0

    @pytest.mark.asyncio
    async def test_bulk_registration_with_conflicts(
        self,
        handler: BulkResourceHandler,
        resource_service: AsyncMock,
        sample_resources: list[ResourceRegistrationItem],
    ) -> None:
        """Test bulk registration with resource conflicts."""
        # Mock resource service to simulate conflicts on some resources
        side_effects = []
        for i, item in enumerate(sample_resources):
            if i % 3 == 0:  # Every 3rd resource conflicts
                side_effects.append(
                    ResourceConflictError(
                        resource_id=item.resource_id,
                        current_owner="other-instance",
                    )
                )
            else:
                side_effects.append(
                    Resource(
                        resource_id=item.resource_id,
                        owner_instance_id="test-instance",
                        service_name="test-service",
                        registered_at=datetime.now(UTC),
                        metadata=item.metadata,
                    )
                )

        resource_service.register_resource.side_effect = side_effects

        # Create request with continue_on_error=True
        request = BulkResourceRegistrationRequest(
            service_name="test-service",
            instance_id="test-instance",
            resources=sample_resources,
            batch_size=5,
            continue_on_error=True,
            trace_id="trace-123",
        )

        # Process request
        response = await handler._process_bulk_registration(request)

        # Verify response
        assert response.total_requested == 10
        assert response.total_registered == 6  # 10 - 4 conflicts
        assert len(response.failed) == 4  # 4 conflicts

        # Verify failures
        for failure in response.failed:
            assert failure.error_code == "RESOURCE_CONFLICT"
            assert failure.current_owner == "other-instance"

    @pytest.mark.asyncio
    async def test_bulk_registration_stops_on_error(
        self,
        handler: BulkResourceHandler,
        resource_service: AsyncMock,
        sample_resources: list[ResourceRegistrationItem],
    ) -> None:
        """Test bulk registration stops on first error when continue_on_error=False."""
        # Mock resource service to fail on third resource
        side_effects = []
        for i, item in enumerate(sample_resources):
            if i == 2:
                side_effects.append(ValidationError(f"Invalid resource {item.resource_id}"))
            else:
                side_effects.append(
                    Resource(
                        resource_id=item.resource_id,
                        owner_instance_id="test-instance",
                        service_name="test-service",
                        registered_at=datetime.now(UTC),
                        metadata=item.metadata,
                    )
                )

        resource_service.register_resource.side_effect = side_effects

        # Create request with continue_on_error=False
        request = BulkResourceRegistrationRequest(
            service_name="test-service",
            instance_id="test-instance",
            resources=sample_resources,
            batch_size=5,
            continue_on_error=False,
            trace_id="trace-123",
        )

        # Process request
        response = await handler._process_bulk_registration(request)

        # Verify response - should stop at first batch due to error
        assert response.total_registered == 2  # Only first 2 resources before error
        assert len(response.failed) == 1  # One failure
        assert response.failed[0].error_code == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_bulk_release_success(
        self, handler: BulkResourceHandler, resource_service: AsyncMock
    ) -> None:
        """Test successful bulk resource release."""
        # Mock resource service for successful releases
        resource_service.release_resource.return_value = True

        # Create request
        resource_ids = [f"resource-{i}" for i in range(10)]
        request = BulkResourceReleaseRequest(
            service_name="test-service",
            instance_id="test-instance",
            resource_ids=resource_ids,
            batch_size=5,
            continue_on_error=False,
            transactional=False,
            trace_id="trace-123",
        )

        # Process request
        response = await handler._process_bulk_release(request)

        # Verify response
        assert isinstance(response, BulkResourceReleaseResponse)
        assert response.total_requested == 10
        assert response.total_released == 10
        assert len(response.released) == 10
        assert len(response.failed) == 0
        assert not response.rollback_performed

        # Verify all resources were released
        assert resource_service.release_resource.call_count == 10

    @pytest.mark.asyncio
    async def test_bulk_release_with_errors(
        self, handler: BulkResourceHandler, resource_service: AsyncMock
    ) -> None:
        """Test bulk release with some errors."""
        # Mock resource service to fail on some releases
        side_effects = []
        for i in range(10):
            if i % 4 == 0:  # Every 4th resource fails
                side_effects.append(ResourceReleaseError(f"Not owner of resource-{i}"))
            else:
                side_effects.append(True)

        resource_service.release_resource.side_effect = side_effects

        # Create request with continue_on_error=True
        resource_ids = [f"resource-{i}" for i in range(10)]
        request = BulkResourceReleaseRequest(
            service_name="test-service",
            instance_id="test-instance",
            resource_ids=resource_ids,
            batch_size=5,
            continue_on_error=True,
            transactional=False,
            trace_id="trace-123",
        )

        # Process request
        response = await handler._process_bulk_release(request)

        # Verify response
        assert response.total_requested == 10
        assert response.total_released == 7  # 10 - 3 failures
        assert len(response.failed) == 3

        # Verify failures
        for failure in response.failed:
            assert failure.error_code == "NOT_OWNER"

    @pytest.mark.asyncio
    async def test_bulk_release_transactional_rollback(
        self, handler: BulkResourceHandler, resource_service: AsyncMock
    ) -> None:
        """Test transactional bulk release with rollback on failure."""
        # Mock resource service to succeed on first batch, fail on second
        release_count = 0

        async def mock_release(resource_id: str, instance_id: str) -> bool:
            nonlocal release_count
            release_count += 1
            if release_count > 5:  # Fail after first batch
                raise ResourceReleaseError(f"Not owner of {resource_id}")
            return True

        resource_service.release_resource.side_effect = mock_release

        # Mock re-registration for rollback
        resource_service.register_resource.return_value = MagicMock()

        # Mock get_resource for metadata preservation
        resource_service._registry = MagicMock()
        resource_service._registry.get_resource = AsyncMock(return_value=None)

        # Create transactional request
        resource_ids = [f"resource-{i}" for i in range(10)]
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

        # Verify rollback occurred
        assert response.rollback_performed
        assert response.total_released == 0  # All rolled back
        assert len(response.failed) == 1  # One failure triggered rollback

        # Verify rollback calls
        assert resource_service.register_resource.call_count == 5  # Re-register first batch

    @pytest.mark.asyncio
    async def test_concurrent_batch_processing(
        self,
        handler: BulkResourceHandler,
        resource_service: AsyncMock,
        sample_metadata: ResourceMetadata,
    ) -> None:
        """Test concurrent batch processing respects semaphore limit."""
        # Create a slow mock to test concurrency
        processing_times = []

        async def slow_register(
            service_name: str,
            instance_id: str,
            resource_id: str,
            metadata: ResourceMetadata,
            force: bool,
        ) -> Resource:
            start_time = asyncio.get_event_loop().time()
            await asyncio.sleep(0.1)  # Simulate slow operation
            processing_times.append((start_time, asyncio.get_event_loop().time()))
            return Resource(
                resource_id=resource_id,
                owner_instance_id=instance_id,
                service_name=service_name,
                registered_at=datetime.now(UTC),
                metadata=metadata,
            )

        resource_service.register_resource.side_effect = slow_register

        # Create request with many resources to test batching
        resources = [
            ResourceRegistrationItem(
                resource_id=f"resource-{i}",
                metadata=ResourceMetadata(
                    resource_type="test",
                    version=1,
                    created_by="test",
                    last_modified=datetime.now(UTC),
                ),
                force=False,
            )
            for i in range(30)
        ]

        request = BulkResourceRegistrationRequest(
            service_name="test-service",
            instance_id="test-instance",
            resources=resources,
            batch_size=10,  # 3 batches total
            continue_on_error=False,
            trace_id="trace-123",
        )

        # Process request
        response = await handler._process_bulk_registration(request)

        # Verify all processed
        assert response.total_registered == 30

        # Verify semaphore limited concurrent batches
        # With max_concurrent_batches=3, all batches should run concurrently
        assert len(response.batch_results) == 3

    @pytest.mark.asyncio
    async def test_handle_bulk_registration_request(
        self,
        handler: BulkResourceHandler,
        nats_client: AsyncMock,
        resource_service: AsyncMock,
        sample_resources: list[ResourceRegistrationItem],
    ) -> None:
        """Test handling incoming bulk registration request via NATS."""
        # Mock resource service
        resource_service.register_resource.return_value = Resource(
            resource_id="test-resource",
            owner_instance_id="test-instance",
            service_name="test-service",
            registered_at=datetime.now(UTC),
            metadata=sample_metadata,
        )

        # Create request data
        request_data = {
            "service_name": "test-service",
            "instance_id": "test-instance",
            "resources": [r.model_dump() for r in sample_resources],
            "batch_size": 5,
            "continue_on_error": False,
            "trace_id": "trace-123",
        }

        # Process request
        await handler._handle_bulk_registration(request_data, "reply.subject")

        # Verify response was published
        nats_client.publish.assert_called_once()
        call_args = nats_client.publish.call_args
        assert call_args[1]["subject"] == "reply.subject"

        # Verify response data
        response_data = call_args[1]["data"]
        assert response_data["total_requested"] == 10
        assert response_data["trace_id"] == "trace-123"

    @pytest.mark.asyncio
    async def test_handle_bulk_registration_validation_error(
        self, handler: BulkResourceHandler, nats_client: AsyncMock
    ) -> None:
        """Test handling invalid bulk registration request."""
        # Invalid request (missing required field)
        request_data = {
            "instance_id": "test-instance",
            # Missing service_name
            "resources": [],
            "trace_id": "trace-123",
        }

        # Process request
        await handler._handle_bulk_registration(request_data, "reply.subject")

        # Verify error response was sent
        nats_client.publish.assert_called_once()
        call_args = nats_client.publish.call_args
        response_data = call_args[1]["data"]

        assert response_data["success"] is False
        assert response_data["error"]["code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_handle_bulk_release_request(
        self, handler: BulkResourceHandler, nats_client: AsyncMock, resource_service: AsyncMock
    ) -> None:
        """Test handling incoming bulk release request via NATS."""
        # Mock resource service
        resource_service.release_resource.return_value = True

        # Create request data
        request_data = {
            "service_name": "test-service",
            "instance_id": "test-instance",
            "resource_ids": [f"resource-{i}" for i in range(10)],
            "batch_size": 5,
            "continue_on_error": False,
            "transactional": True,
            "trace_id": "trace-123",
        }

        # Process request
        await handler._handle_bulk_release(request_data, "reply.subject")

        # Verify response was published
        nats_client.publish.assert_called_once()
        call_args = nats_client.publish.call_args
        assert call_args[1]["subject"] == "reply.subject"

        # Verify response data
        response_data = call_args[1]["data"]
        assert response_data["total_requested"] == 10
        assert response_data["total_released"] == 10
        assert response_data["trace_id"] == "trace-123"

    @pytest.mark.asyncio
    async def test_batch_result_timing(
        self,
        handler: BulkResourceHandler,
        resource_service: AsyncMock,
        sample_resources: list[ResourceRegistrationItem],
        sample_metadata: ResourceMetadata,
    ) -> None:
        """Test batch result includes accurate timing information."""
        # Mock instant registration
        resource_service.register_resource.return_value = Resource(
            resource_id="test-resource",
            owner_instance_id="test-instance",
            service_name="test-service",
            registered_at=datetime.now(UTC),
            metadata=sample_metadata,
        )

        # Create request with single batch
        request = BulkResourceRegistrationRequest(
            service_name="test-service",
            instance_id="test-instance",
            resources=sample_resources[:5],
            batch_size=10,  # Single batch
            continue_on_error=False,
            trace_id="trace-123",
        )

        # Process request
        response = await handler._process_bulk_registration(request)

        # Verify timing
        assert len(response.batch_results) == 1
        batch_result = response.batch_results[0]
        assert batch_result.duration_ms >= 0
        assert batch_result.batch_number == 1

    @pytest.mark.asyncio
    async def test_error_response_handling(
        self, handler: BulkResourceHandler, nats_client: AsyncMock
    ) -> None:
        """Test error response handling."""
        # Test sending error response
        await handler._send_error_response(
            reply_subject="reply.subject",
            error_code="TEST_ERROR",
            message="Test error message",
            details={"foo": "bar"},
        )

        # Verify error response structure
        nats_client.publish.assert_called_once()
        call_args = nats_client.publish.call_args
        response_data = call_args[1]["data"]

        assert response_data["success"] is False
        assert response_data["error"]["code"] == "TEST_ERROR"
        assert response_data["error"]["message"] == "Test error message"
        assert response_data["error"]["details"]["foo"] == "bar"

    @pytest.mark.parametrize(
        "batch_size,total_resources,expected_batches",
        [
            (10, 25, 3),  # 3 batches: 10, 10, 5
            (50, 100, 2),  # 2 batches: 50, 50
            (100, 50, 1),  # 1 batch: 50
            (1, 5, 5),  # 5 batches: 1 each
        ],
    )
    @pytest.mark.asyncio
    async def test_batch_sizing(
        self,
        handler: BulkResourceHandler,
        resource_service: AsyncMock,
        sample_metadata: ResourceMetadata,
        batch_size: int,
        total_resources: int,
        expected_batches: int,
    ) -> None:
        """Test correct batch sizing for various configurations."""
        # Mock resource service
        resource_service.register_resource.return_value = Resource(
            resource_id="test-resource",
            owner_instance_id="test-instance",
            service_name="test-service",
            registered_at=datetime.now(UTC),
            metadata=sample_metadata,
        )

        # Create resources
        resources = [
            ResourceRegistrationItem(
                resource_id=f"resource-{i}",
                metadata=ResourceMetadata(
                    resource_type="test",
                    version=1,
                    created_by="test",
                    last_modified=datetime.now(UTC),
                ),
                force=False,
            )
            for i in range(total_resources)
        ]

        request = BulkResourceRegistrationRequest(
            service_name="test-service",
            instance_id="test-instance",
            resources=resources,
            batch_size=batch_size,
            continue_on_error=False,
            trace_id="trace-123",
        )

        # Process request
        response = await handler._process_bulk_registration(request)

        # Verify batch count
        assert len(response.batch_results) == expected_batches
        assert response.total_registered == total_resources
