# Use Python 3.13 slim image for smaller size
FROM python:3.13-slim AS builder

# Set work directory
WORKDIR /build

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip install --no-cache-dir uv

# Copy dependency files
COPY packages/ipc_router/pyproject.toml packages/ipc_router/
COPY packages/ipc_client_sdk/pyproject.toml packages/ipc_client_sdk/
COPY pyproject.toml .

# Create a virtual environment and install dependencies
RUN uv venv /venv
ENV VIRTUAL_ENV=/venv
ENV PATH="/venv/bin:$PATH"

# Install dependencies
WORKDIR /build/packages/ipc_router
RUN uv pip install -e .

# Runtime stage
FROM python:3.13-slim

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/venv \
    PATH="/venv/bin:$PATH"

# Copy virtual environment from builder
COPY --from=builder /venv /venv

# Set work directory
WORKDIR /app

# Copy application code
COPY packages/ipc_router /app/ipc_router
COPY packages/ipc_client_sdk /app/ipc_client_sdk

# Change ownership to non-root user
RUN chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import sys; sys.exit(0)" || exit 1

# Default command (to be overridden)
CMD ["python", "-m", "ipc_router"]
