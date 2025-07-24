"""Unit tests for message cache."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from ipc_router.infrastructure.cache import CacheEntry, MessageCache


class TestCacheEntry:
    """Test CacheEntry class."""

    def test_cache_entry_creation(self) -> None:
        """Test creating a cache entry."""
        entry = CacheEntry(
            key="test-key",
            value={"data": "test"},
            ttl=timedelta(minutes=30),
        )

        assert entry.key == "test-key"
        assert entry.value == {"data": "test"}
        assert entry.hit_count == 0
        assert entry.created_at <= datetime.now(UTC)
        assert entry.expires_at == entry.created_at + timedelta(minutes=30)
        assert not entry.is_expired

    def test_cache_entry_expiration(self) -> None:
        """Test cache entry expiration."""
        # Create entry with very short TTL
        entry = CacheEntry(
            key="test-key",
            value="test",
            ttl=timedelta(microseconds=1),
        )

        # Wait a bit to ensure expiration
        import time

        time.sleep(0.001)

        assert entry.is_expired

    def test_cache_entry_access(self) -> None:
        """Test recording access to cache entry."""
        entry = CacheEntry(
            key="test-key",
            value="test",
            ttl=timedelta(hours=1),
        )

        original_last_accessed = entry.last_accessed

        # Record some accesses
        entry.access()
        assert entry.hit_count == 1
        assert entry.last_accessed >= original_last_accessed

        entry.access()
        assert entry.hit_count == 2

    def test_cache_entry_memory_size(self) -> None:
        """Test memory size calculation for cache entries."""
        # Simple string value
        entry = CacheEntry(
            key="test-key",
            value="test",
            ttl=timedelta(hours=1),
        )
        assert entry.memory_size > 0

        # Dictionary value
        dict_entry = CacheEntry(
            key="dict-key",
            value={"name": "test", "data": [1, 2, 3]},
            ttl=timedelta(hours=1),
        )
        assert dict_entry.memory_size > entry.memory_size

        # Large nested structure
        large_value = {"level1": {"level2": {"data": ["item" * 100 for _ in range(10)]}}}
        large_entry = CacheEntry(
            key="large-key",
            value=large_value,
            ttl=timedelta(hours=1),
        )
        assert large_entry.memory_size > dict_entry.memory_size

    def test_cache_entry_deep_size_circular_ref(self) -> None:
        """Test deep size calculation handles circular references."""
        # Create circular reference
        circular_dict: dict[str, Any] = {"key": "value"}
        circular_dict["self"] = circular_dict

        entry = CacheEntry(
            key="circular-key",
            value=circular_dict,
            ttl=timedelta(hours=1),
        )

        # Should not hang or raise, memory size should be reasonable
        assert entry.memory_size > 0
        assert entry.memory_size < 10000  # Reasonable upper bound


class TestMessageCache:
    """Test MessageCache functionality."""

    @pytest.fixture
    def cache(self) -> MessageCache[str]:
        """Create a test cache instance."""
        return MessageCache[str](
            capacity=3,
            max_memory_mb=1,  # 1 MB limit
            default_ttl=timedelta(hours=1),
        )

    @pytest.mark.asyncio
    async def test_put_and_get(self, cache: MessageCache[str]) -> None:
        """Test basic put and get operations."""
        # Put value
        await cache.put("key1", "value1")

        # Get value
        value = await cache.get("key1")
        assert value == "value1"

        # Check stats
        assert cache.size == 1
        assert cache.stats["hits"] == 1
        assert cache.stats["misses"] == 0

    @pytest.mark.asyncio
    async def test_get_missing_key(self, cache: MessageCache[str]) -> None:
        """Test getting a missing key."""
        value = await cache.get("missing")
        assert value is None

        # Check stats
        assert cache.stats["misses"] == 1
        assert cache.stats["hits"] == 0

    @pytest.mark.asyncio
    async def test_lru_eviction(self, cache: MessageCache[str]) -> None:
        """Test LRU eviction when capacity is reached."""
        # Fill cache to capacity
        await cache.put("key1", "value1")
        await cache.put("key2", "value2")
        await cache.put("key3", "value3")

        assert cache.size == 3

        # Access key1 and key2 to make them more recently used
        await cache.get("key1")
        await cache.get("key2")

        # Add new entry, should evict key3 (least recently used)
        await cache.put("key4", "value4")

        assert cache.size == 3
        assert await cache.get("key3") is None  # Evicted
        assert await cache.get("key1") == "value1"  # Still present
        assert await cache.get("key2") == "value2"  # Still present
        assert await cache.get("key4") == "value4"  # New entry

        # Check eviction stats
        assert cache.stats["evictions"] == 1

    @pytest.mark.asyncio
    async def test_ttl_expiration(self) -> None:
        """Test TTL-based expiration."""
        # Create cache with short TTL
        cache = MessageCache[str](
            capacity=10,
            default_ttl=timedelta(milliseconds=10),
        )

        await cache.put("key1", "value1")

        # Value should be present immediately
        assert await cache.get("key1") == "value1"

        # Wait for expiration
        await asyncio.sleep(0.02)

        # Value should be expired
        assert await cache.get("key1") is None
        assert cache.stats["expirations"] == 1

    @pytest.mark.asyncio
    async def test_custom_ttl(self) -> None:
        """Test custom TTL per entry."""
        cache = MessageCache[str](
            capacity=10,
            default_ttl=timedelta(hours=1),
        )

        # Put with custom short TTL
        await cache.put("key1", "value1", ttl=timedelta(milliseconds=10))

        # Put with default TTL
        await cache.put("key2", "value2")

        # Wait for first to expire
        await asyncio.sleep(0.02)

        # First should be expired, second should not
        assert await cache.get("key1") is None
        assert await cache.get("key2") == "value2"

    @pytest.mark.asyncio
    async def test_remove_entry(self, cache: MessageCache[str]) -> None:
        """Test manual removal of entries."""
        await cache.put("key1", "value1")
        await cache.put("key2", "value2")

        # Remove existing entry
        assert await cache.remove("key1") is True
        assert await cache.get("key1") is None
        assert cache.size == 1

        # Try to remove non-existent entry
        assert await cache.remove("key3") is False

    @pytest.mark.asyncio
    async def test_clear_cache(self, cache: MessageCache[str]) -> None:
        """Test clearing the cache."""
        await cache.put("key1", "value1")
        await cache.put("key2", "value2")
        await cache.put("key3", "value3")

        assert cache.size == 3

        await cache.clear()
        assert cache.size == 0
        assert await cache.get("key1") is None

    @pytest.mark.asyncio
    async def test_cleanup_expired(self) -> None:
        """Test cleanup of expired entries."""
        cache = MessageCache[str](capacity=10)

        # Put entries with different TTLs
        await cache.put("key1", "value1", ttl=timedelta(milliseconds=10))
        await cache.put("key2", "value2", ttl=timedelta(milliseconds=10))
        await cache.put("key3", "value3", ttl=timedelta(hours=1))

        # Wait for first two to expire
        await asyncio.sleep(0.02)

        # Cleanup expired
        removed = await cache.cleanup_expired()
        assert removed == 2
        assert cache.size == 1
        assert await cache.get("key3") == "value3"

    @pytest.mark.asyncio
    async def test_eviction_callback(self) -> None:
        """Test eviction callback functionality."""
        evicted_entries = []

        async def eviction_callback(key: str, value: str, reason: str) -> None:
            evicted_entries.append((key, value, reason))

        cache = MessageCache[str](
            capacity=2,
            eviction_callback=eviction_callback,
        )

        # Add entries
        await cache.put("key1", "value1")
        await cache.put("key2", "value2")

        # Trigger LRU eviction
        await cache.put("key3", "value3")

        # Check callback was called
        assert len(evicted_entries) == 1
        assert evicted_entries[0] == ("key1", "value1", "evicted")

        # Clear cache
        await cache.clear()

        # Should have called callback for remaining entries
        assert len(evicted_entries) == 3  # 1 eviction + 2 clears

    @pytest.mark.asyncio
    async def test_get_or_compute(self) -> None:
        """Test get_or_compute functionality."""
        cache = MessageCache[str](capacity=10)
        compute_calls = 0

        async def compute_value() -> str:
            nonlocal compute_calls
            compute_calls += 1
            return "computed_value"

        # First call should compute
        value = await cache.get_or_compute("key1", compute_value)
        assert value == "computed_value"
        assert compute_calls == 1

        # Second call should use cache
        value = await cache.get_or_compute("key1", compute_value)
        assert value == "computed_value"
        assert compute_calls == 1  # Not called again

    @pytest.mark.asyncio
    async def test_concurrent_access(self, cache: MessageCache[str]) -> None:
        """Test thread-safe concurrent access."""

        # Run multiple concurrent operations
        async def put_values() -> None:
            for i in range(10):
                await cache.put(f"key{i}", f"value{i}")

        async def get_values() -> None:
            for i in range(10):
                await cache.get(f"key{i}")

        # Run concurrently
        await asyncio.gather(
            put_values(),
            get_values(),
            put_values(),
            get_values(),
        )

        # Cache should be consistent
        assert cache.size <= cache.capacity

    @pytest.mark.asyncio
    async def test_hit_rate_calculation(self, cache: MessageCache[str]) -> None:
        """Test hit rate calculation."""
        # Initial hit rate should be 0
        assert cache.hit_rate == 0.0

        # Add some values
        await cache.put("key1", "value1")
        await cache.put("key2", "value2")

        # Some hits
        await cache.get("key1")  # Hit
        await cache.get("key1")  # Hit

        # Some misses
        await cache.get("key3")  # Miss
        await cache.get("key4")  # Miss

        # Hit rate should be 2/4 = 0.5
        assert cache.hit_rate == 0.5

    @pytest.mark.asyncio
    async def test_stats(self, cache: MessageCache[str]) -> None:
        """Test cache statistics."""
        # Initial stats
        stats = cache.stats
        assert stats["size"] == 0
        assert stats["capacity"] == 3
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["evictions"] == 0
        assert stats["expirations"] == 0
        assert stats["memory_usage_bytes"] == 0
        assert stats["memory_usage_mb"] == 0.0
        assert stats["memory_usage_percent"] == 0.0
        assert stats["memory_limit_mb"] == 1.0
        assert stats["memory_evictions"] == 0

        # Perform operations
        await cache.put("key1", "value1")
        await cache.get("key1")  # Hit
        await cache.get("missing")  # Miss

        # Updated stats
        stats = cache.stats
        assert stats["size"] == 1
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["memory_usage_bytes"] > 0
        assert stats["memory_usage_mb"] > 0
        assert stats["memory_usage_percent"] > 0

    @pytest.mark.asyncio
    async def test_replace_existing_entry(self, cache: MessageCache[str]) -> None:
        """Test replacing an existing entry."""
        await cache.put("key1", "value1")
        await cache.put("key1", "value2")  # Replace

        assert cache.size == 1
        assert await cache.get("key1") == "value2"

    @pytest.mark.asyncio
    async def test_preheat_cache(self) -> None:
        """Test preheating cache with multiple entries."""
        cache = MessageCache[str](capacity=10)

        # Preheat with multiple entries
        entries = {
            "key1": "value1",
            "key2": "value2",
            "key3": "value3",
        }
        await cache.preheat(entries)

        # All entries should be present
        assert cache.size == 3
        assert await cache.get("key1") == "value1"
        assert await cache.get("key2") == "value2"
        assert await cache.get("key3") == "value3"

    @pytest.mark.asyncio
    async def test_persist_and_restore(self) -> None:
        """Test persisting and restoring cache contents."""
        cache = MessageCache[str](capacity=10)

        # Add some entries
        await cache.put("key1", "value1")
        await cache.put("key2", "value2")
        await cache.put("key3", "value3")

        # Persist cache
        persisted_data = await cache.persist()
        assert len(persisted_data) == 3
        assert persisted_data["key1"] == "value1"

        # Clear and restore
        await cache.clear()
        assert cache.size == 0

        await cache.restore(persisted_data)
        assert cache.size == 3
        assert await cache.get("key1") == "value1"
        assert await cache.get("key2") == "value2"

    @pytest.mark.asyncio
    async def test_persist_excludes_expired(self) -> None:
        """Test that persist excludes expired entries."""
        cache = MessageCache[str](capacity=10)

        # Add entries with different TTLs
        await cache.put("key1", "value1", ttl=timedelta(milliseconds=10))
        await cache.put("key2", "value2", ttl=timedelta(hours=1))

        # Wait for first to expire
        await asyncio.sleep(0.02)

        # Persist should only include non-expired
        persisted_data = await cache.persist()
        assert len(persisted_data) == 1
        assert "key1" not in persisted_data
        assert persisted_data["key2"] == "value2"

    @pytest.mark.asyncio
    async def test_memory_based_eviction(self) -> None:
        """Test eviction based on memory limit."""
        # Create cache with very small memory limit
        cache = MessageCache[str](
            capacity=100,  # High capacity
            max_memory_mb=0.001,  # Very low memory limit (1KB)
        )

        # Add large values that exceed memory limit
        large_value = "x" * 1000  # ~1KB string

        await cache.put("key1", large_value)
        await cache.put("key2", large_value)
        await cache.put("key3", large_value)

        # Cache should have evicted entries due to memory pressure
        assert cache.size < 3  # Some entries evicted
        assert cache.stats["memory_evictions"] > 0
        # Memory should be close to limit (allow small overhead for object metadata)
        assert cache.memory_usage_bytes <= cache._max_memory_bytes * 1.2  # Allow 20% overhead

    @pytest.mark.asyncio
    async def test_memory_tracking_accuracy(self) -> None:
        """Test accuracy of memory tracking."""
        cache = MessageCache[dict[str, Any]](
            capacity=10,
            max_memory_mb=10,
        )

        # Track memory before and after operations
        initial_memory = cache.memory_usage_bytes
        assert initial_memory == 0

        # Add entry
        test_data = {"key": "value", "numbers": list(range(100))}
        await cache.put("test1", test_data)

        memory_after_put = cache.memory_usage_bytes
        assert memory_after_put > initial_memory

        # Remove entry
        await cache.remove("test1")
        assert cache.memory_usage_bytes == 0

    @pytest.mark.asyncio
    async def test_memory_properties(self) -> None:
        """Test memory-related properties."""
        cache = MessageCache[str](
            capacity=10,
            max_memory_mb=2,
        )

        # Add some data
        await cache.put("key1", "value1" * 100)
        await cache.put("key2", "value2" * 100)

        # Test properties
        assert cache.memory_usage_bytes > 0
        assert cache.memory_usage_mb > 0
        assert 0 < cache.memory_usage_percent < 100

        # Memory usage should be consistent
        bytes_usage = cache.memory_usage_bytes
        mb_usage = cache.memory_usage_mb
        assert abs(mb_usage - (bytes_usage / (1024 * 1024))) < 0.001

    @pytest.mark.asyncio
    async def test_eviction_callback_with_memory_pressure(self) -> None:
        """Test eviction callback is called during memory-based eviction."""
        evicted_entries = []

        async def eviction_callback(key: str, value: str, reason: str) -> None:
            evicted_entries.append((key, value, reason))

        cache = MessageCache[str](
            capacity=100,
            max_memory_mb=0.001,  # Very low limit
            eviction_callback=eviction_callback,
        )

        # Add large values
        large_value = "x" * 1000
        await cache.put("key1", large_value + "1")
        await cache.put("key2", large_value + "2")
        await cache.put("key3", large_value + "3")

        # Should have evictions due to memory pressure
        assert len(evicted_entries) > 0
        assert all(reason == "evicted" for _, _, reason in evicted_entries)

    @pytest.mark.asyncio
    async def test_clear_resets_memory_tracking(self) -> None:
        """Test that clear() resets memory tracking."""
        cache = MessageCache[str](capacity=10, max_memory_mb=10)

        # Add entries
        await cache.put("key1", "value1" * 100)
        await cache.put("key2", "value2" * 100)

        assert cache.memory_usage_bytes > 0

        # Clear cache
        await cache.clear()

        # Memory should be reset
        assert cache.memory_usage_bytes == 0
        assert cache.memory_usage_mb == 0
        assert cache.memory_usage_percent == 0

    @pytest.mark.asyncio
    async def test_cleanup_expired_updates_memory(self) -> None:
        """Test that cleanup_expired correctly updates memory tracking."""
        cache = MessageCache[str](capacity=10, max_memory_mb=10)

        # Add entries with short TTL
        await cache.put("key1", "value1" * 100, ttl=timedelta(milliseconds=10))
        await cache.put("key2", "value2" * 100, ttl=timedelta(milliseconds=10))
        await cache.put("key3", "value3" * 100, ttl=timedelta(hours=1))

        initial_memory = cache.memory_usage_bytes
        assert initial_memory > 0

        # Wait for expiration
        await asyncio.sleep(0.02)

        # Cleanup expired
        removed = await cache.cleanup_expired()
        assert removed == 2

        # Memory should be reduced
        assert cache.memory_usage_bytes < initial_memory
        assert cache.memory_usage_bytes > 0  # key3 still present

    @pytest.mark.asyncio
    async def test_complex_object_memory_tracking(self) -> None:
        """Test memory tracking with complex nested objects."""
        cache = MessageCache[dict[str, Any]](capacity=10, max_memory_mb=10)

        # Complex nested object
        complex_obj = {
            "users": [{"id": i, "name": f"User{i}", "data": list(range(100))} for i in range(10)],
            "metadata": {
                "created": datetime.now(UTC).isoformat(),
                "tags": ["tag1", "tag2", "tag3"],
            },
        }

        await cache.put("complex", complex_obj)

        # Memory usage should reflect the complexity
        assert cache.memory_usage_bytes > 1000  # Should be substantial

        # Stats should be consistent
        stats = cache.stats
        assert stats["size"] == 1
        assert stats["memory_usage_bytes"] > 0

    @pytest.mark.asyncio
    async def test_replace_entry_updates_memory(self) -> None:
        """Test that replacing an entry correctly updates memory tracking."""
        cache = MessageCache[str](capacity=10, max_memory_mb=10)

        # Put initial value
        await cache.put("key1", "small")
        initial_memory = cache.memory_usage_bytes

        # Replace with larger value
        await cache.put("key1", "x" * 1000)

        # Memory should increase
        assert cache.memory_usage_bytes > initial_memory
        assert cache.size == 1  # Still only one entry

    @pytest.mark.asyncio
    async def test_memory_limit_prevents_put(self) -> None:
        """Test that memory limit prevents putting new entries."""
        cache = MessageCache[str](
            capacity=100,
            max_memory_mb=0.0001,  # Extremely small limit
        )

        # Try to put a value that exceeds memory limit
        large_value = "x" * 10000
        await cache.put("key1", large_value)

        # Cache might be empty if value was too large
        if cache.size > 0:
            # If it was added, memory should still be within limits
            assert cache.memory_usage_bytes <= cache._max_memory_bytes

    @pytest.mark.asyncio
    async def test_concurrent_memory_tracking(self) -> None:
        """Test memory tracking under concurrent operations."""
        cache = MessageCache[str](capacity=100, max_memory_mb=10)

        async def add_entries(prefix: str, count: int) -> None:
            for i in range(count):
                await cache.put(f"{prefix}-{i}", f"value-{i}" * 10)

        async def remove_entries(prefix: str, count: int) -> None:
            for i in range(count):
                await cache.remove(f"{prefix}-{i}")

        # Run concurrent operations
        await asyncio.gather(
            add_entries("set1", 20),
            add_entries("set2", 20),
            asyncio.sleep(0.01),  # Small delay
            remove_entries("set1", 10),
            remove_entries("set2", 10),
        )

        # Memory tracking should be consistent
        stats = cache.stats
        assert stats["memory_usage_bytes"] >= 0
        assert stats["size"] * 50 <= stats["memory_usage_bytes"]  # Rough estimate

    @pytest.mark.asyncio
    async def test_edge_cases(self) -> None:
        """Test edge cases for cache operations."""
        cache = MessageCache[Any](capacity=5, max_memory_mb=10)

        # Test with None value
        await cache.put("none-key", None)
        assert await cache.get("none-key") is None

        # Test with empty string
        await cache.put("empty", "")
        assert await cache.get("empty") == ""

        # Test with various types
        await cache.put("int", 42)
        await cache.put("float", 3.14)
        await cache.put("list", [1, 2, 3])
        await cache.put("tuple", (1, 2, 3))

        assert await cache.get("int") == 42
        assert await cache.get("float") == 3.14
        assert await cache.get("list") == [1, 2, 3]
        assert await cache.get("tuple") == (1, 2, 3)

    @pytest.mark.asyncio
    async def test_custom_object_with_dict(self) -> None:
        """Test caching custom objects with __dict__."""

        class CustomObject:
            def __init__(self, name: str, data: list[int]) -> None:
                self.name = name
                self.data = data

        cache = MessageCache[CustomObject](capacity=5, max_memory_mb=10)

        obj = CustomObject("test", [1, 2, 3, 4, 5])
        await cache.put("custom", obj)

        retrieved = await cache.get("custom")
        assert retrieved is not None
        assert retrieved.name == "test"
        assert retrieved.data == [1, 2, 3, 4, 5]

        # Memory should include object overhead
        assert cache.memory_usage_bytes > 100
