"""Tests for error handling utilities."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from ipc_router.application.error_handling import (
    CircuitBreaker,
    CircuitBreakerState,
    RetryConfig,
    RetryStrategy,
    with_retry,
    with_timeout,
)
from ipc_router.domain.exceptions import (
    ServiceUnavailableError,
)
from ipc_router.domain.exceptions import (
    TimeoutError as AegisTimeoutError,
)


class TestRetryConfig:
    """Test retry configuration."""

    def test_default_config(self) -> None:
        """Test default retry configuration."""
        config = RetryConfig()
        assert config.max_attempts == 3
        assert config.initial_delay == 1.0
        assert config.max_delay == 60.0
        assert config.strategy == RetryStrategy.EXPONENTIAL
        assert config.jitter is True

    def test_custom_config(self) -> None:
        """Test custom retry configuration."""
        config = RetryConfig(
            max_attempts=5,
            initial_delay=0.5,
            max_delay=30.0,
            strategy=RetryStrategy.LINEAR,
            jitter=False,
        )
        assert config.max_attempts == 5
        assert config.initial_delay == 0.5
        assert config.max_delay == 30.0
        assert config.strategy == RetryStrategy.LINEAR
        assert config.jitter is False


class TestRetryDelay:
    """Test retry delay calculation."""

    def test_constant_strategy(self) -> None:
        """Test constant retry delay strategy."""
        from ipc_router.application.error_handling import calculate_retry_delay

        config = RetryConfig(strategy=RetryStrategy.CONSTANT, initial_delay=1.0, jitter=False)

        # All attempts should have same delay
        assert calculate_retry_delay(1, config) == 1.0
        assert calculate_retry_delay(2, config) == 1.0
        assert calculate_retry_delay(3, config) == 1.0

    def test_linear_strategy(self) -> None:
        """Test linear retry delay strategy."""
        from ipc_router.application.error_handling import calculate_retry_delay

        config = RetryConfig(strategy=RetryStrategy.LINEAR, initial_delay=1.0, jitter=False)

        # Delay should increase linearly
        assert calculate_retry_delay(1, config) == 1.0
        assert calculate_retry_delay(2, config) == 2.0
        assert calculate_retry_delay(3, config) == 3.0

    def test_exponential_with_max_delay(self) -> None:
        """Test exponential strategy with max delay cap."""
        from ipc_router.application.error_handling import calculate_retry_delay

        config = RetryConfig(
            strategy=RetryStrategy.EXPONENTIAL, initial_delay=1.0, max_delay=5.0, jitter=False
        )

        # Test that delay is capped at max_delay
        assert calculate_retry_delay(1, config) == 1.0  # 1 * 2^0
        assert calculate_retry_delay(2, config) == 2.0  # 1 * 2^1
        assert calculate_retry_delay(3, config) == 4.0  # 1 * 2^2
        assert calculate_retry_delay(4, config) == 5.0  # Would be 8, but capped at 5


class TestWithRetry:
    """Test retry decorator."""

    @pytest.mark.asyncio
    async def test_successful_on_first_attempt(self) -> None:
        """Test function succeeds on first attempt."""
        mock_func = AsyncMock(return_value="success")
        config = RetryConfig(max_attempts=3)

        @with_retry(config)  # type: ignore[misc]
        async def test_func() -> str:
            return await mock_func()  # type: ignore[no-any-return]

        result = await test_func()
        assert result == "success"
        assert mock_func.call_count == 1

    @pytest.mark.asyncio
    async def test_retry_on_failure(self) -> None:
        """Test function retries on failure."""
        mock_func = AsyncMock(side_effect=[ServiceUnavailableError("service", "down"), "success"])
        config = RetryConfig(max_attempts=3, initial_delay=0.01)

        @with_retry(config)  # type: ignore[misc]
        async def test_func() -> str:
            return await mock_func()  # type: ignore[no-any-return]

        result = await test_func()
        assert result == "success"
        assert mock_func.call_count == 2

    @pytest.mark.asyncio
    async def test_max_attempts_exceeded(self) -> None:
        """Test function fails after max attempts."""
        mock_func = AsyncMock(side_effect=ServiceUnavailableError("service", "down"))
        config = RetryConfig(max_attempts=3, initial_delay=0.01)

        @with_retry(config)  # type: ignore[misc]
        async def test_func() -> str:
            return await mock_func()  # type: ignore[no-any-return]

        with pytest.raises(ServiceUnavailableError):
            await test_func()
        assert mock_func.call_count == 3

    @pytest.mark.asyncio
    async def test_non_retryable_exception(self) -> None:
        """Test non-retryable exceptions are not retried."""
        mock_func = AsyncMock(side_effect=ValueError("bad value"))
        config = RetryConfig(max_attempts=3)

        @with_retry(config)  # type: ignore[misc]
        async def test_func() -> str:
            return await mock_func()  # type: ignore[no-any-return]

        with pytest.raises(ValueError):
            await test_func()
        assert mock_func.call_count == 1


class TestWithTimeout:
    """Test timeout wrapper."""

    @pytest.mark.asyncio
    async def test_successful_within_timeout(self) -> None:
        """Test function completes within timeout."""

        async def test_func() -> str:
            await asyncio.sleep(0.01)
            return "success"

        result = await with_timeout(test_func(), timeout=1.0, operation_name="test")
        assert result == "success"

    @pytest.mark.asyncio
    async def test_timeout_exceeded(self) -> None:
        """Test function times out."""

        async def test_func() -> str:
            await asyncio.sleep(1.0)
            return "success"

        with pytest.raises(AegisTimeoutError) as exc_info:
            await with_timeout(test_func(), timeout=0.01, operation_name="test")

        assert exc_info.value.details["operation"] == "test"
        assert exc_info.value.details["timeout_seconds"] == 0.01


class TestCircuitBreaker:
    """Test circuit breaker pattern."""

    def test_initial_state(self) -> None:
        """Test circuit breaker initial state."""
        breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=10.0)
        assert breaker.state == CircuitBreakerState.CLOSED
        assert breaker.failure_count == 0

    @pytest.mark.asyncio
    async def test_successful_calls(self) -> None:
        """Test successful calls don't open circuit."""
        breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=10.0)

        async def success_func() -> str:
            return "success"

        for _ in range(5):
            async with breaker:
                result = await success_func()
                assert result == "success"

        assert breaker.state == CircuitBreakerState.CLOSED
        assert breaker.failure_count == 0

    @pytest.mark.asyncio
    async def test_circuit_opens_on_failures(self) -> None:
        """Test circuit opens after threshold failures."""
        breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=10.0)

        for _ in range(3):
            try:
                async with breaker:
                    raise ServiceUnavailableError("test", "error")
            except ServiceUnavailableError:
                pass

        assert breaker.state == CircuitBreakerState.OPEN
        assert breaker.failure_count == 3

    @pytest.mark.asyncio
    async def test_open_circuit_rejects_calls(self) -> None:
        """Test open circuit rejects calls immediately."""
        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=10.0)

        # Open the circuit
        try:
            async with breaker:
                raise ServiceUnavailableError("test", "error")
        except ServiceUnavailableError:
            pass

        # Should reject without calling function
        with pytest.raises(ServiceUnavailableError) as exc_info:
            async with breaker:
                # This should not be executed
                raise AssertionError("Should not reach here")

        assert "Circuit breaker is OPEN" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_half_open_state(self) -> None:
        """Test circuit moves to half-open after recovery timeout."""
        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01)

        # Open the circuit
        try:
            async with breaker:
                raise ServiceUnavailableError("test", "error")
        except ServiceUnavailableError:
            pass

        # Wait for recovery timeout
        await asyncio.sleep(0.02)

        # Circuit should be half-open now
        async with breaker:
            pass  # Successful call

        # Successful call should close the circuit
        assert breaker.state == CircuitBreakerState.CLOSED
        assert breaker.failure_count == 0
