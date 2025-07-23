"""Unit tests for application event bus and events."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from ipc_router.application.events import Event, EventBus


class MockEventHandler:
    """Mock event handler for testing."""

    def __init__(self) -> None:
        """Initialize mock handler."""
        self.handled_events: list[Event] = []
        self.handle_called = False

    async def handle(self, event: Event) -> None:
        """Handle an event."""
        self.handle_called = True
        self.handled_events.append(event)


class TestEvent:
    """Test Event class."""

    def test_event_creation_with_defaults(self) -> None:
        """Test creating event with default values."""
        event = Event(
            event_id="test-123",
            event_type="test.event",
        )

        assert event.event_id == "test-123"
        assert event.event_type == "test.event"
        assert event.data == {}
        assert event.trace_id is None
        assert isinstance(event.timestamp, datetime)

    def test_event_creation_with_all_fields(self) -> None:
        """Test creating event with all fields."""
        timestamp = datetime.now(UTC)
        event = Event(
            event_id="test-456",
            event_type="test.complete",
            timestamp=timestamp,
            data={"key": "value", "count": 42},
            trace_id="trace-789",
        )

        assert event.event_id == "test-456"
        assert event.event_type == "test.complete"
        assert event.timestamp == timestamp
        assert event.data == {"key": "value", "count": 42}
        assert event.trace_id == "trace-789"


class TestEventBus:
    """Test EventBus functionality."""

    @pytest.fixture
    def event_bus(self) -> EventBus:
        """Create an event bus instance."""
        return EventBus()

    @pytest.mark.asyncio
    async def test_subscribe_and_publish(self, event_bus: EventBus) -> None:
        """Test subscribing handler and publishing event."""
        # Create handler
        handler = MockEventHandler()

        # Subscribe to event type
        event_bus.subscribe("user.created", handler)

        # Create and publish event
        event = Event(
            event_id="evt-1",
            event_type="user.created",
            data={"user_id": "123"},
        )

        await event_bus.publish(event)

        # Verify handler was called
        assert handler.handle_called
        assert len(handler.handled_events) == 1
        assert handler.handled_events[0] == event

    @pytest.mark.asyncio
    async def test_multiple_handlers_for_same_event(self, event_bus: EventBus) -> None:
        """Test multiple handlers for the same event type."""
        # Create handlers
        handler1 = MockEventHandler()
        handler2 = MockEventHandler()
        handler3 = MockEventHandler()

        # Subscribe all to same event type
        event_bus.subscribe("order.placed", handler1)
        event_bus.subscribe("order.placed", handler2)
        event_bus.subscribe("order.placed", handler3)

        # Publish event
        event = Event(
            event_id="evt-2",
            event_type="order.placed",
            data={"order_id": "456"},
        )

        await event_bus.publish(event)

        # All handlers should be called
        assert handler1.handle_called
        assert handler2.handle_called
        assert handler3.handle_called

    @pytest.mark.asyncio
    async def test_publish_event_no_handlers(self, event_bus: EventBus) -> None:
        """Test publishing event when no handlers are subscribed."""
        # Publish event without any handlers
        event = Event(
            event_id="evt-3",
            event_type="unhandled.event",
        )

        # Should not raise any errors
        await event_bus.publish(event)

    def test_unsubscribe_handler(self, event_bus: EventBus) -> None:
        """Test unsubscribing a handler."""
        # Create handlers
        handler1 = MockEventHandler()
        handler2 = MockEventHandler()

        # Subscribe both
        event_bus.subscribe("test.event", handler1)
        event_bus.subscribe("test.event", handler2)

        # Unsubscribe handler1
        event_bus.unsubscribe("test.event", handler1)

        # Check internal state
        assert handler1 not in event_bus._handlers.get("test.event", [])
        assert handler2 in event_bus._handlers.get("test.event", [])

    def test_unsubscribe_from_non_existent_event_type(self, event_bus: EventBus) -> None:
        """Test unsubscribing from event type that doesn't exist."""
        handler = MockEventHandler()

        # Should not raise error
        event_bus.unsubscribe("non.existent", handler)

    @pytest.mark.asyncio
    async def test_event_handler_protocol(self, event_bus: EventBus) -> None:
        """Test that any object implementing EventHandler protocol works."""

        # Create a class that implements the protocol
        class CustomHandler:
            def __init__(self) -> None:
                self.events: list[Event] = []

            async def handle(self, event: Event) -> None:
                self.events.append(event)

        handler = CustomHandler()
        event_bus.subscribe("custom.event", handler)

        event = Event(event_id="evt-4", event_type="custom.event")
        await event_bus.publish(event)

        assert len(handler.events) == 1
        assert handler.events[0] == event

    @pytest.mark.asyncio
    async def test_concurrent_event_publishing(self, event_bus: EventBus) -> None:
        """Test concurrent event publishing."""
        handler = MockEventHandler()
        event_bus.subscribe("concurrent.test", handler)

        # Create multiple events
        events = [
            Event(
                event_id=f"evt-{i}",
                event_type="concurrent.test",
                data={"index": i},
            )
            for i in range(10)
        ]

        # Publish concurrently
        await asyncio.gather(*[event_bus.publish(event) for event in events])

        # All events should be handled
        assert len(handler.handled_events) == 10

        # Check all events were received (order may vary)
        received_indices = {e.data["index"] for e in handler.handled_events}
        assert received_indices == set(range(10))

    def test_subscribe_same_handler_multiple_times(self, event_bus: EventBus) -> None:
        """Test subscribing same handler multiple times."""
        handler = MockEventHandler()

        # Subscribe same handler twice
        event_bus.subscribe("duplicate.test", handler)
        event_bus.subscribe("duplicate.test", handler)

        # Should have handler twice in the list
        assert len(event_bus._handlers["duplicate.test"]) == 2
