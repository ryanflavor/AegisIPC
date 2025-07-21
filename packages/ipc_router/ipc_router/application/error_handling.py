"""Error handling patterns and utilities for the application layer.

This module demonstrates best practices for error handling in the AegisIPC
application, including retry logic, circuit breakers, and error recovery.
"""

import asyncio
import functools
from collections.abc import Callable
from datetime import UTC, datetime
from enum import Enum
from typing import Any, TypeVar

from pydantic import BaseModel, Field

from ipc_router.domain.exceptions import (
    ApplicationError,
    InfrastructureError,
    ServiceUnavailableError,
)
from ipc_router.domain.exceptions import (
    TimeoutError as AegisTimeoutError,
)
from ipc_router.infrastructure.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")
AsyncFunc = TypeVar("AsyncFunc", bound=Callable[..., Any])


class RetryStrategy(str, Enum):
    """Retry strategies for error recovery."""

    EXPONENTIAL = "exponential"
    LINEAR = "linear"
    CONSTANT = "constant"


class RetryConfig(BaseModel):
    """Configuration for retry behavior."""

    max_attempts: int = Field(default=3, ge=1, description="Maximum retry attempts")
    initial_delay: float = Field(default=1.0, gt=0, description="Initial delay in seconds")
    max_delay: float = Field(default=60.0, gt=0, description="Maximum delay in seconds")
    strategy: RetryStrategy = Field(default=RetryStrategy.EXPONENTIAL, description="Retry strategy")
    jitter: bool = Field(default=True, description="Add jitter to retry delays")
    retryable_exceptions: tuple[type[Exception], ...] = Field(
        default=(InfrastructureError, ServiceUnavailableError),
        description="Exceptions that trigger retry",
    )


def calculate_retry_delay(
    attempt: int,
    config: RetryConfig,
) -> float:
    """Calculate delay before next retry attempt."""
    if config.strategy == RetryStrategy.CONSTANT:
        delay = config.initial_delay
    elif config.strategy == RetryStrategy.LINEAR:
        delay = config.initial_delay * attempt
    else:  # EXPONENTIAL
        delay = config.initial_delay * (2 ** (attempt - 1))

    # Apply max delay cap
    delay = min(delay, config.max_delay)

    # Add jitter if enabled
    if config.jitter:
        import random

        jitter_range = delay * 0.1  # 10% jitter
        delay += random.uniform(-jitter_range, jitter_range)

    return max(0.1, delay)  # Ensure minimum delay


def with_retry(config: RetryConfig | None = None) -> Callable[[AsyncFunc], AsyncFunc]:
    """
    Decorator for adding retry logic to async functions.

    Example:
        @with_retry(RetryConfig(max_attempts=5))
        async def fetch_data():
            # Code that might fail
            pass
    """
    if config is None:
        config = RetryConfig()

    def decorator(func: AsyncFunc) -> AsyncFunc:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception: Exception | None = None

            for attempt in range(1, config.max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except config.retryable_exceptions as e:
                    last_exception = e
                    if attempt == config.max_attempts:
                        logger.error(
                            f"Max retry attempts ({config.max_attempts}) reached for {func.__name__}",
                            extra={
                                "function": func.__name__,
                                "attempt": attempt,
                                "error": str(e),
                            },
                        )
                        raise

                    delay = calculate_retry_delay(attempt, config)
                    logger.warning(
                        f"Retry attempt {attempt}/{config.max_attempts} for {func.__name__} "
                        f"after {delay:.2f}s delay",
                        extra={
                            "function": func.__name__,
                            "attempt": attempt,
                            "delay": delay,
                            "error": str(e),
                        },
                    )
                    await asyncio.sleep(delay)
                except Exception as e:
                    # Non-retryable exception
                    logger.error(
                        f"Non-retryable error in {func.__name__}: {e}",
                        extra={"function": func.__name__, "error": str(e)},
                    )
                    raise

            # Should never reach here, but just in case
            if last_exception:
                raise last_exception
            raise ApplicationError("Unexpected retry loop exit")

        return wrapper  # type: ignore

    return decorator


class CircuitBreakerState(Enum):
    """States of a circuit breaker."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, rejecting calls
    HALF_OPEN = "half_open"  # Testing if service recovered


class CircuitBreaker:
    """
    Circuit breaker pattern implementation for fault tolerance.

    Example:
        breaker = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=60,
            expected_exception=ServiceUnavailableError
        )

        async with breaker:
            result = await external_service_call()
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        expected_exception: type[Exception] = Exception,
        name: str | None = None,
    ) -> None:
        """
        Initialize circuit breaker.

        Args:
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Seconds before attempting recovery
            expected_exception: Exception type that triggers the breaker
            name: Optional name for logging
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        self.name = name or "CircuitBreaker"

        self._state = CircuitBreakerState.CLOSED
        self._failure_count = 0
        self._last_failure_time: datetime | None = None
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitBreakerState:
        """Get current circuit breaker state."""
        return self._state

    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset."""
        if self._last_failure_time is None:
            return False

        time_since_failure = datetime.now(UTC) - self._last_failure_time
        return time_since_failure.total_seconds() >= self.recovery_timeout

    async def __aenter__(self) -> "CircuitBreaker":
        """Enter circuit breaker context."""
        async with self._lock:
            if self._state == CircuitBreakerState.OPEN:
                if self._should_attempt_reset():
                    logger.info(f"{self.name}: Attempting reset to HALF_OPEN")
                    self._state = CircuitBreakerState.HALF_OPEN
                else:
                    raise ServiceUnavailableError(
                        self.name,
                        f"Circuit breaker is OPEN (failures: {self._failure_count})",
                    )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> bool:
        """Exit circuit breaker context."""
        async with self._lock:
            if exc_type is None:
                # Success
                if self._state == CircuitBreakerState.HALF_OPEN:
                    logger.info(f"{self.name}: Reset to CLOSED after successful call")
                    self._state = CircuitBreakerState.CLOSED
                    self._failure_count = 0
                    self._last_failure_time = None
            elif issubclass(exc_type, self.expected_exception):
                # Expected failure
                self._failure_count += 1
                self._last_failure_time = datetime.now(UTC)

                if self._failure_count >= self.failure_threshold:
                    logger.error(
                        f"{self.name}: Opening circuit after {self._failure_count} failures"
                    )
                    self._state = CircuitBreakerState.OPEN
                elif self._state == CircuitBreakerState.HALF_OPEN:
                    logger.warning(f"{self.name}: Reopening circuit after HALF_OPEN failure")
                    self._state = CircuitBreakerState.OPEN

        return False  # Don't suppress exceptions


async def with_timeout(
    coro: Any,
    timeout: float,
    operation_name: str = "operation",
) -> Any:
    """
    Execute coroutine with timeout.

    Args:
        coro: Coroutine to execute
        timeout: Timeout in seconds
        operation_name: Name for error reporting

    Returns:
        Coroutine result

    Raises:
        AegisTimeoutError: If operation times out
    """
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except TimeoutError as e:
        raise AegisTimeoutError(operation_name, timeout) from e


class ErrorAggregator:
    """
    Aggregate multiple errors for batch operations.

    Example:
        aggregator = ErrorAggregator()

        for item in items:
            try:
                await process_item(item)
            except Exception as e:
                aggregator.add_error(item.id, e)

        if aggregator.has_errors():
            # Handle aggregated errors
            logger.error(f"Processing failed for {aggregator.error_count} items")
    """

    def __init__(self) -> None:
        """Initialize error aggregator."""
        self._errors: dict[str, Exception] = {}

    def add_error(self, identifier: str, error: Exception) -> None:
        """Add an error to the aggregator."""
        self._errors[identifier] = error

    def has_errors(self) -> bool:
        """Check if any errors have been recorded."""
        return len(self._errors) > 0

    @property
    def error_count(self) -> int:
        """Get number of recorded errors."""
        return len(self._errors)

    @property
    def errors(self) -> dict[str, Exception]:
        """Get all recorded errors."""
        return self._errors.copy()

    def get_summary(self) -> str:
        """Get a summary of all errors."""
        if not self._errors:
            return "No errors"

        error_types: dict[str, int] = {}
        for error in self._errors.values():
            error_type = type(error).__name__
            error_types[error_type] = error_types.get(error_type, 0) + 1

        summary_parts = [f"{count} {error_type}" for error_type, count in error_types.items()]
        return f"Errors: {', '.join(summary_parts)} (Total: {self.error_count})"


# Example usage function
async def example_error_handling() -> None:
    """Demonstrate error handling patterns."""

    # Example 1: Retry decorator
    @with_retry(RetryConfig(max_attempts=3, initial_delay=1.0))
    async def flaky_service_call() -> str:
        # Simulate flaky service
        import random

        if random.random() < 0.7:
            raise ServiceUnavailableError("ExampleService", "Random failure")
        return "Success"

    # Example 2: Circuit breaker
    breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=30)

    async def protected_call() -> str:
        async with breaker:
            # Call that might fail
            return await flaky_service_call()
        return "Failed"  # Add default return for type checker

    # Example 3: Timeout wrapper
    try:
        await with_timeout(
            protected_call(),
            timeout=5.0,
            operation_name="protected_call",
        )
    except AegisTimeoutError as e:
        logger.error(f"Operation timed out: {e}")

    # Example 4: Error aggregation
    aggregator = ErrorAggregator()
    items = ["item1", "item2", "item3"]

    for item in items:
        try:
            # Process item
            if item == "item2":
                raise ValueError("Invalid item")
        except Exception as e:
            aggregator.add_error(item, e)

    if aggregator.has_errors():
        logger.error(f"Batch processing completed with errors: {aggregator.get_summary()}")
