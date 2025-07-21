"""Centralized logging configuration for AegisIPC."""

import logging
import logging.handlers
import sys
from datetime import UTC
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field, field_validator


class LogLevel(str, Enum):
    """Valid log levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class LoggingConfig(BaseModel):
    """Logging configuration model."""

    level: LogLevel = Field(default=LogLevel.INFO, description="Global log level")
    format: str = Field(
        default="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        description="Log message format",
    )
    date_format: str = Field(
        default="%Y-%m-%d %H:%M:%S",
        description="Date format for log messages",
    )
    console_enabled: bool = Field(default=True, description="Enable console logging")
    file_enabled: bool = Field(default=False, description="Enable file logging")
    file_path: Path | None = Field(default=None, description="Log file path")
    max_bytes: int = Field(
        default=10_485_760,  # 10MB
        description="Maximum log file size in bytes",
    )
    backup_count: int = Field(
        default=5,
        description="Number of backup log files to keep",
    )
    json_format: bool = Field(
        default=False,
        description="Use JSON format for structured logging",
    )

    @field_validator("file_path")
    @classmethod
    def validate_file_path(cls, v: Path | None) -> Path | None:
        """Ensure file path directory exists."""
        if v is not None:
            v.parent.mkdir(parents=True, exist_ok=True)
        return v


class StructuredFormatter(logging.Formatter):
    """Custom formatter for structured JSON logging."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        import json
        from datetime import datetime

        log_data = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add extra fields
        for key, value in record.__dict__.items():
            if key not in [
                "name",
                "msg",
                "args",
                "created",
                "msecs",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "getMessage",
            ]:
                log_data[key] = value

        return json.dumps(log_data)


def setup_logging(config: LoggingConfig | None = None) -> None:
    """
    Set up logging configuration.

    Args:
        config: Logging configuration. If None, uses defaults.
    """
    if config is None:
        config = LoggingConfig()

    # Reset existing handlers
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(config.level.value)

    # Create formatters
    if config.json_format:
        formatter = StructuredFormatter()
    else:
        formatter = logging.Formatter(config.format, datefmt=config.date_format)

    # Console handler
    if config.console_enabled:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    # File handler
    if config.file_enabled and config.file_path:
        file_handler = logging.handlers.RotatingFileHandler(
            filename=config.file_path,
            maxBytes=config.max_bytes,
            backupCount=config.backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    # Log the configuration
    logger = logging.getLogger(__name__)
    logger.info("Logging configured", extra={"config": config.model_dump()})


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance.

    Args:
        name: Logger name (usually __name__)

    Returns:
        Logger instance
    """
    return logging.getLogger(name)


# Example usage patterns
def log_with_context(logger: logging.Logger, message: str, **context) -> None:
    """
    Log a message with additional context.

    Args:
        logger: Logger instance
        message: Log message
        **context: Additional context to include
    """
    logger.info(message, extra=context)


def log_error_with_trace(
    logger: logging.Logger, error: Exception, message: str = "Error occurred"
) -> None:
    """
    Log an error with full traceback.

    Args:
        logger: Logger instance
        error: Exception instance
        message: Error message
    """
    logger.error(message, exc_info=error, extra={"error_type": type(error).__name__})
