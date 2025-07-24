"""Message cache implementation for deduplication."""

from __future__ import annotations

import asyncio
import sys
from collections import OrderedDict
from datetime import UTC, datetime, timedelta
from typing import Any, Generic, TypeVar

from ipc_router.config import get_config
from ipc_router.infrastructure.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


class CacheEntry(Generic[T]):
    """Represents a cache entry with value and metadata."""

    def __init__(self, key: str, value: T, ttl: timedelta) -> None:
        """Initialize cache entry.

        Args:
            key: Cache key
            value: Cached value
            ttl: Time to live
        """
        self.key = key
        self.value = value
        self.created_at = datetime.now(UTC)
        self.expires_at = self.created_at + ttl
        self.hit_count = 0
        self.last_accessed = self.created_at
        # Track memory size of the entry
        self.memory_size = self._calculate_size()

    @property
    def is_expired(self) -> bool:
        """Check if entry is expired."""
        return datetime.now(UTC) >= self.expires_at

    def access(self) -> None:
        """Record an access to this entry."""
        self.hit_count += 1
        self.last_accessed = datetime.now(UTC)

    def _calculate_size(self) -> int:
        """Calculate approximate memory size of the entry.

        Returns:
            Size in bytes
        """
        # Base size of the entry object
        size = sys.getsizeof(self)

        # Add size of the key
        size += sys.getsizeof(self.key)

        # Add size of the value (recursive for containers)
        size += self._get_deep_size(self.value)

        return size

    def _get_deep_size(self, obj: Any, seen: set[int] | None = None) -> int:
        """Get the deep size of an object, handling circular references."""
        if seen is None:
            seen = set()

        obj_id = id(obj)
        if obj_id in seen:
            return 0

        seen.add(obj_id)
        size = sys.getsizeof(obj)

        # Handle common container types
        if isinstance(obj, dict):
            size += sum(
                self._get_deep_size(k, seen) + self._get_deep_size(v, seen) for k, v in obj.items()
            )
        elif isinstance(obj, list | tuple | set | frozenset):
            size += sum(self._get_deep_size(item, seen) for item in obj)
        elif hasattr(obj, "__dict__"):
            size += self._get_deep_size(obj.__dict__, seen)

        return size


class MessageCache(Generic[T]):
    """Thread-safe LRU cache for message deduplication.

    This cache provides:
    - LRU eviction when capacity is reached
    - TTL-based expiration
    - Thread-safe operations using asyncio locks
    - Hit/miss statistics
    - Optional persistence hooks
    """

    def __init__(
        self,
        capacity: int | None = None,
        max_memory_mb: int | None = None,
        default_ttl: timedelta | None = None,
        eviction_callback: Any | None = None,
    ) -> None:
        """Initialize the message cache.

        Args:
            capacity: Maximum number of entries (defaults to config value)
            max_memory_mb: Maximum memory usage in megabytes (defaults to config value)
            default_ttl: Default time to live for entries (defaults to config value)
            eviction_callback: Optional async callback when entries are evicted
        """
        # Get configuration
        config = get_config()

        # Use provided values or fall back to configuration
        self._capacity = capacity if capacity is not None else config.cache.message_cache_capacity
        self._max_memory_bytes = (
            max_memory_mb * 1024 * 1024
            if max_memory_mb is not None
            else config.cache.message_cache_max_memory_mb * 1024 * 1024
        )
        self._default_ttl = default_ttl if default_ttl is not None else config.message_cache_ttl
        self._eviction_callback = eviction_callback

        # Use OrderedDict for LRU behavior
        self._cache: OrderedDict[str, CacheEntry[T]] = OrderedDict()
        self._lock = asyncio.Lock()

        # Track total memory usage
        self._total_memory_bytes = 0

        # Statistics
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._expirations = 0
        self._memory_evictions = 0

    async def get(self, key: str) -> T | None:
        """Get value from cache.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found/expired
        """
        async with self._lock:
            entry = self._cache.get(key)

            if entry is None:
                self._misses += 1
                logger.debug(
                    "Cache miss",
                    extra={"key": key, "hit_rate": self.hit_rate},
                )
                return None

            # Check expiration
            if entry.is_expired:
                await self._remove_entry(key, "expired")
                self._misses += 1
                self._expirations += 1
                logger.debug(
                    "Cache entry expired",
                    extra={
                        "key": key,
                        "created_at": entry.created_at.isoformat(),
                        "expires_at": entry.expires_at.isoformat(),
                        "memory_size_bytes": entry.memory_size,
                    },
                )
                return None

            # Move to end (most recently used)
            self._cache.move_to_end(key)
            entry.access()
            self._hits += 1

            logger.debug(
                "Cache hit",
                extra={
                    "key": key,
                    "hit_count": entry.hit_count,
                    "hit_rate": self.hit_rate,
                    "memory_size_bytes": entry.memory_size,
                },
            )

            return entry.value

    async def put(
        self,
        key: str,
        value: T,
        ttl: timedelta | None = None,
    ) -> None:
        """Put value in cache.

        Args:
            key: Cache key
            value: Value to cache
            ttl: Optional custom TTL
        """
        async with self._lock:
            # Remove existing entry if present
            if key in self._cache:
                await self._remove_entry(key, "replaced")

            # Add new entry
            entry = CacheEntry(key, value, ttl or self._default_ttl)

            # Check capacity and memory limits, evict if necessary
            while (
                len(self._cache) >= self._capacity
                or self._total_memory_bytes + entry.memory_size > self._max_memory_bytes
            ):
                if self._total_memory_bytes + entry.memory_size > self._max_memory_bytes:
                    await self._evict_lru(memory_pressure=True)
                else:
                    await self._evict_lru(memory_pressure=False)

                # Break if cache is empty to avoid infinite loop
                if not self._cache:
                    break

            # Add to cache and update memory tracking
            self._cache[key] = entry
            self._total_memory_bytes += entry.memory_size

            logger.debug(
                "Cache put",
                extra={
                    "key": key,
                    "ttl_seconds": (ttl or self._default_ttl).total_seconds(),
                    "cache_size": len(self._cache),
                    "entry_memory_bytes": entry.memory_size,
                    "total_memory_bytes": self._total_memory_bytes,
                    "memory_usage_pct": (self._total_memory_bytes / self._max_memory_bytes) * 100,
                },
            )

    async def remove(self, key: str) -> bool:
        """Remove entry from cache.

        Args:
            key: Cache key

        Returns:
            True if entry was removed, False if not found
        """
        async with self._lock:
            if key in self._cache:
                await self._remove_entry(key, "manual")
                return True
            return False

    async def clear(self) -> None:
        """Clear all entries from cache."""
        async with self._lock:
            # Call eviction callback for all entries if configured
            if self._eviction_callback:
                for entry in self._cache.values():
                    await self._eviction_callback(entry.key, entry.value, "clear")

            self._cache.clear()
            self._total_memory_bytes = 0
            logger.info("Cache cleared", extra={"entries_cleared": len(self._cache)})

    async def cleanup_expired(self) -> int:
        """Remove all expired entries.

        Returns:
            Number of entries removed
        """
        async with self._lock:
            expired_keys = [key for key, entry in self._cache.items() if entry.is_expired]
            memory_freed = 0

            for key in expired_keys:
                entry = self._cache.get(key)
                if entry:
                    memory_freed += entry.memory_size
                await self._remove_entry(key, "expired")
                self._expirations += 1

            if expired_keys:
                logger.info(
                    "Cleaned up expired entries",
                    extra={
                        "count": len(expired_keys),
                        "memory_freed_bytes": memory_freed,
                        "memory_freed_mb": memory_freed / (1024 * 1024),
                    },
                )

            return len(expired_keys)

    async def _evict_lru(self, memory_pressure: bool = False) -> None:
        """Evict least recently used entry.

        Args:
            memory_pressure: True if evicting due to memory limit
        """
        if not self._cache:
            return

        # Get oldest entry (first in OrderedDict)
        key = next(iter(self._cache))
        await self._remove_entry(key, "evicted")
        self._evictions += 1
        if memory_pressure:
            self._memory_evictions += 1

    async def _remove_entry(self, key: str, reason: str) -> None:
        """Remove entry and call eviction callback.

        Args:
            key: Cache key
            reason: Reason for removal
        """
        entry = self._cache.pop(key, None)
        if entry:
            # Update memory tracking
            self._total_memory_bytes -= entry.memory_size

            if self._eviction_callback:
                await self._eviction_callback(key, entry.value, reason)

            logger.debug(
                "Cache entry removed",
                extra={
                    "key": key,
                    "reason": reason,
                    "memory_freed_bytes": entry.memory_size,
                    "total_memory_bytes": self._total_memory_bytes,
                },
            )

    @property
    def size(self) -> int:
        """Get current cache size."""
        return len(self._cache)

    @property
    def capacity(self) -> int:
        """Get cache capacity."""
        return self._capacity

    @property
    def hit_rate(self) -> float:
        """Get cache hit rate."""
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0.0

    @property
    def memory_usage_bytes(self) -> int:
        """Get current memory usage in bytes."""
        return self._total_memory_bytes

    @property
    def memory_usage_mb(self) -> float:
        """Get current memory usage in megabytes."""
        return self._total_memory_bytes / (1024 * 1024)

    @property
    def memory_usage_percent(self) -> float:
        """Get memory usage as percentage of max."""
        return (self._total_memory_bytes / self._max_memory_bytes) * 100

    @property
    def stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        return {
            "size": self.size,
            "capacity": self.capacity,
            "memory_usage_bytes": self._total_memory_bytes,
            "memory_usage_mb": self.memory_usage_mb,
            "memory_usage_percent": self.memory_usage_percent,
            "memory_limit_mb": self._max_memory_bytes / (1024 * 1024),
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": self.hit_rate,
            "evictions": self._evictions,
            "memory_evictions": self._memory_evictions,
            "expirations": self._expirations,
        }

    async def get_or_compute(
        self,
        key: str,
        compute_fn: Any,
        ttl: timedelta | None = None,
    ) -> T:
        """Get value from cache or compute if not present.

        This method provides a convenient way to handle cache misses
        by automatically computing and storing the value.

        Args:
            key: Cache key
            compute_fn: Async function to compute value if not in cache
            ttl: Optional custom TTL

        Returns:
            Cached or computed value
        """
        # Try to get from cache first
        value = await self.get(key)
        if value is not None:
            return value

        # Compute value
        value = await compute_fn()

        # Store in cache
        await self.put(key, value, ttl)

        return value

    async def preheat(self, entries: dict[str, T], ttl: timedelta | None = None) -> None:
        """Preheat cache with multiple entries.

        This is useful for warming up the cache with frequently accessed data
        on startup or after a cache clear.

        Args:
            entries: Dictionary of key-value pairs to cache
            ttl: Optional TTL for all entries
        """
        for key, value in entries.items():
            await self.put(key, value, ttl)

        logger.info(
            "Cache preheated",
            extra={"entries_count": len(entries)},
        )

    async def persist(self) -> dict[str, T]:
        """Export cache contents for persistence.

        Returns:
            Dictionary of current cache contents
        """
        async with self._lock:
            return {key: entry.value for key, entry in self._cache.items() if not entry.is_expired}

    async def restore(self, data: dict[str, T], ttl: timedelta | None = None) -> None:
        """Restore cache from persisted data.

        Args:
            data: Dictionary of key-value pairs to restore
            ttl: Optional TTL for restored entries
        """
        await self.clear()
        await self.preheat(data, ttl)

        logger.info(
            "Cache restored",
            extra={"entries_count": len(data)},
        )
