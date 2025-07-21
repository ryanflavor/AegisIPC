# Contributing to AegisIPC

Thank you for your interest in contributing to AegisIPC! This document provides guidelines and workflows for contributing to the project.

## Git Workflow

We follow a simplified Git Flow model:

### Branches

- **`main`** - Production-ready code. Protected branch requiring PR reviews.
- **`develop`** - Integration branch for features. All feature branches merge here first.
- **`feature/*`** - Feature branches (e.g., `feature/add-retry-logic`)
- **`bugfix/*`** - Bug fix branches (e.g., `bugfix/fix-connection-timeout`)
- **`hotfix/*`** - Emergency fixes that go directly to main (e.g., `hotfix/critical-security-patch`)
- **`release/*`** - Release preparation branches (e.g., `release/1.0.0`)

### Workflow Steps

1. **Start a new feature**
   ```bash
   git checkout develop
   git pull origin develop
   git checkout -b feature/your-feature-name
   ```

2. **Work on your feature**
   ```bash
   # Make changes
   git add .
   git commit -m "feat: add new feature description"
   ```

3. **Keep your branch updated**
   ```bash
   git checkout develop
   git pull origin develop
   git checkout feature/your-feature-name
   git rebase develop
   ```

4. **Submit a Pull Request**
   - Push your branch: `git push origin feature/your-feature-name`
   - Create a PR from your branch to `develop`
   - Ensure all CI checks pass
   - Request review from maintainers

## Development Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/AegisIPC/AegisIPC.git
   cd AegisIPC
   ```

2. **Install uv (package manager)**
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

3. **Install dependencies**
   ```bash
   uv sync
   ```

4. **Install pre-commit hooks**
   ```bash
   uv run pre-commit install
   ```

5. **Run tests**
   ```bash
   uv run pytest
   ```

## Commit Message Convention

We follow the [Conventional Commits](https://www.conventionalcommits.org/) specification:

- `feat:` New feature
- `fix:` Bug fix
- `docs:` Documentation changes
- `style:` Code style changes (formatting, missing semicolons, etc.)
- `refactor:` Code refactoring
- `perf:` Performance improvements
- `test:` Adding or updating tests
- `build:` Build system or dependency changes
- `ci:` CI/CD configuration changes
- `chore:` Other changes that don't modify src or test files

### Examples

```
feat: add retry logic to NATS connection
fix: resolve timeout issue in message processing
docs: update API documentation for new endpoints
refactor: simplify error handling in router module
```

## Code Standards

### Python Code Style

- Follow PEP 8
- Use type hints for all function signatures
- Maximum line length: 100 characters
- Use Black for formatting (automatically applied via pre-commit)

### Testing

- Write unit tests for all new functionality
- Maintain or improve code coverage (minimum 80%)
- Use pytest for all tests
- Follow the AAA pattern: Arrange, Act, Assert

### Documentation

- Add docstrings to all public functions and classes
- Use Google-style docstrings
- Update README.md if adding new features
- Include examples for complex functionality

## Pull Request Guidelines

1. **Before submitting:**
   - Run all tests: `uv run pytest`
   - Run linters: `uv run pre-commit run --all-files`
   - Update documentation as needed
   - Add tests for new functionality

2. **PR Description should include:**
   - Summary of changes
   - Related issue numbers (if applicable)
   - Breaking changes (if any)
   - Screenshots (for UI changes)

3. **Review process:**
   - At least one maintainer approval required
   - All CI checks must pass
   - No merge conflicts with target branch

## Security

- Never commit secrets, keys, or credentials
- Report security vulnerabilities privately to security@aegisipc.com
- Use environment variables for sensitive configuration
- Follow the principle of least privilege

## Questions?

If you have questions about contributing:

1. Check existing issues and discussions
2. Join our community chat (link TBD)
3. Open a discussion in the GitHub Discussions tab

Thank you for helping make AegisIPC better!
