"""Tests for logging infrastructure."""

import json
import logging
from pathlib import Path
from unittest.mock import Mock, patch

from ipc_router.infrastructure.logging import (
    LoggingConfig,
    LogLevel,
    StructuredFormatter,
    get_logger,
    setup_logging,
)


class TestLoggingConfig:
    """Test logging configuration."""

    def test_default_config(self) -> None:
        """Test default logging configuration."""
        config = LoggingConfig()
        assert config.level == LogLevel.INFO
        assert config.json_format is False
        assert config.file_enabled is False
        assert config.file_path is None
        assert config.max_bytes == 10485760  # 10MB
        assert config.backup_count == 5

    def test_custom_config(self) -> None:
        """Test custom logging configuration."""
        config = LoggingConfig(
            level=LogLevel.DEBUG,
            json_format=True,
            file_enabled=True,
            file_path=Path("/var/log/test.log"),
            max_bytes=5242880,  # 5MB
            backup_count=3,
        )
        assert config.level == LogLevel.DEBUG
        assert config.json_format is True
        assert config.file_enabled is True
        assert config.file_path == Path("/var/log/test.log")
        assert config.max_bytes == 5242880
        assert config.backup_count == 3


class TestStructuredFormatter:
    """Test structured JSON formatter."""

    def test_json_formatting(self) -> None:
        """Test JSON log formatting."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test.module",
            level=logging.INFO,
            pathname="test.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        # Add extra fields directly to the record
        record.user_id = "123"
        record.action = "login"

        formatted = formatter.format(record)
        log_data = json.loads(formatted)

        assert log_data["message"] == "Test message"
        assert log_data["level"] == "INFO"
        assert log_data["logger"] == "test.module"
        assert log_data["user_id"] == "123"
        assert log_data["action"] == "login"
        assert "timestamp" in log_data

    def test_exception_formatting(self) -> None:
        """Test exception formatting in JSON."""
        formatter = StructuredFormatter()

        try:
            raise ValueError("Test error")
        except ValueError:
            import sys

            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test.module",
            level=logging.ERROR,
            pathname="test.py",
            lineno=42,
            msg="Error occurred",
            args=(),
            exc_info=exc_info,
        )

        formatted = formatter.format(record)
        log_data = json.loads(formatted)

        assert log_data["message"] == "Error occurred"
        assert log_data["level"] == "ERROR"
        assert "exception" in log_data
        assert "ValueError: Test error" in log_data["exception"]


class TestGetLogger:
    """Test logger factory."""

    def test_get_logger(self) -> None:
        """Test getting a logger instance."""
        logger = get_logger("test.module")
        assert logger.name == "test.module"
        assert isinstance(logger, logging.Logger)

    def test_get_logger_with_different_names(self) -> None:
        """Test getting loggers with different names."""
        logger1 = get_logger("module1")
        logger2 = get_logger("module2")

        assert logger1.name == "module1"
        assert logger2.name == "module2"
        assert logger1 is not logger2


class TestSetupLogging:
    """Test logging setup."""

    def test_setup_basic_logging(self) -> None:
        """Test basic logging setup."""
        # Save original handlers
        root_logger = logging.getLogger()
        original_handlers = root_logger.handlers[:]
        original_level = root_logger.level

        try:
            config = LoggingConfig(level=LogLevel.DEBUG)
            setup_logging(config)

            # Check that logger was configured
            assert root_logger.level == logging.DEBUG
            assert len(root_logger.handlers) > 0
        finally:
            # Restore original handlers
            root_logger.handlers = original_handlers
            root_logger.level = original_level

    @patch("logging.handlers.RotatingFileHandler")
    def test_setup_with_file_handler(self, mock_file_handler: Mock) -> None:
        """Test logging setup with file handler."""
        # Create a proper mock handler
        mock_handler_instance = Mock()
        mock_handler_instance.level = logging.INFO
        mock_file_handler.return_value = mock_handler_instance

        config = LoggingConfig(
            level=LogLevel.INFO,
            file_enabled=True,
            file_path=Path("/tmp/test.log"),
        )

        setup_logging(config)

        mock_file_handler.assert_called_once_with(
            filename=Path("/tmp/test.log"),
            maxBytes=config.max_bytes,
            backupCount=config.backup_count,
            encoding="utf-8",
        )

    def test_log_level_mapping(self) -> None:
        """Test log level enum to logging level mapping."""
        assert LogLevel.DEBUG.value == logging.getLevelName(logging.DEBUG)
        assert LogLevel.INFO.value == logging.getLevelName(logging.INFO)
        assert LogLevel.WARNING.value == logging.getLevelName(logging.WARNING)
        assert LogLevel.ERROR.value == logging.getLevelName(logging.ERROR)
        assert LogLevel.CRITICAL.value == logging.getLevelName(logging.CRITICAL)
