"""Test thread safety of MessageMetricsCollector."""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from ipc_router.infrastructure.monitoring.metrics import MessageMetricsCollector


class TestMessageMetricsThreadSafety:
    """Test thread safety of metrics collection."""

    @pytest.mark.asyncio
    async def test_concurrent_success_failure_updates(self) -> None:
        """Test concurrent updates to success/failure counters."""
        collector = MessageMetricsCollector("test-service")
        iterations = 100

        # Define worker functions
        def sync_success_worker() -> None:
            """Worker that records success synchronously."""
            for _ in range(iterations):
                collector.record_acknowledgment("test_method", "success", 0.1)

        def sync_failure_worker() -> None:
            """Worker that records failure synchronously."""
            for _ in range(iterations):
                collector.record_acknowledgment("test_method", "failure", 0.1)

        async def async_success_worker() -> None:
            """Worker that records success asynchronously."""
            for _ in range(iterations):
                await collector.record_acknowledgment_async("test_method", "success", 0.1)

        async def async_failure_worker() -> None:
            """Worker that records failure asynchronously."""
            for _ in range(iterations):
                await collector.record_acknowledgment_async("test_method", "failure", 0.1)

        # Run sync workers in threads
        with ThreadPoolExecutor(max_workers=4) as executor:
            sync_futures = [
                executor.submit(sync_success_worker),
                executor.submit(sync_success_worker),
                executor.submit(sync_failure_worker),
                executor.submit(sync_failure_worker),
            ]

            # Run async workers concurrently
            async_tasks = [
                asyncio.create_task(async_success_worker()),
                asyncio.create_task(async_success_worker()),
                asyncio.create_task(async_failure_worker()),
                asyncio.create_task(async_failure_worker()),
            ]

            # Wait for all to complete
            for future in sync_futures:
                future.result()

            await asyncio.gather(*async_tasks)

        # Verify final counts
        stats = await collector.get_stats_async()

        # We had 4 success workers and 4 failure workers, each doing 100 iterations
        assert stats["success_count"] == 4 * iterations
        assert stats["failure_count"] == 4 * iterations
        assert stats["success_rate"] == 0.5

    @pytest.mark.asyncio
    async def test_concurrent_timeout_failure_updates(self) -> None:
        """Test concurrent timeout and failure updates."""
        collector = MessageMetricsCollector("test-service")
        iterations = 50

        async def timeout_worker() -> None:
            """Worker that records timeouts."""
            for i in range(iterations):
                await collector.record_acknowledgment_timeout_async("test_method", f"msg-{i}", 30.0)

        async def failure_worker() -> None:
            """Worker that records delivery failures."""
            for i in range(iterations):
                await collector.record_delivery_failure_async(
                    "test_method", "network_error", f"Connection failed {i}"
                )

        # Run workers concurrently
        tasks = []
        for _ in range(3):
            tasks.append(asyncio.create_task(timeout_worker()))
            tasks.append(asyncio.create_task(failure_worker()))

        await asyncio.gather(*tasks)

        # Verify final counts
        stats = await collector.get_stats_async()

        # We had 3 timeout workers and 3 failure workers, each doing 50 iterations
        assert stats["failure_count"] == 6 * iterations
        assert stats["success_rate"] == 0.0  # All failures

    def test_sync_concurrent_updates(self) -> None:
        """Test purely synchronous concurrent updates."""
        collector = MessageMetricsCollector("test-service")
        iterations = 100
        threads = []

        def worker(status: str) -> None:
            """Worker thread."""
            for _ in range(iterations):
                collector.record_acknowledgment("test_method", status, 0.05)

        # Create and start threads
        for _ in range(5):
            t1 = threading.Thread(target=worker, args=("success",))
            t2 = threading.Thread(target=worker, args=("failure",))
            threads.extend([t1, t2])
            t1.start()
            t2.start()

        # Wait for all threads
        for t in threads:
            t.join()

        # Verify final counts
        stats = collector.get_stats()

        # 5 success threads and 5 failure threads, each doing 100 iterations
        assert stats["success_count"] == 5 * iterations
        assert stats["failure_count"] == 5 * iterations
        assert stats["success_rate"] == 0.5

    @pytest.mark.asyncio
    async def test_window_reset_thread_safety(self) -> None:
        """Test that window reset is thread-safe."""
        collector = MessageMetricsCollector("test-service")

        # Manually set window to be about to expire
        from datetime import UTC, datetime, timedelta

        collector._window_start = datetime.now(UTC) - timedelta(seconds=3599)

        # Record many events concurrently, some should trigger reset
        async def worker() -> None:
            """Worker that may trigger window reset."""
            for _ in range(100):
                await collector.record_acknowledgment_async("test_method", "success", 0.01)
                await asyncio.sleep(0.001)  # Small delay to increase chance of race

        # Run multiple workers
        tasks = [asyncio.create_task(worker()) for _ in range(5)]
        await asyncio.gather(*tasks)

        # Stats should be consistent (no partial resets)
        stats = await collector.get_stats_async()

        # After reset, counts should be less than total operations
        # (some operations happened before reset, some after)
        assert stats["success_count"] <= 500
        assert stats["failure_count"] == 0

    @pytest.mark.asyncio
    async def test_get_stats_consistency(self) -> None:
        """Test that get_stats returns consistent data during concurrent updates."""
        collector = MessageMetricsCollector("test-service")
        results = []

        async def stats_reader() -> None:
            """Continuously read stats."""
            for _ in range(50):
                stats = await collector.get_stats_async()
                # Success rate should always be valid
                if stats["success_count"] + stats["failure_count"] > 0:
                    calculated_rate = stats["success_count"] / (
                        stats["success_count"] + stats["failure_count"]
                    )
                    assert abs(stats["success_rate"] - calculated_rate) < 0.001
                results.append(stats)
                await asyncio.sleep(0.001)

        async def updater() -> None:
            """Update metrics concurrently."""
            for i in range(100):
                if i % 2 == 0:
                    await collector.record_acknowledgment_async("test_method", "success", 0.01)
                else:
                    await collector.record_acknowledgment_async("test_method", "failure", 0.01)

        # Run readers and updaters concurrently
        tasks = [
            asyncio.create_task(stats_reader()),
            asyncio.create_task(stats_reader()),
            asyncio.create_task(updater()),
            asyncio.create_task(updater()),
        ]

        await asyncio.gather(*tasks)

        # All results should be internally consistent
        for stats in results:
            total = stats["success_count"] + stats["failure_count"]
            if total > 0:
                expected_rate = stats["success_count"] / total
                assert abs(stats["success_rate"] - expected_rate) < 0.001
