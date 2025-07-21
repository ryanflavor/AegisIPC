.PHONY: help install install-hooks sync format lint type-check security test test-unit test-integration test-coverage clean docker-build docker-up docker-down docs

# Default target
.DEFAULT_GOAL := help

# Colors for output
BLUE := \033[0;34m
GREEN := \033[0;32m
YELLOW := \033[0;33m
RED := \033[0;31m
NC := \033[0m # No Color

help: ## Show this help message
	@echo '${BLUE}Usage:${NC}'
	@echo '  ${GREEN}make${NC} ${YELLOW}<target>${NC}'
	@echo ''
	@echo '${BLUE}Targets:${NC}'
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  ${GREEN}%-20s${NC} %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install uv and project dependencies
	@echo "${BLUE}Installing uv package manager...${NC}"
	@curl -LsSf https://astral.sh/uv/install.sh | sh
	@echo "${BLUE}Installing project dependencies...${NC}"
	@uv sync --all-extras
	@echo "${GREEN}✓ Installation complete${NC}"

install-hooks: ## Install pre-commit hooks
	@echo "${BLUE}Installing pre-commit hooks...${NC}"
	@./scripts/install-hooks.sh
	@echo "${GREEN}✓ Hooks installed${NC}"

sync: ## Sync all dependencies
	@echo "${BLUE}Syncing dependencies...${NC}"
	@uv sync --all-extras
	@echo "${GREEN}✓ Dependencies synced${NC}"

format: ## Format code with black and ruff
	@echo "${BLUE}Formatting code...${NC}"
	@uv run black .
	@uv run ruff check --fix .
	@echo "${GREEN}✓ Code formatted${NC}"

lint: ## Run all linting checks
	@echo "${BLUE}Running linting checks...${NC}"
	@uv run black --check .
	@uv run ruff check .
	@uv run mypy packages/
	@echo "${GREEN}✓ All linting checks passed${NC}"

type-check: ## Run type checking with mypy
	@echo "${BLUE}Running type checks...${NC}"
	@uv run mypy packages/
	@echo "${GREEN}✓ Type checking passed${NC}"

security: ## Run all security checks
	@echo "${BLUE}Running security checks...${NC}"
	@echo "${YELLOW}Running Bandit...${NC}"
	@uv run bandit -r packages/ -ll
	@echo "${YELLOW}Running pip-audit...${NC}"
	@uv run pip-audit
	@echo "${GREEN}✓ All security checks passed${NC}"

test: test-unit ## Run unit tests (default)

test-unit: ## Run unit tests
	@echo "${BLUE}Running unit tests...${NC}"
	@uv run pytest -v -m "not integration" --tb=short

test-integration: ## Run integration tests
	@echo "${BLUE}Running integration tests...${NC}"
	@uv run pytest -v -m integration --tb=short

test-coverage: ## Run tests with coverage report
	@echo "${BLUE}Running tests with coverage...${NC}"
	@uv run pytest -v --cov=packages --cov-report=term-missing --cov-report=html --cov-report=xml
	@echo "${GREEN}✓ Coverage report generated in htmlcov/${NC}"

test-all: ## Run all tests including integration
	@echo "${BLUE}Running all tests...${NC}"
	@uv run pytest -v --tb=short

clean: ## Clean build artifacts and caches
	@echo "${BLUE}Cleaning build artifacts...${NC}"
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name "dist" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name "build" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@find . -type f -name ".coverage" -delete 2>/dev/null || true
	@rm -rf htmlcov/ 2>/dev/null || true
	@echo "${GREEN}✓ Cleaned${NC}"

docker-build: ## Build Docker images
	@echo "${BLUE}Building Docker images...${NC}"
	@docker-compose build
	@echo "${GREEN}✓ Docker images built${NC}"

docker-up: ## Start Docker services
	@echo "${BLUE}Starting Docker services...${NC}"
	@docker-compose up -d
	@echo "${GREEN}✓ Services started${NC}"

docker-down: ## Stop Docker services
	@echo "${BLUE}Stopping Docker services...${NC}"
	@docker-compose down
	@echo "${GREEN}✓ Services stopped${NC}"

docker-logs: ## Show Docker service logs
	@docker-compose logs -f

docs: ## Build documentation
	@echo "${BLUE}Building documentation...${NC}"
	@uv run mkdocs build
	@echo "${GREEN}✓ Documentation built in site/${NC}"

docs-serve: ## Serve documentation locally
	@echo "${BLUE}Serving documentation at http://localhost:8000${NC}"
	@uv run mkdocs serve

# Development workflow commands
dev-setup: install install-hooks ## Complete development environment setup
	@echo "${GREEN}✓ Development environment ready!${NC}"

check: format lint type-check security ## Run all checks (format, lint, type-check, security)
	@echo "${GREEN}✓ All checks passed!${NC}"

ci: lint type-check test-coverage security ## Run CI checks locally
	@echo "${GREEN}✓ CI checks passed!${NC}"
