"""Integration test configuration and fixtures."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from ipc_router.infrastructure.messaging import NATSClient


@pytest.fixture(scope="session")
def nats_url() -> str:
    """NATS server URL for tests."""
    # Can be overridden by environment variable
    return os.environ.get("NATS_URL", "nats://localhost:4222")


@pytest_asyncio.fixture
async def nats_client(
    nats_url: str,
) -> AsyncGenerator[NATSClient]:
    """Create a NATS client for testing.

    Note: This assumes NATS is already running either via:
    - docker-compose up nats
    - Local NATS server
    - CI/CD environment
    """
    client = NATSClient([nats_url])
    try:
        await client.connect()
        yield client
    finally:
        await client.disconnect()


@pytest.fixture
def service_subject() -> str:
    """Subject for service registration."""
    return "ipc.service.register"


@pytest.fixture
def heartbeat_subject() -> str:
    """Subject for heartbeat updates."""
    return "ipc.service.heartbeat"


@pytest.fixture
def timeout_seconds() -> float:
    """Default timeout for requests."""
    return 5.0
