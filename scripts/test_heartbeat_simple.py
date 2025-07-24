#!/usr/bin/env python3
"""Simple test to verify heartbeat functionality."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Add packages to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "packages" / "ipc_router"))
sys.path.insert(0, str(PROJECT_ROOT / "packages" / "ipc_client_sdk"))

from ipc_client_sdk.clients import ServiceClient, ServiceClientConfig  # noqa: E402


async def main() -> None:
    """Test automatic heartbeat functionality."""
    print("Testing automatic heartbeat after registration...")

    # Create client with heartbeat enabled
    config = ServiceClientConfig(
        nats_servers="nats://localhost:4223",
        heartbeat_enabled=True,
        heartbeat_interval=2.0,
    )

    client = ServiceClient(config=config)
    await client.connect()
    print("✓ Connected to NATS")

    # Register service
    await client.register(
        service_name="test-heartbeat-service",
        instance_id="test-instance-1",
    )
    print("✓ Service registered")

    # Wait for heartbeats
    print("Waiting for heartbeats to be sent...")
    await asyncio.sleep(5.0)

    print("✓ Test completed successfully!")

    # Cleanup
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
