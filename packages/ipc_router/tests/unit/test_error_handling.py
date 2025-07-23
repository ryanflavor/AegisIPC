"""Unit tests for error handling decorators and utilities."""

from __future__ import annotations

import asyncio

import pytest
from ipc_router.application.error_handling import (
    CircuitBreaker,
    CircuitBreakerState,
    ErrorAggregator,
    RetryConfig,
    calculate_retry_delay,
    with_retry,
    with_timeout,
)
from ipc_router.domain.exceptions import (
    ServiceUnavailableError,
    ValidationError,
)
from ipc_router.domain.exceptions import (
    TimeoutError as AegisTimeoutError,
)


class TestRetryMechanism:
    """Test retry functionality."""

    @pytest.mark.asyncio
    async def test_with_retry_success_first_attempt(self) -> None:
        """Test retry decorator succeeds on first attempt."""
        call_count = 0

        @with_retry()
        async def test_func() -> str:
            nonlocal call_count
            call_count += 1
            return "success"

        result = await test_func()
        assert result == "success"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_with_retry_success_after_retries(self) -> None:
        """Test retry decorator succeeds after retries."""
        call_count = 0

        @with_retry(RetryConfig(max_attempts=3, initial_delay=0.01))
        async def test_func() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ServiceUnavailableError("test-service", "Temporary failure")
            return "success"

        result = await test_func()
        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_with_retry_max_attempts_exceeded(self) -> None:
        """Test retry decorator fails after max attempts."""
        call_count = 0

        @with_retry(RetryConfig(max_attempts=3, initial_delay=0.01))
        async def test_func() -> str:
            nonlocal call_count
            call_count += 1
            raise ServiceUnavailableError("test-service", "Permanent failure")

        with pytest.raises(ServiceUnavailableError):
            await test_func()
        assert call_count == 3

    def test_calculate_retry_delay_exponential(self) -> None:
        """Test exponential retry delay calculation."""
        config = RetryConfig(initial_delay=1.0, strategy="exponential", jitter=False)

        # Without jitter, delays should be predictable (attempts are 1-based)
        assert calculate_retry_delay(1, config) == 1.0
        assert calculate_retry_delay(2, config) == 2.0
        assert calculate_retry_delay(3, config) == 4.0

    def test_calculate_retry_delay_with_max(self) -> None:
        """Test retry delay respects max_delay."""
        config = RetryConfig(initial_delay=1.0, max_delay=5.0, strategy="exponential", jitter=False)

        # Should cap at max_delay
        assert calculate_retry_delay(10, config) <= 5.0


class TestTimeoutWrapper:
    """Test timeout functionality."""

    @pytest.mark.asyncio
    async def test_with_timeout_success(self) -> None:
        """Test timeout wrapper with successful operation."""

        async def test_func() -> str:
            await asyncio.sleep(0.01)
            return "success"

        result = await with_timeout(test_func(), timeout=1.0)
        assert result == "success"

    @pytest.mark.asyncio
    async def test_with_timeout_exceeded(self) -> None:
        """Test timeout wrapper when timeout is exceeded."""

        async def test_func() -> str:
            await asyncio.sleep(0.1)
            return "success"

        with pytest.raises(AegisTimeoutError) as exc_info:
            await with_timeout(test_func(), timeout=0.01, operation_name="test_op")

        assert "test_op" in str(exc_info.value)


class TestCircuitBreaker:
    """Test circuit breaker pattern."""

    @pytest.mark.asyncio
    async def test_circuit_breaker_closed_state(self) -> None:
        """Test circuit breaker in closed state allows calls."""
        breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=1.0)
        assert breaker._state == CircuitBreakerState.CLOSED

        call_count = 0

        async def test_func() -> str:
            nonlocal call_count
            call_count += 1
            return "success"

        # Should work normally
        async with breaker:
            result = await test_func()
            assert result == "success"

        assert call_count == 1
        assert breaker._state == CircuitBreakerState.CLOSED

    @pytest.mark.asyncio
    async def test_circuit_breaker_opens_after_failures(self) -> None:
        """Test circuit breaker opens after threshold failures."""
        breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)

        # First failure
        with pytest.raises(ServiceUnavailableError):
            async with breaker:
                raise ServiceUnavailableError("test-service", "Failure 1")

        # Second failure - should open circuit
        with pytest.raises(ServiceUnavailableError):
            async with breaker:
                raise ServiceUnavailableError("test-service", "Failure 2")

        assert breaker._state == CircuitBreakerState.OPEN

    @pytest.mark.asyncio
    async def test_circuit_breaker_recovery(self) -> None:
        """Test circuit breaker recovery to half-open state."""
        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01)

        # Open the circuit
        with pytest.raises(ServiceUnavailableError):
            async with breaker:
                raise ServiceUnavailableError("test-service", "Failure")

        assert breaker._state == CircuitBreakerState.OPEN

        # Wait for recovery
        await asyncio.sleep(0.02)

        # Should transition to half-open on next call
        async with breaker:
            pass  # Circuit should transition to half-open

        # Successful call should close the circuit
        assert breaker._state == CircuitBreakerState.CLOSED


class TestErrorAggregator:
    """Test error aggregation functionality."""

    def test_error_aggregator_empty(self) -> None:
        """Test empty error aggregator."""
        aggregator = ErrorAggregator()
        assert not aggregator.has_errors()
        assert aggregator.error_count == 0
        assert aggregator.get_summary() == "No errors"

    def test_error_aggregator_add_errors(self) -> None:
        """Test adding errors to aggregator."""
        aggregator = ErrorAggregator()

        aggregator.add_error("item1", ValueError("Invalid value"))
        aggregator.add_error("item2", ServiceUnavailableError("service", "Down"))
        aggregator.add_error("item3", ValueError("Another invalid"))

        assert aggregator.has_errors()
        assert aggregator.error_count == 3

        summary = aggregator.get_summary()
        assert "2 ValueError" in summary
        assert "1 ServiceUnavailableError" in summary
        assert "Total: 3" in summary

    def test_error_aggregator_get_errors(self) -> None:
        """Test retrieving errors from aggregator."""
        aggregator = ErrorAggregator()

        error1 = ValueError("Error 1")
        error2 = ValidationError("Error 2")

        aggregator.add_error("id1", error1)
        aggregator.add_error("id2", error2)

        errors = aggregator.errors
        assert len(errors) == 2
        assert errors["id1"] is error1
        assert errors["id2"] is error2

        # Should return a copy
        errors.clear()
        assert aggregator.error_count == 2
