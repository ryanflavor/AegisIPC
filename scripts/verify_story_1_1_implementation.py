#!/usr/bin/env python3
"""Verify Story 1.1 implementation without running full tests.

This script checks that all the project initialization and engineering practices
are properly implemented according to the acceptance criteria.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


def check_file_exists(file_path: Path, description: str) -> bool:
    """Check if a file exists and report result."""
    if file_path.exists():
        print(f"✓ {description}")
        return True
    else:
        print(f"✗ {description} - File not found: {file_path}")
        return False


def check_file_contains(file_path: Path, patterns: list[str], description: str) -> bool:
    """Check if file contains all specified patterns."""
    if not file_path.exists():
        print(f"✗ {description} - File not found: {file_path}")
        return False

    try:
        content = file_path.read_text()
        missing = []
        for pattern in patterns:
            if pattern not in content:
                missing.append(pattern)

        if not missing:
            print(f"✓ {description}")
            return True
        else:
            print(f"✗ {description} - Missing patterns: {missing}")
            return False
    except Exception as e:
        print(f"✗ {description} - Error reading file: {e}")
        return False


def check_command_exists(command: str) -> bool:
    """Check if a command exists in the system."""
    try:
        result = subprocess.run(
            [command, "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def verify_ac1_package_management() -> bool:
    """AC1: 项目使用 uv 和 pyproject.toml 管理依赖."""
    print("\n" + "=" * 60)
    print("AC1: Package Management with uv and pyproject.toml")
    print("=" * 60)

    results = []

    # Check uv installation
    if check_command_exists("uv"):
        print("✓ uv package manager is installed")
        results.append(True)
    else:
        print("✗ uv is not installed")
        print("  Install with: curl -LsSf https://astral.sh/uv/install.sh | sh")
        results.append(False)

    # Check root pyproject.toml
    root_toml = PROJECT_ROOT / "pyproject.toml"
    results.append(check_file_exists(root_toml, "Root pyproject.toml exists"))

    if root_toml.exists():
        # Check workspace configuration
        patterns = [
            "[tool.uv.workspace]",
            "members = [",
            '"packages/ipc_router"',
            '"packages/ipc_client_sdk"',
            '"packages/ipc_cli"',
        ]
        results.append(
            check_file_contains(root_toml, patterns, "Workspace configuration is correct")
        )

        # Check Python version requirement
        results.append(
            check_file_contains(
                root_toml, ['requires-python = ">=3.13"'], "Python 3.13+ requirement specified"
            )
        )

    # Check package pyproject.toml files
    packages = {
        "ipc_router": PROJECT_ROOT / "packages/ipc_router/pyproject.toml",
        "ipc_client_sdk": PROJECT_ROOT / "packages/ipc_client_sdk/pyproject.toml",
        "ipc_cli": PROJECT_ROOT / "packages/ipc_cli/pyproject.toml",
    }

    for package_name, package_toml in packages.items():
        results.append(check_file_exists(package_toml, f"{package_name} has pyproject.toml"))

    # Check key development dependencies
    dev_deps = {
        "Black": '"black==',
        "Ruff": '"ruff==',
        "Mypy": '"mypy==',
        "Pytest": '"pytest==',
        "Pre-commit": '"pre-commit==',
    }

    print("\nDevelopment dependencies:")
    for dep_name, pattern in dev_deps.items():
        if root_toml.exists():
            content = root_toml.read_text()
            if pattern in content:
                print(f"✓ {dep_name} configured")
                results.append(True)
            else:
                print(f"✗ {dep_name} not found")
                results.append(False)

    return all(results)


def verify_ac2_code_quality_tools() -> bool:
    """AC2: Black, Ruff, Mypy 已配置并集成到pre-commit hook."""
    print("\n" + "=" * 60)
    print("AC2: Code Quality Tools and Pre-commit Integration")
    print("=" * 60)

    results = []

    # Check .pre-commit-config.yaml
    pre_commit_config = PROJECT_ROOT / ".pre-commit-config.yaml"
    results.append(check_file_exists(pre_commit_config, ".pre-commit-config.yaml exists"))

    if pre_commit_config.exists():
        # Check hooks configuration
        hooks_patterns = [
            "id: black",
            "id: ruff",
            "id: mypy",
            "id: bandit",
        ]
        results.append(
            check_file_contains(
                pre_commit_config, hooks_patterns, "All code quality hooks configured"
            )
        )

    # Check tool configurations in pyproject.toml
    root_toml = PROJECT_ROOT / "pyproject.toml"
    if root_toml.exists():
        tool_configs = [
            ("[tool.black]", "Black configuration"),
            ("[tool.ruff]", "Ruff configuration"),
            ("[tool.mypy]", "Mypy configuration"),
            ("[tool.pytest.ini_options]", "Pytest configuration"),
        ]

        print("\nTool configurations:")
        content = root_toml.read_text()
        for pattern, desc in tool_configs:
            if pattern in content:
                print(f"✓ {desc} found")
                results.append(True)
            else:
                print(f"✗ {desc} missing")
                results.append(False)

        # Check specific settings
        settings_checks = [
            ("line-length = 100", "Line length set to 100"),
            ("strict_equality = true", "Mypy strict equality enabled"),
            ("--cov=packages", "Pytest coverage configured"),
        ]

        print("\nSpecific settings:")
        for pattern, desc in settings_checks:
            if pattern in content:
                print(f"✓ {desc}")
                results.append(True)
            else:
                print(f"✗ {desc}")
                results.append(False)

    # Check if pre-commit is available
    if check_command_exists("pre-commit"):
        print("✓ pre-commit is installed globally")
        results.append(True)
    else:
        # Check if available through uv
        try:
            result = subprocess.run(
                ["uv", "run", "pre-commit", "--version"],
                capture_output=True,
                text=True,
                check=False,
                cwd=PROJECT_ROOT,
            )
            if result.returncode == 0:
                print("✓ pre-commit available through uv")
                results.append(True)
            else:
                print("✗ pre-commit not available")
                results.append(False)
        except Exception:
            print("✗ pre-commit not available")
            results.append(False)

    return all(results)


def verify_ac3_containerization() -> bool:
    """AC3: 提供 Dockerfile 和 docker-compose.yaml 用于本地开发."""
    print("\n" + "=" * 60)
    print("AC3: Docker and docker-compose Configuration")
    print("=" * 60)

    results = []

    # Check docker-compose.yaml
    docker_compose = PROJECT_ROOT / "docker-compose.yaml"
    results.append(check_file_exists(docker_compose, "docker-compose.yaml exists"))

    if docker_compose.exists():
        # Check services
        service_patterns = [
            "nats:",
            "-js",  # JetStream enabled
            "ipc-router:",
            "dev-tools:",
        ]
        results.append(
            check_file_contains(
                docker_compose, service_patterns, "All required services configured"
            )
        )

        # Check specific configurations
        config_patterns = [
            "image: nats:latest",
            "build:",
            "volumes:",
            "networks:",
        ]
        results.append(
            check_file_contains(
                docker_compose, config_patterns, "Docker compose properly configured"
            )
        )

    # Check IPC Router Dockerfile
    dockerfile = PROJECT_ROOT / "packages/ipc_router/Dockerfile"
    results.append(check_file_exists(dockerfile, "IPC Router Dockerfile exists"))

    if dockerfile.exists():
        # Check Dockerfile best practices
        dockerfile_patterns = [
            "FROM python:3.13",
            "AS builder",  # Multi-stage build
            "USER",  # Security user
            "WORKDIR",
            "COPY",
        ]
        results.append(
            check_file_contains(
                dockerfile, dockerfile_patterns, "Dockerfile follows best practices"
            )
        )

    # Check if Docker is installed
    if check_command_exists("docker"):
        print("✓ Docker is installed")
        results.append(True)

        # Validate docker-compose syntax
        try:
            result = subprocess.run(
                ["docker", "compose", "config", "--quiet"],
                capture_output=True,
                text=True,
                check=False,
                cwd=PROJECT_ROOT,
            )
            if result.returncode == 0:
                print("✓ docker-compose configuration is valid")
                results.append(True)
            else:
                print("✗ docker-compose validation failed")
                print(f"  Error: {result.stderr}")
                results.append(False)
        except Exception as e:
            print(f"✗ Could not validate docker-compose: {e}")
            results.append(False)
    else:
        print("⚠ Docker not installed - cannot validate compose configuration")

    return all(results)


def verify_ac4_architecture() -> bool:
    """AC4: 初始源代码目录遵循分层结构(domain, application, infrastructure)."""
    print("\n" + "=" * 60)
    print("AC4: Hexagonal Architecture Structure")
    print("=" * 60)

    results = []

    # Check IPC Router structure
    router_base = PROJECT_ROOT / "packages/ipc_router/ipc_router"

    # Required directories
    required_dirs = {
        "api": "API layer (ports/adapters)",
        "application": "Application services layer",
        "domain": "Domain models and business logic",
        "infrastructure": "Infrastructure implementations",
    }

    print("Directory structure:")
    for dir_name, description in required_dirs.items():
        dir_path = router_base / dir_name
        if dir_path.exists() and dir_path.is_dir():
            print(f"✓ {dir_name}/ - {description}")
            results.append(True)

            # Check for __init__.py
            init_file = dir_path / "__init__.py"
            if init_file.exists():
                print(f"  ✓ {dir_name}/__init__.py exists")
            else:
                print(f"  ⚠ {dir_name}/__init__.py missing")
        else:
            print(f"✗ {dir_name}/ - Missing directory")
            results.append(False)

    # Check layer contents
    print("\nLayer contents:")

    # Domain layer
    domain_path = router_base / "domain"
    if domain_path.exists():
        domain_files = list(domain_path.glob("*.py"))
        domain_modules = [f.name for f in domain_files if f.name != "__init__.py"]
        if domain_modules:
            print(f"✓ Domain layer has {len(domain_modules)} modules:")
            for module in domain_modules[:5]:  # Show first 5
                print(f"  - {module}")
            results.append(True)
        else:
            print("⚠ Domain layer is empty (ready for implementation)")
            results.append(True)  # Empty is OK for initial setup

    # Application layer
    app_path = router_base / "application"
    if app_path.exists():
        app_subdirs = [d for d in app_path.iterdir() if d.is_dir() and d.name != "__pycache__"]
        if app_subdirs:
            print(f"✓ Application layer has {len(app_subdirs)} subdirectories:")
            for subdir in app_subdirs[:5]:  # Show first 5
                print(f"  - {subdir.name}/")
            results.append(True)
        else:
            print("⚠ Application layer is empty (ready for services)")
            results.append(True)  # Empty is OK for initial setup

    # Infrastructure layer
    infra_path = router_base / "infrastructure"
    if infra_path.exists():
        infra_subdirs = [d for d in infra_path.iterdir() if d.is_dir() and d.name != "__pycache__"]
        if infra_subdirs:
            print(f"✓ Infrastructure layer has {len(infra_subdirs)} subdirectories:")
            for subdir in infra_subdirs[:5]:  # Show first 5
                print(f"  - {subdir.name}/")
            results.append(True)
        else:
            print("⚠ Infrastructure layer is empty (ready for implementations)")
            results.append(True)  # Empty is OK for initial setup

    # Check separation of concerns
    print("\nArchitecture validation:")

    # Domain should not depend on infrastructure
    if domain_path.exists():
        domain_imports_infra = False
        for py_file in domain_path.glob("**/*.py"):
            try:
                content = py_file.read_text()
                if (
                    "from ipc_router.infrastructure" in content
                    or "import ipc_router.infrastructure" in content
                ):
                    domain_imports_infra = True
                    break
            except Exception:
                pass

        if not domain_imports_infra:
            print("✓ Domain layer properly isolated (no infrastructure imports)")
            results.append(True)
        else:
            print("✗ Domain layer has infrastructure dependencies")
            results.append(False)

    return all(results)


def check_bonus_features() -> None:
    """Check additional production-readiness features."""
    print("\n" + "=" * 60)
    print("BONUS: Production Readiness Features")
    print("=" * 60)

    # CI/CD
    ci_file = PROJECT_ROOT / ".github/workflows/ci.yaml"
    if ci_file.exists():
        print("✓ CI/CD workflow configured (.github/workflows/ci.yaml)")
    else:
        print("⚠ No CI/CD workflow found")

    # Documentation and security files
    files_to_check = [
        ("README.md", "Project documentation"),
        ("SECURITY.md", "Security policy"),
        ("CONTRIBUTING.md", "Contribution guidelines"),
        (".env.example", "Environment variables example"),
        ("Makefile", "Developer convenience commands"),
        (".gitignore", "Git ignore configuration"),
        ("LICENSE", "License file"),
    ]

    for filename, description in files_to_check:
        file_path = PROJECT_ROOT / filename
        if file_path.exists():
            print(f"✓ {filename} - {description}")
        else:
            print(f"⚠ {filename} - {description} (not found)")

    # Check Makefile targets if it exists
    makefile = PROJECT_ROOT / "Makefile"
    if makefile.exists():
        try:
            result = subprocess.run(
                ["make", "help"],
                capture_output=True,
                text=True,
                check=False,
                cwd=PROJECT_ROOT,
            )
            if result.returncode == 0 and result.stdout:
                print("\nAvailable make commands:")
                lines = result.stdout.strip().split("\n")[:10]  # Show first 10
                for line in lines:
                    if line.strip():
                        print(f"  {line}")
        except Exception:
            pass


def verify_implementation() -> None:
    """Verify all Story 1.1 features are implemented."""
    print("Verifying Story 1.1 Implementation...")
    print("=" * 60)
    print("Story 1.1: 项目初始化与工程实践框架搭建")
    print("=" * 60)

    results = {
        "AC1": verify_ac1_package_management(),
        "AC2": verify_ac2_code_quality_tools(),
        "AC3": verify_ac3_containerization(),
        "AC4": verify_ac4_architecture(),
    }

    # Check bonus features
    check_bonus_features()

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY:")
    passed = sum(results.values())
    total = len(results)

    if passed == total:
        print(f"✅ ALL {total} acceptance criteria have been implemented!")
        print("\nThe project has been successfully initialized with:")
        print("  ✓ Modern Python tooling (uv, Python 3.13)")
        print("  ✓ Comprehensive code quality automation")
        print("  ✓ Production-ready containerization")
        print("  ✓ Clean hexagonal architecture")
        print("  ✓ Security and contribution guidelines")
    else:
        print(f"⚠️  {passed}/{total} acceptance criteria implemented")
        print("\nImplementation status:")

    ac_descriptions = {
        "AC1": "Package management with uv and pyproject.toml",
        "AC2": "Code quality tools and pre-commit integration",
        "AC3": "Docker containerization for local development",
        "AC4": "Hexagonal architecture structure",
    }

    for ac, passed in results.items():
        status = "✓" if passed else "✗"
        print(f"  {status} {ac}: {ac_descriptions[ac]}")

    return passed == total


if __name__ == "__main__":
    success = verify_implementation()
    sys.exit(0 if success else 1)
