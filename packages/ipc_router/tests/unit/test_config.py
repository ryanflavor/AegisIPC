"""Unit tests for configuration management."""

from __future__ import annotations

import os
from datetime import timedelta
from unittest.mock import patch

import pytest
from ipc_router.config import RouterConfig, get_config, reload_config


class TestRouterConfig:
    """Test router configuration functionality."""

    def test_default_configuration(self) -> None:
        """Test that default configuration values are loaded correctly."""
        config = RouterConfig()

        # Test timeout defaults
        assert config.timeouts.default_request_timeout == 5.0
        assert config.timeouts.acknowledgment_timeout == 30.0
        assert config.timeouts.health_check_interval == 10.0
        assert config.timeouts.heartbeat_timeout == 30.0
        assert config.timeouts.nats_request_timeout == 5.0
        assert config.timeouts.nats_reconnect_wait == 2

        # Test retry defaults
        assert config.retries.max_attempts == 3
        assert config.retries.initial_delay == 1.0
        assert config.retries.max_delay == 60.0
        assert config.retries.retry_delay == 5.0
        assert config.retries.nats_max_reconnect_attempts == 10

        # Test cache defaults
        assert config.cache.message_cache_capacity == 10000
        assert config.cache.message_cache_max_memory_mb == 100
        assert config.cache.message_cache_ttl_hours == 1.0
        assert config.cache.message_store_ttl_seconds == 3600
        assert config.cache.message_store_cleanup_interval == 300
        assert config.cache.message_store_max_messages == 10000
        assert config.cache.deduplication_window_seconds == 300.0

        # Test resource defaults
        assert config.resources.max_resources_per_instance == 1000
        assert config.resources.resource_batch_size == 100
        assert config.resources.resource_query_limit == 100
        assert config.resources.max_transfer_history == 1000
        assert config.resources.max_concurrent_bulk_batches == 5

        # Test monitoring defaults
        assert config.monitoring.cache_hit_ratio_threshold == 0.3
        assert config.monitoring.delivery_success_rate_threshold == 0.9
        assert config.monitoring.max_retry_threshold == 100
        assert config.monitoring.health_percentage_threshold == 80
        assert config.monitoring.circuit_breaker_failure_threshold == 5
        assert config.monitoring.circuit_breaker_recovery_timeout == 60.0

        # Test logging defaults
        assert config.logging.log_file_max_bytes == 10_485_760
        assert config.logging.log_backup_count == 5

        # Test messaging defaults
        assert config.messaging.route_request_subject == "ipc.route.request"
        assert config.messaging.service_register_subject == "ipc.service.register"
        assert config.messaging.service_heartbeat_subject == "ipc.service.heartbeat"
        assert config.messaging.resource_register_subject == "ipc.resource.register"
        assert config.messaging.resource_release_subject == "ipc.resource.release"
        assert config.messaging.bulk_register_subject == "ipc.resource.bulk_register"
        assert config.messaging.bulk_release_subject == "ipc.resource.bulk_release"
        assert config.messaging.ack_response_subject == "ipc.ack.response"
        assert config.messaging.ack_subject_pattern == "ipc.ack.{message_id}"

        # Test feature flags
        assert config.enable_jetstream is True
        assert config.enable_distributed_locking is False
        assert config.enable_circuit_breaker is True
        assert config.enable_auto_cleanup is True

    def test_environment_variable_override(self) -> None:
        """Test that environment variables override default values."""
        env_vars = {
            "AEGIS_IPC_ROUTER_TIMEOUTS__DEFAULT_REQUEST_TIMEOUT": "10.0",
            "AEGIS_IPC_ROUTER_RETRIES__MAX_ATTEMPTS": "5",
            "AEGIS_IPC_ROUTER_CACHE__MESSAGE_CACHE_CAPACITY": "50000",
            "AEGIS_IPC_ROUTER_RESOURCES__MAX_RESOURCES_PER_INSTANCE": "5000",
            "AEGIS_IPC_ROUTER_MONITORING__HEALTH_PERCENTAGE_THRESHOLD": "90",
            "AEGIS_IPC_ROUTER_MESSAGING__ROUTE_REQUEST_SUBJECT": "custom.route.request",
            "AEGIS_IPC_ROUTER_ENABLE_DISTRIBUTED_LOCKING": "true",
            "AEGIS_IPC_ROUTER_ENABLE_CIRCUIT_BREAKER": "false",
        }

        with patch.dict(os.environ, env_vars, clear=False):
            config = RouterConfig()

            # Verify overrides
            assert config.timeouts.default_request_timeout == 10.0
            assert config.retries.max_attempts == 5
            assert config.cache.message_cache_capacity == 50000
            assert config.resources.max_resources_per_instance == 5000
            assert config.monitoring.health_percentage_threshold == 90
            assert config.messaging.route_request_subject == "custom.route.request"
            assert config.enable_distributed_locking is True
            assert config.enable_circuit_breaker is False

    def test_computed_properties(self) -> None:
        """Test computed properties return correct values."""
        config = RouterConfig()

        # Test timedelta conversions
        assert config.message_cache_ttl == timedelta(hours=1.0)
        assert config.message_store_ttl == timedelta(seconds=3600)
        assert config.deduplication_window == timedelta(seconds=300)

    def test_get_ack_subject(self) -> None:
        """Test acknowledgment subject formatting."""
        config = RouterConfig()

        # Test with default pattern
        assert config.get_ack_subject("test-123") == "ipc.ack.test-123"
        assert config.get_ack_subject("msg-456") == "ipc.ack.msg-456"

        # Test with custom pattern
        with patch.dict(
            os.environ,
            {"AEGIS_IPC_ROUTER_MESSAGING__ACK_SUBJECT_PATTERN": "custom.ack.{message_id}"},
            clear=False,
        ):
            config = RouterConfig()
            assert config.get_ack_subject("test-123") == "custom.ack.test-123"

    def test_validation_constraints(self) -> None:
        """Test that validation constraints are enforced."""
        # Test timeout constraints
        with pytest.raises(ValueError):
            RouterConfig(timeouts={"default_request_timeout": -1})

        with pytest.raises(ValueError):
            RouterConfig(timeouts={"default_request_timeout": 301})

        # Test retry constraints
        with pytest.raises(ValueError):
            RouterConfig(retries={"max_attempts": 0})

        with pytest.raises(ValueError):
            RouterConfig(retries={"max_attempts": 11})

        # Test cache constraints
        with pytest.raises(ValueError):
            RouterConfig(cache={"message_cache_capacity": 50})

        with pytest.raises(ValueError):
            RouterConfig(cache={"message_cache_capacity": 2000000})

        # Test monitoring constraints
        with pytest.raises(ValueError):
            RouterConfig(monitoring={"cache_hit_ratio_threshold": -0.1})

        with pytest.raises(ValueError):
            RouterConfig(monitoring={"cache_hit_ratio_threshold": 1.1})

    def test_get_config_singleton(self) -> None:
        """Test that get_config returns a singleton instance."""
        config1 = get_config()
        config2 = get_config()

        # Should be the same instance
        assert config1 is config2

    def test_reload_config(self) -> None:
        """Test that reload_config creates a new instance."""
        # Get initial config
        config1 = get_config()

        # Modify environment
        with patch.dict(
            os.environ, {"AEGIS_IPC_ROUTER_TIMEOUTS__DEFAULT_REQUEST_TIMEOUT": "15.0"}, clear=False
        ):
            # Reload config
            config2 = reload_config()

            # Should be different instances
            assert config1 is not config2

            # New config should have updated value
            assert config2.timeouts.default_request_timeout == 15.0

            # get_config should now return the new instance
            config3 = get_config()
            assert config3 is config2

    def test_nested_configuration_access(self) -> None:
        """Test accessing nested configuration values."""
        config = RouterConfig()

        # Test nested access
        assert isinstance(config.timeouts, object)
        assert hasattr(config.timeouts, "default_request_timeout")

        assert isinstance(config.retries, object)
        assert hasattr(config.retries, "max_attempts")

        assert isinstance(config.cache, object)
        assert hasattr(config.cache, "message_cache_capacity")

    def test_env_file_loading(self) -> None:
        """Test loading configuration from .env file."""
        # Create a temporary .env file
        env_content = """
AEGIS_IPC_ROUTER_TIMEOUTS__DEFAULT_REQUEST_TIMEOUT=20.0
AEGIS_IPC_ROUTER_CACHE__MESSAGE_CACHE_CAPACITY=25000
AEGIS_IPC_ROUTER_ENABLE_DISTRIBUTED_LOCKING=true
"""

        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write(env_content)
            env_file_path = f.name

        try:
            # Load config with env file
            config = RouterConfig(_env_file=env_file_path)

            # Verify values from env file
            assert config.timeouts.default_request_timeout == 20.0
            assert config.cache.message_cache_capacity == 25000
            assert config.enable_distributed_locking is True
        finally:
            # Clean up
            os.unlink(env_file_path)

    def test_case_insensitive_env_vars(self) -> None:
        """Test that environment variables are case-insensitive."""
        env_vars = {
            "aegis_ipc_router_timeouts__default_request_timeout": "12.0",
            "AEGIS_IPC_ROUTER_RETRIES__MAX_ATTEMPTS": "4",
            "Aegis_Ipc_Router_Cache__Message_Cache_Capacity": "30000",
        }

        with patch.dict(os.environ, env_vars, clear=False):
            config = RouterConfig()

            # All should work regardless of case
            assert config.timeouts.default_request_timeout == 12.0
            assert config.retries.max_attempts == 4
            assert config.cache.message_cache_capacity == 30000

    def test_extra_fields_ignored(self) -> None:
        """Test that extra fields in environment are ignored."""
        env_vars = {
            "AEGIS_IPC_ROUTER_UNKNOWN_FIELD": "value",
            "AEGIS_IPC_ROUTER_TIMEOUTS__UNKNOWN_TIMEOUT": "10",
        }

        with patch.dict(os.environ, env_vars, clear=False):
            # Should not raise an error
            config = RouterConfig()

            # Should still have default values
            assert config.timeouts.default_request_timeout == 5.0
