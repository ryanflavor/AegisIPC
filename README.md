# AegisIPC

[![CI](https://github.com/AegisIPC/AegisIPC/actions/workflows/ci.yaml/badge.svg)](https://github.com/AegisIPC/AegisIPC/actions/workflows/ci.yaml)
[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/downloads/release/python-313/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Checked with mypy](https://www.mypy-lang.org/static/mypy_badge.svg)](https://mypy-lang.org/)

A high-performance IPC (Inter-Process Communication) framework for distributed systems, built on NATS JetStream with MessagePack serialization.

## Overview

AegisIPC provides a robust, scalable solution for inter-process communication in distributed systems. It leverages:

- **NATS JetStream** for reliable, high-performance messaging
- **MessagePack** for efficient binary serialization
- **Pydantic v2+** for data validation and contract-driven development
- **Hexagonal Architecture** for clean, maintainable code structure

## Project Structure

This is a monorepo containing three main packages:

```
packages/
├── ipc_router/      # Core routing service
├── ipc_client_sdk/  # Client SDK for IPC interactions
└── ipc_cli/         # Command-line management tool
```

## 🚀 Quick Start

### Prerequisites

- Python 3.13+
- Docker and Docker Compose
- uv package manager ([install instructions](https://github.com/astral-sh/uv))

### Development Setup

```bash
# Clone the repository
git clone https://github.com/AegisIPC/AegisIPC.git
cd AegisIPC

# Install uv if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Complete development setup (installs deps + pre-commit hooks)
make dev-setup

# Run all quality checks
make check

# Start services
make docker-up
```

### 🛠️ Development Commands

We provide a comprehensive Makefile for common tasks:

```bash
make help         # Show all available commands
make format       # Format code with Black and Ruff
make lint         # Run linting checks
make security     # Run security scans
make test         # Run unit tests
make test-coverage # Run tests with coverage report
make docker-build # Build Docker images
make docs-serve   # Serve documentation locally
```

## 🧪 Testing

```bash
# Run unit tests
make test

# Run tests with coverage report
make test-coverage

# Run integration tests
make test-integration

# Run all tests
make test-all
```

We maintain a minimum of 80% code coverage.

## 🔒 Security

Security is a top priority for AegisIPC:

- **Dependency Scanning**: Automated with Bandit, Safety, and pip-audit
- **Container Scanning**: Trivy scans in CI/CD
- **Version Pinning**: All dependencies are version-pinned
- **Automated Updates**: Dependabot for dependency updates
- **Security Policy**: See [SECURITY.md](SECURITY.md) for vulnerability reporting

Run security checks locally:

```bash
make security
```

## 🏗️ Architecture

AegisIPC follows a hexagonal architecture pattern with Domain-Driven Design (DDD) principles:

```
ipc_router/
├── api/              # External interfaces (REST, gRPC, CLI)
├── application/      # Use cases and orchestration
├── domain/          # Business logic and entities
└── infrastructure/  # Technical implementations
```

### Key Design Principles

- **Clean Architecture**: Dependencies point inward
- **Domain-Driven Design**: Business logic at the core
- **Contract-First**: Pydantic models define all interfaces
- **Error Handling**: Comprehensive error hierarchy with retry patterns
- **Observability**: Structured logging and metrics

## 📊 Code Quality Standards

- **Type Safety**: 100% type hints with strict Mypy checking
- **Code Formatting**: Black + Ruff with automatic formatting
- **Testing**: Pytest with minimum 80% coverage
- **Documentation**: Comprehensive docstrings and architecture docs
- **Pre-commit Hooks**: Automated quality checks before commit

## 🤝 Contributing

We welcome contributions! Please see:

- [Contributing Guidelines](CONTRIBUTING.md) - Git workflow and standards
- [Security Policy](SECURITY.md) - Reporting vulnerabilities
- [Code of Conduct](CODE_OF_CONDUCT.md) - Community guidelines

## 📚 Documentation

- [Architecture Overview](docs/architecture.md) - System design and patterns
- [Product Requirements](docs/prd.md) - Feature specifications
- [API Documentation](https://aegisipc.readthedocs.io) - Coming soon
- [User Stories](docs/stories/) - Development roadmap

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 💬 Support

- **Issues**: [GitHub Issues](https://github.com/AegisIPC/AegisIPC/issues)
- **Discussions**: [GitHub Discussions](https://github.com/AegisIPC/AegisIPC/discussions)
- **Security**: security@aegisipc.com
