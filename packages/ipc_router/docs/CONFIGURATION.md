# IPC Router Configuration Guide

The IPC Router uses a centralized configuration system that supports environment variables, configuration files, and default values with validation.

## Configuration Structure

The configuration is organized into logical sections:

- **Timeouts**: Request, acknowledgment, and health check timeouts
- **Retries**: Retry attempts, delays, and backoff configuration
- **Cache**: Message cache capacity, memory limits, and TTL settings
- **Resources**: Resource limits, batch sizes, and transfer settings
- **Monitoring**: Health check thresholds and circuit breaker settings
- **Logging**: Log file size and rotation settings
- **Messaging**: NATS subjects and patterns
- **Feature Flags**: Enable/disable optional features

## Using Configuration in Code

### Getting Configuration

```python
from ipc_router.config import get_config

# Get the singleton configuration instance
config = get_config()

# Access configuration values
timeout = config.timeouts.default_request_timeout
cache_capacity = config.cache.message_cache_capacity
```

### Example: Using Configuration in a Service

```python
from ipc_router.config import get_config

class MyService:
    def __init__(self):
        config = get_config()

        # Use configuration values
        self.timeout = config.timeouts.default_request_timeout
        self.max_retries = config.retries.max_attempts
        self.cache_size = config.cache.message_cache_capacity
```

## Environment Variables

All configuration values can be overridden using environment variables with the prefix `AEGIS_IPC_ROUTER_` and using `__` as a nested delimiter.

### Examples

```bash
# Timeout configuration
export AEGIS_IPC_ROUTER_TIMEOUTS__DEFAULT_REQUEST_TIMEOUT=10.0
export AEGIS_IPC_ROUTER_TIMEOUTS__ACKNOWLEDGMENT_TIMEOUT=60.0

# Retry configuration
export AEGIS_IPC_ROUTER_RETRIES__MAX_ATTEMPTS=5
export AEGIS_IPC_ROUTER_RETRIES__INITIAL_DELAY=2.0

# Cache configuration
export AEGIS_IPC_ROUTER_CACHE__MESSAGE_CACHE_CAPACITY=50000
export AEGIS_IPC_ROUTER_CACHE__MESSAGE_CACHE_MAX_MEMORY_MB=500

# Feature flags
export AEGIS_IPC_ROUTER_ENABLE_DISTRIBUTED_LOCKING=true
export AEGIS_IPC_ROUTER_ENABLE_CIRCUIT_BREAKER=false
```

## Configuration File (.env)

You can also use a `.env` file in your project root:

```env
# Timeouts
AEGIS_IPC_ROUTER_TIMEOUTS__DEFAULT_REQUEST_TIMEOUT=10.0
AEGIS_IPC_ROUTER_TIMEOUTS__HEALTH_CHECK_INTERVAL=15.0

# Cache settings
AEGIS_IPC_ROUTER_CACHE__MESSAGE_CACHE_CAPACITY=20000
AEGIS_IPC_ROUTER_CACHE__MESSAGE_CACHE_TTL_HOURS=2.0

# Monitoring
AEGIS_IPC_ROUTER_MONITORING__HEALTH_PERCENTAGE_THRESHOLD=85
AEGIS_IPC_ROUTER_MONITORING__DELIVERY_SUCCESS_RATE_THRESHOLD=0.95
```

## Configuration Reference

### Timeouts

| Setting | Default | Range | Description |
|---------|---------|-------|-------------|
| `timeouts.default_request_timeout` | 5.0 | 0-300 | Default request timeout in seconds |
| `timeouts.acknowledgment_timeout` | 30.0 | 0-300 | Default acknowledgment timeout in seconds |
| `timeouts.health_check_interval` | 10.0 | 0-60 | Health check interval in seconds |
| `timeouts.heartbeat_timeout` | 30.0 | 0-120 | Heartbeat timeout in seconds |
| `timeouts.nats_request_timeout` | 5.0 | 0-60 | NATS request timeout in seconds |
| `timeouts.nats_reconnect_wait` | 2 | 1-30 | NATS reconnect wait time in seconds |

### Retries

| Setting | Default | Range | Description |
|---------|---------|-------|-------------|
| `retries.max_attempts` | 3 | 1-10 | Maximum retry attempts |
| `retries.initial_delay` | 1.0 | 0-10 | Initial retry delay in seconds |
| `retries.max_delay` | 60.0 | 0-300 | Maximum retry delay in seconds |
| `retries.retry_delay` | 5.0 | 0-60 | Fixed retry delay for acknowledgments |
| `retries.nats_max_reconnect_attempts` | 10 | 1-100 | NATS maximum reconnect attempts |

### Cache

| Setting | Default | Range | Description |
|---------|---------|-------|-------------|
| `cache.message_cache_capacity` | 10000 | 100-1000000 | Maximum number of entries in message cache |
| `cache.message_cache_max_memory_mb` | 100 | 1-10000 | Maximum memory usage for message cache in MB |
| `cache.message_cache_ttl_hours` | 1.0 | 0-24 | Default message cache TTL in hours |
| `cache.message_store_ttl_seconds` | 3600 | 60-86400 | Message store TTL in seconds |
| `cache.message_store_cleanup_interval` | 300 | 30-3600 | Message store cleanup interval in seconds |
| `cache.message_store_max_messages` | 10000 | 100-1000000 | Maximum messages in store |
| `cache.deduplication_window_seconds` | 300.0 | 0-3600 | Deduplication window in seconds |

### Resources

| Setting | Default | Range | Description |
|---------|---------|-------|-------------|
| `resources.max_resources_per_instance` | 1000 | 10-100000 | Maximum resources per service instance |
| `resources.resource_batch_size` | 100 | 1-1000 | Default batch size for resource operations |
| `resources.resource_query_limit` | 100 | 1-1000 | Default query result limit |
| `resources.max_transfer_history` | 1000 | 100-10000 | Maximum transfer history entries |
| `resources.max_concurrent_bulk_batches` | 5 | 1-50 | Maximum concurrent bulk operation batches |

### Monitoring

| Setting | Default | Range | Description |
|---------|---------|-------|-------------|
| `monitoring.cache_hit_ratio_threshold` | 0.3 | 0.0-1.0 | Minimum acceptable cache hit ratio |
| `monitoring.delivery_success_rate_threshold` | 0.9 | 0.5-1.0 | Minimum acceptable delivery success rate |
| `monitoring.max_retry_threshold` | 100 | 10-10000 | Maximum acceptable retry count threshold |
| `monitoring.health_percentage_threshold` | 80 | 0-100 | Minimum health percentage for healthy status |
| `monitoring.circuit_breaker_failure_threshold` | 5 | 1-100 | Failures before circuit breaker opens |
| `monitoring.circuit_breaker_recovery_timeout` | 60.0 | 0-600 | Circuit breaker recovery timeout in seconds |

### Logging

| Setting | Default | Range | Description |
|---------|---------|-------|-------------|
| `logging.log_file_max_bytes` | 10485760 | 1MB-100MB | Maximum log file size in bytes |
| `logging.log_backup_count` | 5 | 1-100 | Number of backup log files to keep |

### Feature Flags

| Setting | Default | Description |
|---------|---------|-------------|
| `enable_jetstream` | true | Enable NATS JetStream for persistence |
| `enable_distributed_locking` | false | Enable distributed locking (requires Redis) |
| `enable_circuit_breaker` | true | Enable circuit breaker pattern |
| `enable_auto_cleanup` | true | Enable automatic background cleanup tasks |

## Dynamic Configuration Updates

To reload configuration at runtime:

```python
from ipc_router.config import reload_config

# Reload configuration from environment
new_config = reload_config()
```

## Best Practices

1. **Use Environment Variables for Deployment**: Override defaults using environment variables in production environments.

2. **Validate Configuration Early**: Access configuration during service initialization to catch errors early.

3. **Document Custom Values**: When overriding defaults, document why in your deployment configuration.

4. **Monitor Configuration Changes**: Log configuration values at startup for debugging.

5. **Test with Different Configurations**: Test your services with various configuration values to ensure robustness.

## Example: Complete Configuration

Here's an example of a production configuration using environment variables:

```bash
# Production timeouts
export AEGIS_IPC_ROUTER_TIMEOUTS__DEFAULT_REQUEST_TIMEOUT=10.0
export AEGIS_IPC_ROUTER_TIMEOUTS__ACKNOWLEDGMENT_TIMEOUT=45.0
export AEGIS_IPC_ROUTER_TIMEOUTS__HEALTH_CHECK_INTERVAL=30.0

# Increased cache for production load
export AEGIS_IPC_ROUTER_CACHE__MESSAGE_CACHE_CAPACITY=100000
export AEGIS_IPC_ROUTER_CACHE__MESSAGE_CACHE_MAX_MEMORY_MB=1000
export AEGIS_IPC_ROUTER_CACHE__MESSAGE_CACHE_TTL_HOURS=4.0

# Stricter monitoring thresholds
export AEGIS_IPC_ROUTER_MONITORING__DELIVERY_SUCCESS_RATE_THRESHOLD=0.99
export AEGIS_IPC_ROUTER_MONITORING__HEALTH_PERCENTAGE_THRESHOLD=95

# Enable production features
export AEGIS_IPC_ROUTER_ENABLE_DISTRIBUTED_LOCKING=true
export AEGIS_IPC_ROUTER_ENABLE_CIRCUIT_BREAKER=true

# Adjust retry strategy
export AEGIS_IPC_ROUTER_RETRIES__MAX_ATTEMPTS=5
export AEGIS_IPC_ROUTER_RETRIES__INITIAL_DELAY=2.0
export AEGIS_IPC_ROUTER_RETRIES__MAX_DELAY=120.0
```
