"""Event bus and event definitions for the application layer."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel, Field


class Event(BaseModel):
    """Base event class."""

    event_id: str = Field(..., description="Unique event identifier")
    event_type: str = Field(..., description="Type of event")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    data: dict[str, Any] = Field(default_factory=dict)
    trace_id: str | None = Field(None, description="Trace ID for correlation")


class EventHandler(Protocol):
    """Protocol for event handlers."""

    async def handle(self, event: Event) -> None:
        """Handle an event."""
        ...


class EventBus:
    """Simple in-memory event bus for application events."""

    def __init__(self) -> None:
        """Initialize event bus."""
        self._handlers: dict[str, list[EventHandler]] = {}

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """Subscribe a handler to an event type."""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)

    def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        """Unsubscribe a handler from an event type."""
        if event_type in self._handlers:
            self._handlers[event_type] = [h for h in self._handlers[event_type] if h != handler]

    async def publish(self, event: Event) -> None:
        """Publish an event to all subscribed handlers."""
        if event.event_type in self._handlers:
            for handler in self._handlers[event.event_type]:
                await handler.handle(event)
