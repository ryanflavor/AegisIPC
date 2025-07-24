#!/usr/bin/env python3
"""Common utilities for demo scripts."""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

# Add packages to path consistently
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "packages" / "ipc_router"))
sys.path.insert(0, str(PROJECT_ROOT / "packages" / "ipc_client_sdk"))

from ipc_router.infrastructure.messaging.nats_client import NATSClient  # noqa: E402


class DemoSettings(BaseSettings):
    """Demo configuration settings."""

    nats_url: str = Field(default="nats://localhost:4223", description="NATS server URL")
    connection_timeout: float = Field(default=5.0, description="Connection timeout in seconds")
    setup_delay: float = Field(default=0.5, description="Setup delay for subscriptions")

    class Config:
        env_prefix = "DEMO_"
        env_file = ".env"


@dataclass
class Colors:
    """ANSI color codes for terminal output."""

    GREEN: str = "\033[92m"
    YELLOW: str = "\033[93m"
    RED: str = "\033[91m"
    BLUE: str = "\033[94m"
    CYAN: str = "\033[96m"
    MAGENTA: str = "\033[95m"
    RESET: str = "\033[0m"
    BOLD: str = "\033[1m"


# Global color instance
colors = Colors()


class DemoLogger:
    """Structured logging for demo scripts."""

    def __init__(self, demo_name: str) -> None:
        self.demo_name = demo_name

    def info(self, message: str, **kwargs: Any) -> None:
        """Log info message with optional context."""
        extra = f" | {kwargs}" if kwargs else ""
        print(f"{colors.GREEN}[INFO]{colors.RESET} {message}{extra}")

    def warning(self, message: str, **kwargs: Any) -> None:
        """Log warning message with optional context."""
        extra = f" | {kwargs}" if kwargs else ""
        print(f"{colors.YELLOW}[WARN]{colors.RESET} {message}{extra}")

    def error(self, message: str, **kwargs: Any) -> None:
        """Log error message with optional context."""
        extra = f" | {kwargs}" if kwargs else ""
        print(f"{colors.RED}[ERROR]{colors.RESET} {message}{extra}")

    def section(self, title: str) -> None:
        """Print section header."""
        print(f"\n{colors.BOLD}{colors.BLUE}=== {title} ==={colors.RESET}\n")

    def subsection(self, title: str) -> None:
        """Print subsection header."""
        print(f"\n{colors.BOLD}{colors.YELLOW}=== {title} ==={colors.RESET}")

    def success(self, message: str) -> None:
        """Print success message."""
        print(f"{colors.GREEN}✓{colors.RESET} {message}")

    def failure(self, message: str) -> None:
        """Print failure message."""
        print(f"{colors.RED}✗{colors.RESET} {message}")

    def demo_header(self, title: str, subtitle: str) -> None:
        """Print demo header."""
        print(f"{colors.BOLD}{colors.CYAN}AegisIPC - {title}{colors.RESET}")
        print(f"{colors.CYAN}{subtitle}{colors.RESET}")
        print(f"{colors.CYAN}{'=' * 50}{colors.RESET}")


async def check_nats_connection(settings: DemoSettings) -> bool:
    """Check if NATS server is accessible.

    Args:
        settings: Demo configuration settings

    Returns:
        True if connection successful, False otherwise
    """
    try:
        test_client = NATSClient(settings.nats_url)
        await test_client.connect()
        await test_client.disconnect()
        return True
    except Exception as e:
        logger = DemoLogger("connection-check")
        logger.error(f"Cannot connect to NATS at {settings.nats_url}", error=str(e))
        logger.info("Please ensure NATS is running: docker run -p 4223:4222 nats:latest")
        return False


class DemoResult(BaseModel):
    """Result of a demo execution."""

    success: bool = Field(description="Whether the demo succeeded")
    criteria_passed: list[str] = Field(
        default_factory=list, description="Acceptance criteria that passed"
    )
    criteria_failed: list[str] = Field(
        default_factory=list, description="Acceptance criteria that failed"
    )
    error_message: str | None = Field(default=None, description="Error message if demo failed")


async def run_with_timeout(
    coro: Any, timeout: float, operation_name: str
) -> tuple[bool, Any, str | None]:
    """Run a coroutine with timeout.

    Args:
        coro: Coroutine to run
        timeout: Timeout in seconds
        operation_name: Name of operation for error messages

    Returns:
        Tuple of (success, result, error_message)
    """
    try:
        result = await asyncio.wait_for(coro, timeout=timeout)
        return True, result, None
    except TimeoutError:
        return False, None, f"{operation_name} timed out after {timeout}s"
    except Exception as e:
        return False, None, f"{operation_name} failed: {e}"


def format_instance_id(instance_id: str) -> str:
    """Format instance ID with color."""
    return f"{colors.CYAN}{instance_id}{colors.RESET}"


def format_service_name(service_name: str) -> str:
    """Format service name with color."""
    return f"{colors.MAGENTA}{service_name}{colors.RESET}"
