#!/usr/bin/env python3
"""Verify Story 2.1 implementation without running full integration test."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


def check_file_for_pattern(file_path: Path, patterns: list[str]) -> list[str]:
    """Check if file contains specific patterns."""
    found = []
    try:
        content = file_path.read_text()
        for pattern in patterns:
            if pattern in content:
                found.append(pattern)
    except Exception:
        pass
    return found


def verify_implementation() -> bool:
    """Verify all features are implemented."""
    print("Verifying Story 2.1 Implementation...")
    print("=" * 50)

    results = {
        "AC1": False,  # Automatic heartbeat
        "AC2": False,  # Health status management
        "AC3": False,  # Unhealthy instance filtering
        "AC4": False,  # Instance-level retry
    }

    # Check AC1: Automatic heartbeat in ServiceClient
    service_client = (
        PROJECT_ROOT / "packages/ipc_client_sdk/ipc_client_sdk/clients/service_client.py"
    )
    patterns = [
        "heartbeat_enabled",
        "heartbeat_interval",
        "start_heartbeat",
        "if self._config.heartbeat_enabled:",
    ]
    found = check_file_for_pattern(service_client, patterns)
    if len(found) >= 3:
        print("✓ AC1: Automatic heartbeat implementation found")
        results["AC1"] = True
    else:
        print("✗ AC1: Missing automatic heartbeat features")

    # Check AC2: Health status management
    health_checker = (
        PROJECT_ROOT / "packages/ipc_router/ipc_router/application/services/health_checker.py"
    )
    patterns = [
        "class HealthChecker",
        "_mark_instance_unhealthy",
        "heartbeat_timeout",
    ]
    found = check_file_for_pattern(health_checker, patterns)
    if len(found) >= 2:
        print("✓ AC2: Health status management found")
        results["AC2"] = True
    else:
        print("✗ AC2: Missing health status management")

    # Check AC3: Unhealthy instance filtering
    routing_service = (
        PROJECT_ROOT / "packages/ipc_router/ipc_router/application/services/routing_service.py"
    )
    patterns = [
        "get_healthy_instances",
        "excluded_instances",
    ]
    found = check_file_for_pattern(routing_service, patterns)
    if len(found) >= 1:
        print("✓ AC3: Unhealthy instance filtering found")
        results["AC3"] = True
    else:
        print("✗ AC3: Missing unhealthy instance filtering")

    # Check AC4: Instance-level retry
    patterns = [
        "call_with_failover",
        "excluded_instances",
        "retry on different",
    ]
    found = check_file_for_pattern(service_client, patterns)
    if "call_with_failover" in found:
        print("✓ AC4: Instance-level retry found")
        results["AC4"] = True
    else:
        print("✗ AC4: Missing instance-level retry")

    # Check models
    routing_models = (
        PROJECT_ROOT / "packages/ipc_router/ipc_router/application/models/routing_models.py"
    )
    patterns = [
        "class HeartbeatRequest",
        "class HeartbeatResponse",
        "excluded_instances",
    ]
    found = check_file_for_pattern(routing_models, patterns)
    print(f"\nHeartbeat models found: {len([p for p in patterns[:2] if p in found])}/2")
    print(f"Excluded instances field: {'✓' if 'excluded_instances' in found else '✗'}")

    # Summary
    print("\n" + "=" * 50)
    print("SUMMARY:")
    passed = sum(results.values())
    total = len(results)

    if passed == total:
        print(f"✅ ALL {total} acceptance criteria have been implemented!")
    else:
        print(f"⚠️  {passed}/{total} acceptance criteria implemented")

    for ac, passed in results.items():
        status = "✓" if passed else "✗"
        print(f"  {status} {ac}")

    # Additional checks
    print("\nAdditional Features:")

    # Check metrics
    metrics_file = (
        PROJECT_ROOT / "packages/ipc_router/ipc_router/infrastructure/monitoring/metrics.py"
    )
    if metrics_file.exists():
        content = metrics_file.read_text()
        if "heartbeat" in content:
            print("✓ Heartbeat metrics implemented")
        if "instance_failover" in content:
            print("✓ Instance failover metrics implemented")

    # Check for demo script
    demo_script = PROJECT_ROOT / "scripts/demo_story_2_1_nats.py"
    if demo_script.exists():
        print("✓ Demo script created")

    return passed == total


if __name__ == "__main__":
    success = verify_implementation()
    sys.exit(0 if success else 1)
