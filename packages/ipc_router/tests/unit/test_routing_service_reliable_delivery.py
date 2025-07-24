"""Unit tests for RoutingService with reliable delivery features."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from ipc_router.application.models.routing_models import RouteRequest
from ipc_router.application.services.acknowledgment_service import AcknowledgmentService
from ipc_router.application.services.message_store_service import MessageStoreService
from ipc_router.application.services.routing_service import RoutingService
from ipc_router.domain.entities.message import Message, MessageState
from ipc_router.domain.entities.service import ServiceInstance
from ipc_router.domain.enums import ServiceStatus


@pytest.mark.asyncio
class TestRoutingServiceReliableDelivery:
    """Test cases for RoutingService with reliable delivery features."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.mock_registry = AsyncMock()
        self.mock_message_store = AsyncMock(spec=MessageStoreService)
        self.mock_acknowledgment_service = AsyncMock(spec=AcknowledgmentService)
        from ipc_router.domain.interfaces.load_balancer import LoadBalancer

        self.mock_load_balancer = Mock(spec=LoadBalancer)
        self.routing_service = RoutingService(
            self.mock_registry,
            self.mock_message_store,
            self.mock_acknowledgment_service,
            self.mock_load_balancer,
        )

    async def test_initialization_with_reliable_delivery(self) -> None:
        """Test initialization with reliable delivery services."""
        assert self.routing_service._registry is self.mock_registry
        assert self.routing_service._message_store is self.mock_message_store
        assert self.routing_service._acknowledgment_service is self.mock_acknowledgment_service
        assert self.routing_service._load_balancer is self.mock_load_balancer

    async def test_route_request_with_message_id_new_message(self) -> None:
        """Test routing a new request with message_id."""
        # Setup
        message_id = uuid4()
        instance = ServiceInstance(
            instance_id="inst-1",
            service_name="test-service",
            status=ServiceStatus.ONLINE,
            registered_at=datetime.now(UTC),
            last_heartbeat=datetime.now(UTC),
        )

        self.mock_message_store.get_message.return_value = None
        self.mock_registry.get_healthy_instances.return_value = [instance]
        self.mock_load_balancer.select_instance.return_value = instance

        # Create request with message_id
        request = RouteRequest(
            service_name="test-service",
            method="test_method",
            params={"key": "value"},
            trace_id="trace-123",
            message_id=message_id,
        )

        # Execute
        response = await self.routing_service.route_request(request)

        # Verify
        assert response.success is True
        assert response.message_id == message_id
        assert response.instance_id == "inst-1"

        # Verify message was stored
        self.mock_message_store.get_message.assert_called_with(str(message_id))
        self.mock_message_store.store_message.assert_called_once()
        stored_message = self.mock_message_store.store_message.call_args[0][0]
        assert stored_message.message_id == str(message_id)
        assert stored_message.service_name == "test-service"
        assert stored_message.method == "test_method"
        assert stored_message.params == {"key": "value"}

    async def test_route_request_with_duplicate_acknowledged_message(self) -> None:
        """Test routing a duplicate message that was already acknowledged."""
        # Setup
        message_id = uuid4()
        existing_message = Message(
            message_id=str(message_id),
            service_name="test-service",
            method="test_method",
            params={},
            trace_id="trace-123",
            state=MessageState.ACKNOWLEDGED,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            ack_deadline=datetime.now(UTC),
        )

        # Mock that get_message returns the existing message
        self.mock_message_store.get_message.return_value = existing_message

        # Create duplicate request
        request = RouteRequest(
            service_name="test-service",
            method="test_method",
            trace_id="trace-456",
            message_id=message_id,
        )

        # Execute
        response = await self.routing_service.route_request(request)

        # Verify idempotent response
        assert response.success is True
        assert response.message_id == message_id
        assert response.error is not None
        assert response.error["type"] == "DuplicateMessage"
        assert response.error["code"] == 200

        # Verify no routing occurred
        self.mock_registry.get_healthy_instances.assert_not_called()
        self.mock_load_balancer.select_instance.assert_not_called()

    async def test_route_request_without_message_id(self) -> None:
        """Test routing without message_id (backward compatibility)."""
        # Setup
        instance = ServiceInstance(
            instance_id="inst-1",
            service_name="test-service",
            status=ServiceStatus.ONLINE,
            registered_at=datetime.now(UTC),
            last_heartbeat=datetime.now(UTC),
        )

        self.mock_registry.get_healthy_instances.return_value = [instance]
        self.mock_load_balancer.select_instance.return_value = instance

        # Create request without message_id
        request = RouteRequest(
            service_name="test-service",
            method="test_method",
            trace_id="trace-123",
        )

        # Execute
        response = await self.routing_service.route_request(request)

        # Verify
        assert response.success is True
        assert response.message_id is None
        assert response.instance_id == "inst-1"

        # Verify no message store interaction
        self.mock_message_store.get_message.assert_not_called()
        self.mock_message_store.store_message.assert_not_called()

    async def test_acknowledge_message_success(self) -> None:
        """Test successful message acknowledgment."""
        # Setup
        message_id = uuid4()
        message = Message(
            message_id=str(message_id),
            service_name="test-service",
            method="test_method",
            params={},
            trace_id="trace-123",
            state=MessageState.PENDING,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            ack_deadline=datetime.now(UTC),
        )

        self.mock_message_store.get_message.return_value = message
        self.mock_acknowledgment_service.send_ack.return_value = None
        self.mock_message_store.update_message_state.return_value = None

        # Execute
        result = await self.routing_service.acknowledge_message(message_id)

        # Verify
        assert result is True
        self.mock_message_store.get_message.assert_called_once_with(str(message_id))
        self.mock_acknowledgment_service.send_ack.assert_called_once_with(
            message_id=str(message_id),
            service_name="test-service",
            instance_id="routing-service",
            success=True,
            processing_time_ms=0.0,
            trace_id="trace-123",
        )
        self.mock_message_store.update_message_state.assert_called_once_with(
            str(message_id), MessageState.ACKNOWLEDGED.value
        )

    async def test_acknowledge_message_not_found(self) -> None:
        """Test acknowledging a non-existent message."""
        # Setup
        message_id = uuid4()
        self.mock_message_store.get_message.return_value = None

        # Execute
        result = await self.routing_service.acknowledge_message(message_id)

        # Verify
        assert result is False
        self.mock_message_store.get_message.assert_called_once_with(str(message_id))
        self.mock_acknowledgment_service.send_ack.assert_not_called()

    async def test_acknowledge_message_without_reliable_delivery(self) -> None:
        """Test acknowledgment when reliable delivery is not configured."""
        # Setup service without reliable delivery
        routing_service = RoutingService(self.mock_registry)
        message_id = uuid4()

        # Execute
        result = await routing_service.acknowledge_message(message_id)

        # Verify
        assert result is False

    async def test_acknowledge_message_error_handling(self) -> None:
        """Test error handling during acknowledgment."""
        # Setup
        message_id = uuid4()
        message = Message(
            message_id=str(message_id),
            service_name="test-service",
            method="test_method",
            params={},
            trace_id="trace-123",
            state=MessageState.PENDING,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            ack_deadline=datetime.now(UTC),
        )

        self.mock_message_store.get_message.return_value = message
        self.mock_acknowledgment_service.send_ack.side_effect = Exception("Acknowledgment failed")

        # Execute
        result = await self.routing_service.acknowledge_message(message_id)

        # Verify
        assert result is False

    async def test_get_pending_messages_with_service_filter(self) -> None:
        """Test getting pending messages for a specific service."""
        # Setup
        messages = [
            Message(
                message_id=str(uuid4()),
                service_name="service-1",
                method="method1",
                params={},
                trace_id="trace-1",
                state=MessageState.PENDING,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                ack_deadline=datetime.now(UTC),
            ),
            Message(
                message_id=str(uuid4()),
                service_name="service-2",
                method="method2",
                params={},
                trace_id="trace-2",
                state=MessageState.PENDING,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                ack_deadline=datetime.now(UTC),
            ),
            Message(
                message_id=str(uuid4()),
                service_name="service-1",
                method="method3",
                params={},
                trace_id="trace-3",
                state=MessageState.PENDING,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                ack_deadline=datetime.now(UTC),
            ),
        ]

        service_1_messages = [msg for msg in messages if msg.service_name == "service-1"]
        self.mock_message_store.get_pending_messages_for_retry.return_value = service_1_messages

        # Execute
        result = await self.routing_service.get_pending_messages("service-1")

        # Verify
        assert len(result) == 2
        assert all(msg.service_name == "service-1" for msg in result)
        self.mock_message_store.get_pending_messages_for_retry.assert_called_once_with("service-1")

    async def test_get_pending_messages_without_filter(self) -> None:
        """Test getting all pending messages."""
        # Setup
        messages = [
            Message(
                message_id=str(uuid4()),
                service_name="service-1",
                method="method1",
                params={},
                trace_id="trace-1",
                state=MessageState.PENDING,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                ack_deadline=datetime.now(UTC),
            ),
            Message(
                message_id=str(uuid4()),
                service_name="service-2",
                method="method2",
                params={},
                trace_id="trace-2",
                state=MessageState.PENDING,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                ack_deadline=datetime.now(UTC),
            ),
        ]

        self.mock_message_store.get_pending_messages_for_retry.return_value = messages

        # Execute
        result = await self.routing_service.get_pending_messages()

        # Verify
        assert len(result) == 2
        assert result == messages
        self.mock_message_store.get_pending_messages_for_retry.assert_called_once_with(None)

    async def test_get_pending_messages_without_message_store(self) -> None:
        """Test getting pending messages when message store is not configured."""
        # Setup service without message store
        routing_service = RoutingService(self.mock_registry)

        # Execute
        result = await routing_service.get_pending_messages()

        # Verify
        assert result == []

    async def test_get_pending_messages_error_handling(self) -> None:
        """Test error handling when getting pending messages."""
        # Setup
        self.mock_message_store.get_pending_messages_for_retry.side_effect = Exception(
            "Database error"
        )

        # Execute
        result = await self.routing_service.get_pending_messages()

        # Verify
        assert result == []

    async def test_route_request_with_pending_duplicate_message(self) -> None:
        """Test routing a duplicate message that is still pending."""
        # Setup
        message_id = uuid4()
        existing_message = Message(
            message_id=str(message_id),
            service_name="test-service",
            method="test_method",
            params={},
            trace_id="trace-123",
            state=MessageState.PENDING,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            ack_deadline=datetime.now(UTC),
        )
        instance = ServiceInstance(
            instance_id="inst-1",
            service_name="test-service",
            status=ServiceStatus.ONLINE,
            registered_at=datetime.now(UTC),
            last_heartbeat=datetime.now(UTC),
        )

        # Mock that get_message returns the existing message
        self.mock_message_store.get_message.return_value = existing_message
        self.mock_registry.get_healthy_instances.return_value = [instance]
        self.mock_load_balancer.select_instance.return_value = instance

        # Create duplicate request
        request = RouteRequest(
            service_name="test-service",
            method="test_method",
            trace_id="trace-456",
            message_id=message_id,
        )

        # Execute
        response = await self.routing_service.route_request(request)

        # Verify normal routing occurred (retrying pending message)
        assert response.success is True
        assert response.message_id == message_id
        assert response.instance_id == "inst-1"
        assert response.error is None

        # Verify routing was performed
        self.mock_registry.get_healthy_instances.assert_called_once()
        self.mock_load_balancer.select_instance.assert_called_once()
