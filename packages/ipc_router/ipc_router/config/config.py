"""Centralized configuration management for IPC Router.

This module provides a centralized configuration system that supports:
- Environment variable overrides
- Default values with validation
- Type safety using Pydantic
- Hierarchical configuration structure
"""

from __future__ import annotations

from datetime import timedelta
from functools import lru_cache

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class TimeoutConfig(BaseModel):
    """Timeout-related configuration."""

    # Request timeouts
    default_request_timeout: float = Field(
        default=5.0, gt=0, le=300, description="Default request timeout in seconds"
    )

    # Acknowledgment timeouts
    acknowledgment_timeout: float = Field(
        default=30.0, gt=0, le=300, description="Default acknowledgment timeout in seconds"
    )

    # Health check timeouts
    health_check_interval: float = Field(
        default=10.0, gt=0, le=60, description="Health check interval in seconds"
    )

    heartbeat_timeout: float = Field(
        default=30.0, gt=0, le=120, description="Heartbeat timeout in seconds"
    )

    # NATS timeouts
    nats_request_timeout: float = Field(
        default=5.0, gt=0, le=60, description="NATS request timeout in seconds"
    )

    nats_reconnect_wait: int = Field(
        default=2, ge=1, le=30, description="NATS reconnect wait time in seconds"
    )


class RetryConfig(BaseModel):
    """Retry-related configuration."""

    max_attempts: int = Field(default=3, ge=1, le=10, description="Maximum retry attempts")

    initial_delay: float = Field(
        default=1.0, gt=0, le=10, description="Initial retry delay in seconds"
    )

    max_delay: float = Field(
        default=60.0, gt=0, le=300, description="Maximum retry delay in seconds"
    )

    retry_delay: float = Field(
        default=5.0, gt=0, le=60, description="Fixed retry delay for acknowledgments"
    )

    # NATS specific
    nats_max_reconnect_attempts: int = Field(
        default=10, ge=1, le=100, description="NATS maximum reconnect attempts"
    )


class CacheConfig(BaseModel):
    """Cache-related configuration."""

    # Message cache
    message_cache_capacity: int = Field(
        default=10000, ge=100, le=1000000, description="Maximum number of entries in message cache"
    )

    message_cache_max_memory_mb: int = Field(
        default=100, ge=1, le=10000, description="Maximum memory usage for message cache in MB"
    )

    message_cache_ttl_hours: float = Field(
        default=1.0, gt=0, le=24, description="Default message cache TTL in hours"
    )

    # Message store
    message_store_ttl_seconds: int = Field(
        default=3600, ge=60, le=86400, description="Message store TTL in seconds"
    )

    message_store_cleanup_interval: int = Field(
        default=300, ge=30, le=3600, description="Message store cleanup interval in seconds"
    )

    message_store_max_messages: int = Field(
        default=10000, ge=100, le=1000000, description="Maximum messages in store"
    )

    # Deduplication
    deduplication_window_seconds: float = Field(
        default=300.0, gt=0, le=3600, description="Deduplication window in seconds"
    )


class ResourceConfig(BaseModel):
    """Resource management configuration."""

    max_resources_per_instance: int = Field(
        default=1000, ge=10, le=100000, description="Maximum resources per service instance"
    )

    resource_batch_size: int = Field(
        default=100, ge=1, le=1000, description="Default batch size for resource operations"
    )

    resource_query_limit: int = Field(
        default=100, ge=1, le=1000, description="Default query result limit"
    )

    max_transfer_history: int = Field(
        default=1000, ge=100, le=10000, description="Maximum transfer history entries"
    )

    max_concurrent_bulk_batches: int = Field(
        default=5, ge=1, le=50, description="Maximum concurrent bulk operation batches"
    )


class MonitoringConfig(BaseModel):
    """Monitoring and health check configuration."""

    cache_hit_ratio_threshold: float = Field(
        default=0.3, ge=0.0, le=1.0, description="Minimum acceptable cache hit ratio"
    )

    delivery_success_rate_threshold: float = Field(
        default=0.9, ge=0.5, le=1.0, description="Minimum acceptable delivery success rate"
    )

    max_retry_threshold: int = Field(
        default=100, ge=10, le=10000, description="Maximum acceptable retry count threshold"
    )

    health_percentage_threshold: int = Field(
        default=80, ge=0, le=100, description="Minimum health percentage for healthy status"
    )

    # Circuit breaker
    circuit_breaker_failure_threshold: int = Field(
        default=5, ge=1, le=100, description="Failures before circuit breaker opens"
    )

    circuit_breaker_recovery_timeout: float = Field(
        default=60.0, gt=0, le=600, description="Circuit breaker recovery timeout in seconds"
    )


class LoggingConfig(BaseModel):
    """Logging configuration."""

    log_file_max_bytes: int = Field(
        default=10_485_760,  # 10MB
        ge=1_048_576,  # 1MB
        le=104_857_600,  # 100MB
        description="Maximum log file size in bytes",
    )

    log_backup_count: int = Field(
        default=5, ge=1, le=100, description="Number of backup log files to keep"
    )


class MessagingConfig(BaseModel):
    """Messaging subjects and patterns configuration."""

    # Base subjects
    route_request_subject: str = Field(
        default="ipc.route.request", description="Subject for route requests"
    )

    service_register_subject: str = Field(
        default="ipc.service.register", description="Subject for service registration"
    )

    service_heartbeat_subject: str = Field(
        default="ipc.service.heartbeat", description="Subject for service heartbeats"
    )

    resource_register_subject: str = Field(
        default="ipc.resource.register", description="Subject for resource registration"
    )

    resource_release_subject: str = Field(
        default="ipc.resource.release", description="Subject for resource release"
    )

    bulk_register_subject: str = Field(
        default="ipc.resource.bulk_register", description="Subject for bulk resource registration"
    )

    bulk_release_subject: str = Field(
        default="ipc.resource.bulk_release", description="Subject for bulk resource release"
    )

    ack_response_subject: str = Field(
        default="ipc.ack.response", description="Subject for acknowledgment responses"
    )

    # Subject patterns
    ack_subject_pattern: str = Field(
        default="ipc.ack.{message_id}", description="Pattern for acknowledgment subjects"
    )


class RouterConfig(BaseSettings):
    """Main router configuration.

    All configuration values can be overridden using environment variables
    with the prefix AEGIS_IPC_ROUTER_ (e.g., AEGIS_IPC_ROUTER_TIMEOUTS__DEFAULT_REQUEST_TIMEOUT).
    """

    model_config = SettingsConfigDict(
        env_prefix="AEGIS_IPC_ROUTER_",
        env_nested_delimiter="__",
        case_sensitive=False,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Sub-configurations
    timeouts: TimeoutConfig = Field(default_factory=TimeoutConfig)
    retries: RetryConfig = Field(default_factory=RetryConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    resources: ResourceConfig = Field(default_factory=ResourceConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    messaging: MessagingConfig = Field(default_factory=MessagingConfig)

    # Feature flags
    enable_jetstream: bool = Field(
        default=True, description="Enable NATS JetStream for persistence"
    )

    enable_distributed_locking: bool = Field(
        default=False, description="Enable distributed locking (requires Redis)"
    )

    enable_circuit_breaker: bool = Field(default=True, description="Enable circuit breaker pattern")

    enable_auto_cleanup: bool = Field(
        default=True, description="Enable automatic background cleanup tasks"
    )

    # Computed properties
    @property
    def message_cache_ttl(self) -> timedelta:
        """Get message cache TTL as timedelta."""
        return timedelta(hours=self.cache.message_cache_ttl_hours)

    @property
    def message_store_ttl(self) -> timedelta:
        """Get message store TTL as timedelta."""
        return timedelta(seconds=self.cache.message_store_ttl_seconds)

    @property
    def deduplication_window(self) -> timedelta:
        """Get deduplication window as timedelta."""
        return timedelta(seconds=self.cache.deduplication_window_seconds)

    def get_ack_subject(self, message_id: str) -> str:
        """Get acknowledgment subject for a message ID."""
        return self.messaging.ack_subject_pattern.format(message_id=message_id)


@lru_cache(maxsize=1)
def get_config() -> RouterConfig:
    """Get the singleton configuration instance.

    This function returns a cached configuration instance that reads from
    environment variables and configuration files.

    Returns:
        RouterConfig: The configuration instance
    """
    return RouterConfig()


def reload_config() -> RouterConfig:
    """Reload configuration from environment.

    This clears the cache and creates a new configuration instance.

    Returns:
        RouterConfig: The new configuration instance
    """
    get_config.cache_clear()
    return get_config()
