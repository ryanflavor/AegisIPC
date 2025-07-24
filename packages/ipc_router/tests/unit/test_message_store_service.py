"""Unit tests for MessageStoreService."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from ipc_router.application.services import MessageStoreService
from ipc_router.domain.entities import Message, MessageState
from ipc_router.domain.exceptions import MessageStorageError, NotFoundError


class TestMessageStoreService:
    """Test cases for MessageStoreService."""

    @pytest.fixture
    def service(self) -> MessageStoreService:
        """Create a MessageStoreService instance."""
        return MessageStoreService(
            default_ttl=3600,
            cleanup_interval=300,
            max_messages=100,
        )

    @pytest.fixture
    def sample_message(self) -> Message:
        """Create a sample message."""
        now = datetime.now(UTC)
        return Message(
            message_id="msg_test_001",
            service_name="test-service",
            method="test_method",
            params={"key": "value"},
            state=MessageState.PENDING,
            created_at=now,
            updated_at=now,
            ack_deadline=now + timedelta(seconds=30),
            trace_id="trace_test_001",
        )

    @pytest.mark.asyncio
    async def test_store_message_success(
        self, service: MessageStoreService, sample_message: Message
    ) -> None:
        """Test successful message storage."""
        await service.store_message(sample_message)

        # Verify message was stored
        stored_message = await service.get_message(sample_message.message_id)
        assert stored_message is not None
        assert stored_message.message_id == sample_message.message_id
        assert stored_message.service_name == sample_message.service_name

    @pytest.mark.asyncio
    async def test_store_message_with_eviction(self, service: MessageStoreService) -> None:
        """Test message storage with eviction when at capacity."""
        service.max_messages = 10

        # Fill up the store
        base_time = datetime.now(UTC)
        messages = []
        for i in range(10):
            msg = Message(
                message_id=f"msg_{i:03d}",
                service_name="test-service",
                method="test_method",
                params={},
                state=MessageState.PENDING,
                created_at=base_time + timedelta(seconds=i),
                updated_at=base_time + timedelta(seconds=i),
                ack_deadline=base_time + timedelta(minutes=5),
                trace_id=f"trace_{i:03d}",
            )
            messages.append(msg)
            await service.store_message(msg)

        # Store one more message to trigger eviction
        new_message = Message(
            message_id="msg_new",
            service_name="test-service",
            method="test_method",
            params={},
            state=MessageState.PENDING,
            created_at=base_time + timedelta(minutes=1),
            updated_at=base_time + timedelta(minutes=1),
            ack_deadline=base_time + timedelta(minutes=5),
            trace_id="trace_new",
        )
        await service.store_message(new_message)

        # Verify oldest message was evicted
        assert await service.get_message("msg_000") is None
        assert await service.get_message("msg_new") is not None

    @pytest.mark.asyncio
    async def test_store_message_error_handling(self, service: MessageStoreService) -> None:
        """Test error handling during message storage."""
        message = Message(
            message_id="msg_error",
            service_name="test-service",
            method="test_method",
            params={},
            state=MessageState.PENDING,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            ack_deadline=datetime.now(UTC) + timedelta(minutes=1),
            trace_id="trace_error",
        )

        # Simulate an error by making max_messages negative which will cause an issue
        service.max_messages = -1
        original_evict = service._evict_oldest_messages

        async def mock_evict() -> None:
            raise Exception("Storage error")

        service._evict_oldest_messages = mock_evict

        try:
            with pytest.raises(MessageStorageError) as exc_info:
                await service.store_message(message)

            assert exc_info.value.details["operation"] == "store"
            assert exc_info.value.details["message_id"] == "msg_error"
            assert "Storage error" in exc_info.value.details["reason"]
        finally:
            service._evict_oldest_messages = original_evict

    @pytest.mark.asyncio
    async def test_get_message_exists(
        self, service: MessageStoreService, sample_message: Message
    ) -> None:
        """Test retrieving an existing message."""
        await service.store_message(sample_message)

        retrieved = await service.get_message(sample_message.message_id)
        assert retrieved is not None
        assert retrieved.message_id == sample_message.message_id

    @pytest.mark.asyncio
    async def test_get_message_not_exists(self, service: MessageStoreService) -> None:
        """Test retrieving a non-existent message."""
        retrieved = await service.get_message("non_existent_id")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_is_duplicate_true(
        self, service: MessageStoreService, sample_message: Message
    ) -> None:
        """Test duplicate detection for existing message."""
        await service.store_message(sample_message)

        is_dup = await service.is_duplicate(sample_message.message_id)
        assert is_dup is True

    @pytest.mark.asyncio
    async def test_is_duplicate_false(self, service: MessageStoreService) -> None:
        """Test duplicate detection for non-existent message."""
        is_dup = await service.is_duplicate("non_existent_id")
        assert is_dup is False

    @pytest.mark.asyncio
    async def test_update_message_state_success(
        self, service: MessageStoreService, sample_message: Message
    ) -> None:
        """Test successful message state update."""
        await service.store_message(sample_message)
        original_updated_at = sample_message.updated_at

        # Add small delay to ensure timestamp changes
        await asyncio.sleep(0.001)

        # Update state with response
        response_data = {"result": "success", "data": [1, 2, 3]}
        await service.update_message_state(
            sample_message.message_id,
            MessageState.ACKNOWLEDGED.value,
            response=response_data,
        )

        # Verify update
        updated = await service.get_message(sample_message.message_id)
        assert updated is not None
        assert updated.state == MessageState.ACKNOWLEDGED
        assert updated.response == response_data
        assert updated.updated_at > original_updated_at

    @pytest.mark.asyncio
    async def test_update_message_state_with_error(
        self, service: MessageStoreService, sample_message: Message
    ) -> None:
        """Test message state update with error."""
        await service.store_message(sample_message)

        # Update state with error
        await service.update_message_state(
            sample_message.message_id,
            MessageState.FAILED.value,
            error="Processing failed",
        )

        # Verify update
        updated = await service.get_message(sample_message.message_id)
        assert updated is not None
        assert updated.state == MessageState.FAILED
        assert updated.last_error == "Processing failed"

    @pytest.mark.asyncio
    async def test_update_message_state_not_found(self, service: MessageStoreService) -> None:
        """Test updating non-existent message."""
        with pytest.raises(NotFoundError) as exc_info:
            await service.update_message_state(
                "non_existent_id",
                MessageState.ACKNOWLEDGED.value,
            )

        assert exc_info.value.details["resource_type"] == "Message"
        assert exc_info.value.details["resource_id"] == "non_existent_id"

    @pytest.mark.asyncio
    async def test_get_expired_messages(self, service: MessageStoreService) -> None:
        """Test retrieving expired messages."""
        now = datetime.now(UTC)

        # Create mix of expired and active messages
        expired_msg = Message(
            message_id="msg_expired",
            service_name="test-service",
            method="test_method",
            params={},
            state=MessageState.PENDING,
            created_at=now - timedelta(hours=2),
            updated_at=now - timedelta(hours=2),
            ack_deadline=now - timedelta(hours=1),  # Expired
            trace_id="trace_expired",
        )

        active_msg = Message(
            message_id="msg_active",
            service_name="test-service",
            method="test_method",
            params={},
            state=MessageState.PENDING,
            created_at=now,
            updated_at=now,
            ack_deadline=now + timedelta(hours=1),  # Not expired
            trace_id="trace_active",
        )

        await service.store_message(expired_msg)
        await service.store_message(active_msg)

        # Get expired messages
        expired_list = await service.get_expired_messages()

        assert len(expired_list) == 1
        assert expired_list[0].message_id == "msg_expired"

    @pytest.mark.asyncio
    async def test_get_expired_messages_with_limit(self, service: MessageStoreService) -> None:
        """Test retrieving expired messages with limit."""
        now = datetime.now(UTC)

        # Create multiple expired messages
        for i in range(5):
            msg = Message(
                message_id=f"msg_expired_{i}",
                service_name="test-service",
                method="test_method",
                params={},
                state=MessageState.PENDING,
                created_at=now - timedelta(hours=2),
                updated_at=now - timedelta(hours=2),
                ack_deadline=now - timedelta(hours=1),
                trace_id=f"trace_expired_{i}",
            )
            await service.store_message(msg)

        # Get with limit
        expired_list = await service.get_expired_messages(limit=3)
        assert len(expired_list) == 3

    @pytest.mark.asyncio
    async def test_delete_message_success(
        self, service: MessageStoreService, sample_message: Message
    ) -> None:
        """Test successful message deletion."""
        await service.store_message(sample_message)

        # Delete message
        await service.delete_message(sample_message.message_id)

        # Verify deletion
        assert await service.get_message(sample_message.message_id) is None

    @pytest.mark.asyncio
    async def test_delete_message_not_found(self, service: MessageStoreService) -> None:
        """Test deleting non-existent message."""
        with pytest.raises(NotFoundError):
            await service.delete_message("non_existent_id")

    @pytest.mark.asyncio
    async def test_get_pending_messages_for_retry(self, service: MessageStoreService) -> None:
        """Test retrieving messages eligible for retry."""
        now = datetime.now(UTC)

        # Create messages with different states and retry counts
        eligible_msg = Message(
            message_id="msg_eligible",
            service_name="test-service",
            method="test_method",
            params={},
            state=MessageState.PENDING,
            created_at=now,
            updated_at=now,
            ack_deadline=now + timedelta(minutes=5),
            trace_id="trace_eligible",
            retry_count=1,
        )

        max_retries_msg = Message(
            message_id="msg_max_retries",
            service_name="test-service",
            method="test_method",
            params={},
            state=MessageState.PENDING,
            created_at=now,
            updated_at=now,
            ack_deadline=now + timedelta(minutes=5),
            trace_id="trace_max_retries",
            retry_count=3,  # At max retries
        )

        acked_msg = Message(
            message_id="msg_acked",
            service_name="test-service",
            method="test_method",
            params={},
            state=MessageState.ACKNOWLEDGED,
            created_at=now,
            updated_at=now,
            ack_deadline=now + timedelta(minutes=5),
            trace_id="trace_acked",
        )

        await service.store_message(eligible_msg)
        await service.store_message(max_retries_msg)
        await service.store_message(acked_msg)

        # Get retry eligible messages
        retry_list = await service.get_pending_messages_for_retry()

        assert len(retry_list) == 1
        assert retry_list[0].message_id == "msg_eligible"

    @pytest.mark.asyncio
    async def test_get_pending_messages_for_retry_with_service_filter(
        self, service: MessageStoreService
    ) -> None:
        """Test retrieving retry messages with service filter."""
        now = datetime.now(UTC)

        # Create messages for different services
        service1_msg = Message(
            message_id="msg_service1",
            service_name="service1",
            method="test_method",
            params={},
            state=MessageState.PENDING,
            created_at=now,
            updated_at=now,
            ack_deadline=now + timedelta(minutes=5),
            trace_id="trace_service1",
        )

        service2_msg = Message(
            message_id="msg_service2",
            service_name="service2",
            method="test_method",
            params={},
            state=MessageState.PENDING,
            created_at=now,
            updated_at=now,
            ack_deadline=now + timedelta(minutes=5),
            trace_id="trace_service2",
        )

        await service.store_message(service1_msg)
        await service.store_message(service2_msg)

        # Get with service filter
        retry_list = await service.get_pending_messages_for_retry(service_name="service1")

        assert len(retry_list) == 1
        assert retry_list[0].service_name == "service1"

    @pytest.mark.asyncio
    async def test_start_stop_cleanup_task(self, service: MessageStoreService) -> None:
        """Test starting and stopping cleanup task."""
        # Start cleanup task
        await service.start()
        assert service._running is True
        assert service._cleanup_task is not None

        # Try to start again (should be no-op)
        await service.start()

        # Stop cleanup task
        await service.stop()
        assert service._running is False

    @pytest.mark.asyncio
    async def test_cleanup_expired_messages(self, service: MessageStoreService) -> None:
        """Test cleanup of expired messages."""
        now = datetime.now(UTC)

        # Create old message (beyond TTL)
        old_msg = Message(
            message_id="msg_old",
            service_name="test-service",
            method="test_method",
            params={},
            state=MessageState.ACKNOWLEDGED,
            created_at=now - timedelta(hours=2),  # Beyond 1 hour TTL
            updated_at=now - timedelta(hours=2),
            ack_deadline=now - timedelta(hours=1),
            trace_id="trace_old",
        )

        # Create recent message
        recent_msg = Message(
            message_id="msg_recent",
            service_name="test-service",
            method="test_method",
            params={},
            state=MessageState.PENDING,
            created_at=now - timedelta(minutes=30),
            updated_at=now - timedelta(minutes=30),
            ack_deadline=now + timedelta(minutes=30),
            trace_id="trace_recent",
        )

        await service.store_message(old_msg)
        await service.store_message(recent_msg)

        # Run cleanup
        await service._cleanup_expired_messages()

        # Verify old message was removed
        assert await service.get_message("msg_old") is None
        assert await service.get_message("msg_recent") is not None

    @pytest.mark.asyncio
    async def test_cleanup_loop_error_handling(self, service: MessageStoreService) -> None:
        """Test error handling in cleanup loop."""
        # Mock cleanup method to raise exception
        call_count = 0

        async def mock_cleanup() -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Cleanup error")
            service._running = False  # Stop after first iteration

        with patch.object(service, "_cleanup_expired_messages", side_effect=mock_cleanup):
            service._running = True

            # Run cleanup loop - should handle exception and continue
            with patch("asyncio.sleep", return_value=None):
                await service._cleanup_loop()

            # Verify cleanup was called and exception was handled
            assert call_count > 0

    @pytest.mark.asyncio
    async def test_concurrent_operations(self, service: MessageStoreService) -> None:
        """Test concurrent message operations."""
        # Create multiple messages
        messages = []
        for i in range(10):
            msg = Message(
                message_id=f"msg_concurrent_{i}",
                service_name="test-service",
                method="test_method",
                params={"index": i},
                state=MessageState.PENDING,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                ack_deadline=datetime.now(UTC) + timedelta(minutes=5),
                trace_id=f"trace_concurrent_{i}",
            )
            messages.append(msg)

        # Store messages concurrently
        await asyncio.gather(*[service.store_message(msg) for msg in messages])

        # Update states concurrently
        update_tasks = []
        for i, msg in enumerate(messages):
            if i % 2 == 0:
                update_tasks.append(
                    service.update_message_state(
                        msg.message_id,
                        MessageState.ACKNOWLEDGED.value,
                    )
                )
        await asyncio.gather(*update_tasks)

        # Verify results
        for i, msg in enumerate(messages):
            retrieved = await service.get_message(msg.message_id)
            assert retrieved is not None
            if i % 2 == 0:
                assert retrieved.state == MessageState.ACKNOWLEDGED
            else:
                assert retrieved.state == MessageState.PENDING
