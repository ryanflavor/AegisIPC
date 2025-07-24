#!/usr/bin/env python3
"""
Demonstration of Story 1.1 project initialization and engineering practices.

Acceptance Criteria:
1. 项目使用 uv 和 pyproject.toml 管理依赖。
2. Black, Ruff, Mypy 已配置并集成到pre-commit hook。
3. 提供 Dockerfile 和 docker-compose.yaml 用于本地开发。
4. 初始源代码目录遵循分层结构(domain, application, infrastructure)。
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from demo_utils import DemoLogger, DemoResult, DemoSettings, colors


class Story11Demo:
    """Demonstrates Story 1.1 acceptance criteria."""

    def __init__(self, settings: DemoSettings) -> None:
        """Initialize demo with configuration.

        Args:
            settings: Demo configuration settings
        """
        self.settings = settings
        self.logger = DemoLogger("Story 1.1")
        self.project_root = Path(__file__).parent.parent

    def check_command_exists(self, command: str) -> bool:
        """Check if a command exists in the system.

        Args:
            command: Command to check

        Returns:
            True if command exists
        """
        try:
            subprocess.run(
                [command, "--version"],
                capture_output=True,
                text=True,
                check=False,
            )
            return True
        except (subprocess.SubprocessError, FileNotFoundError):
            return False

    def run_command(self, command: list[str], cwd: str | None = None) -> tuple[bool, str, str]:
        """Run a shell command and return success status and output.

        Args:
            command: Command to run as list
            cwd: Working directory

        Returns:
            Tuple of (success, stdout, stderr)
        """
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                cwd=cwd or self.project_root,
                check=False,
            )
            return result.returncode == 0, result.stdout, result.stderr
        except Exception as e:
            return False, "", str(e)

    async def demonstrate_ac1(self) -> bool:
        """AC1: 项目使用 uv 和 pyproject.toml 管理依赖.

        Returns:
            True if uv and pyproject.toml are properly configured
        """
        self.logger.subsection("AC1: Package Management with uv")
        self.logger.info("Verifying uv package manager and pyproject.toml configuration")

        # Check if uv is installed
        if not self.check_command_exists("uv"):
            self.logger.failure("uv is not installed")
            self.logger.info("Install with: curl -LsSf https://astral.sh/uv/install.sh | sh")
            return False

        self.logger.success("uv package manager is installed")

        # Check root pyproject.toml
        root_pyproject = self.project_root / "pyproject.toml"
        if not root_pyproject.exists():
            self.logger.failure("Root pyproject.toml not found")
            return False

        self.logger.success(f"Found root pyproject.toml at {root_pyproject}")

        # Verify workspace configuration
        self.logger.info("Checking workspace configuration...")
        success, stdout, _ = self.run_command(["uv", "sync", "--dry-run"])
        if success:
            self.logger.success("Workspace configuration is valid")
        else:
            self.logger.warning("Workspace sync check failed (may need uv sync)")

        # Check package pyproject.toml files
        packages = ["ipc_router", "ipc_client_sdk", "ipc_cli"]
        all_found = True
        for package in packages:
            package_toml = self.project_root / f"packages/{package}/pyproject.toml"
            if package_toml.exists():
                self.logger.success(f"Found {package} pyproject.toml")
            else:
                self.logger.failure(f"Missing {package} pyproject.toml")
                all_found = False

        # Check for key dependencies
        self.logger.info("\nKey dependencies configured:")
        with open(root_pyproject) as f:
            content = f.read()
            deps = [
                ("Python 3.13", 'requires-python = ">=3.13"' in content),
                ("Black", '"black==' in content),
                ("Ruff", '"ruff==' in content),
                ("Mypy", '"mypy==' in content),
                ("Pytest", '"pytest==' in content),
            ]
            for name, found in deps:
                if found:
                    self.logger.success(f"{name} configured")
                else:
                    self.logger.failure(f"{name} not found")

        return all_found

    async def demonstrate_ac2(self) -> bool:
        """AC2: Black, Ruff, Mypy 已配置并集成到pre-commit hook.

        Returns:
            True if all code quality tools are properly configured
        """
        self.logger.subsection("AC2: Code Quality Tools Integration")
        self.logger.info("Verifying Black, Ruff, Mypy configuration and pre-commit hooks")

        # Check .pre-commit-config.yaml
        pre_commit_config = self.project_root / ".pre-commit-config.yaml"
        if not pre_commit_config.exists():
            self.logger.failure(".pre-commit-config.yaml not found")
            return False

        self.logger.success("Found .pre-commit-config.yaml")

        # Check if pre-commit is installed
        if not self.check_command_exists("pre-commit"):
            self.logger.warning("pre-commit not installed globally")
            self.logger.info("Checking if available through uv...")
            success, _, _ = self.run_command(["uv", "run", "pre-commit", "--version"])
            if not success:
                self.logger.failure("pre-commit not available")
                return False

        self.logger.success("pre-commit is available")

        # Verify hooks configuration
        with open(pre_commit_config) as f:
            content = f.read()
            hooks = [
                ("Black formatter", "black" in content),
                ("Ruff linter", "ruff" in content),
                ("Mypy type checker", "mypy" in content),
                ("Bandit security", "bandit" in content),
            ]
            all_configured = True
            for name, found in hooks:
                if found:
                    self.logger.success(f"{name} configured in pre-commit")
                else:
                    self.logger.failure(f"{name} not in pre-commit")
                    all_configured = False

        # Check pyproject.toml tool configurations
        self.logger.info("\nTool configurations in pyproject.toml:")
        with open(self.project_root / "pyproject.toml") as f:
            content = f.read()
            configs = [
                ("Black", "[tool.black]" in content, "line-length = 100"),
                ("Ruff", "[tool.ruff]" in content, "line-length = 100"),
                ("Mypy", "[tool.mypy]" in content, "strict_equality = true"),
                ("Pytest", "[tool.pytest.ini_options]" in content, "--cov=packages"),
            ]
            for tool, has_section, check_string in configs:
                if has_section and check_string in content:
                    self.logger.success(f"{tool} properly configured")
                else:
                    self.logger.warning(f"{tool} configuration incomplete")

        return all_configured

    async def demonstrate_ac3(self) -> bool:
        """AC3: 提供 Dockerfile 和 docker-compose.yaml 用于本地开发.

        Returns:
            True if Docker configuration is properly set up
        """
        self.logger.subsection("AC3: Containerization Setup")
        self.logger.info("Verifying Docker and docker-compose configuration")

        # Check docker-compose.yaml
        docker_compose = self.project_root / "docker-compose.yaml"
        if not docker_compose.exists():
            self.logger.failure("docker-compose.yaml not found")
            return False

        self.logger.success("Found docker-compose.yaml")

        # Verify services in docker-compose
        with open(docker_compose) as f:
            content = f.read()
            services = [
                ("NATS JetStream", "nats:" in content and "-js" in content),
                ("IPC Router", "ipc-router:" in content),
                ("Development tools", "dev-tools:" in content),
            ]
            all_services = True
            for name, found in services:
                if found:
                    self.logger.success(f"{name} service configured")
                else:
                    self.logger.failure(f"{name} service missing")
                    all_services = False

        # Check Dockerfile
        dockerfile = self.project_root / "packages/ipc_router/Dockerfile"
        if not dockerfile.exists():
            self.logger.failure("IPC Router Dockerfile not found")
            return False

        self.logger.success("Found IPC Router Dockerfile")

        # Verify Dockerfile content
        with open(dockerfile) as f:
            content = f.read()
            features = [
                ("Python 3.13", "FROM python:3.13" in content),
                ("Multi-stage build", "AS builder" in content),
                ("Security user", "useradd" in content or "USER" in content),
            ]
            for name, found in features:
                if found:
                    self.logger.success(f"Dockerfile has {name}")
                else:
                    self.logger.warning(f"Dockerfile missing {name}")

        # Check if Docker is available
        if self.check_command_exists("docker"):
            self.logger.success("Docker is installed")
            # Check if docker-compose works
            success, stdout, _ = self.run_command(
                ["docker", "compose", "config", "--quiet"],
                cwd=str(self.project_root),
            )
            if success:
                self.logger.success("docker-compose configuration is valid")
            else:
                self.logger.warning("docker-compose validation failed")
        else:
            self.logger.warning("Docker not installed - cannot validate compose file")

        return all_services

    async def demonstrate_ac4(self) -> bool:
        """AC4: 初始源代码目录遵循分层结构(domain, application, infrastructure).

        Returns:
            True if project structure follows hexagonal architecture
        """
        self.logger.subsection("AC4: Hexagonal Architecture Structure")
        self.logger.info("Verifying source code follows domain-driven design patterns")

        # Check IPC Router structure (main package that uses hexagonal architecture)
        router_base = self.project_root / "packages/ipc_router/ipc_router"
        required_dirs = ["api", "application", "domain", "infrastructure"]

        all_found = True
        for dir_name in required_dirs:
            dir_path = router_base / dir_name
            if dir_path.exists() and dir_path.is_dir():
                self.logger.success(f"Found {dir_name}/ layer")
                # Check for __init__.py
                init_file = dir_path / "__init__.py"
                if init_file.exists():
                    self.logger.info(f"  ✓ {dir_name}/__init__.py exists")
                else:
                    self.logger.warning(f"  ⚠ {dir_name}/__init__.py missing")
            else:
                self.logger.failure(f"Missing {dir_name}/ layer")
                all_found = False

        # Check for proper separation of concerns
        self.logger.info("\nVerifying layer contents:")

        # Check domain layer
        domain_path = router_base / "domain"
        if domain_path.exists():
            domain_contents = list(domain_path.glob("*.py"))
            if len(domain_contents) > 1:  # More than just __init__.py
                self.logger.success(f"Domain layer has {len(domain_contents)} files")
                for f in domain_contents[:3]:  # Show first 3
                    if f.name != "__init__.py":
                        self.logger.info(f"  - {f.name}")
            else:
                self.logger.info("Domain layer is ready for implementation")

        # Check application layer
        app_path = router_base / "application"
        if app_path.exists():
            subdirs = [d for d in app_path.iterdir() if d.is_dir()]
            if subdirs:
                self.logger.success(f"Application layer has {len(subdirs)} subdirectories")
                for d in subdirs[:3]:
                    self.logger.info(f"  - {d.name}/")
            else:
                self.logger.info("Application layer is ready for services")

        # Check infrastructure layer
        infra_path = router_base / "infrastructure"
        if infra_path.exists():
            subdirs = [d for d in infra_path.iterdir() if d.is_dir()]
            if subdirs:
                self.logger.success(f"Infrastructure layer has {len(subdirs)} subdirectories")
                for d in subdirs[:3]:
                    self.logger.info(f"  - {d.name}/")
            else:
                self.logger.info("Infrastructure layer is ready for implementations")

        return all_found

    async def run_bonus_checks(self) -> None:
        """Run additional production-readiness checks."""
        self.logger.subsection("Bonus: Production Readiness Checks")

        # Check for CI/CD
        ci_file = self.project_root / ".github/workflows/ci.yaml"
        if ci_file.exists():
            self.logger.success("CI/CD workflow configured")
        else:
            self.logger.warning("No CI/CD workflow found")

        # Check for security files
        security_files = [
            ("SECURITY.md", self.project_root / "SECURITY.md"),
            ("CONTRIBUTING.md", self.project_root / "CONTRIBUTING.md"),
            (".env.example", self.project_root / ".env.example"),
        ]
        for name, path in security_files:
            if path.exists():
                self.logger.success(f"{name} present")
            else:
                self.logger.info(f"{name} not found")

        # Check for Makefile
        makefile = self.project_root / "Makefile"
        if makefile.exists():
            self.logger.success("Makefile for developer convenience")
            # Show available commands
            success, stdout, _ = self.run_command(["make", "help"])
            if success and stdout:
                self.logger.info("Available make commands:")
                for line in stdout.strip().split("\n")[:5]:  # Show first 5
                    if line.strip():
                        self.logger.info(f"  {line}")

    async def run(self) -> DemoResult:
        """Run the complete demonstration.

        Returns:
            Demo execution result
        """
        self.logger.demo_header("Story 1.1 Demo", "项目初始化与工程实践框架搭建")

        result = DemoResult(success=True)

        try:
            # Run acceptance criteria tests
            if await self.demonstrate_ac1():
                result.criteria_passed.append("AC1: Project uses uv and pyproject.toml")
            else:
                result.criteria_failed.append("AC1: Package management setup incomplete")
                result.success = False

            await asyncio.sleep(0.5)

            if await self.demonstrate_ac2():
                result.criteria_passed.append("AC2: Code quality tools integrated")
            else:
                result.criteria_failed.append("AC2: Code quality tools missing")
                result.success = False

            await asyncio.sleep(0.5)

            if await self.demonstrate_ac3():
                result.criteria_passed.append("AC3: Docker environment configured")
            else:
                result.criteria_failed.append("AC3: Containerization incomplete")
                result.success = False

            await asyncio.sleep(0.5)

            if await self.demonstrate_ac4():
                result.criteria_passed.append("AC4: Hexagonal architecture implemented")
            else:
                result.criteria_failed.append("AC4: Architecture structure incorrect")
                result.success = False

            # Run bonus checks
            await self.run_bonus_checks()

            if result.success:
                self.logger.section(f"{colors.GREEN}All Acceptance Criteria PASSED!{colors.RESET}")
                self.logger.info("\nThe project has been successfully initialized with:")
                self.logger.success("Modern Python tooling (uv, Python 3.13)")
                self.logger.success("Comprehensive code quality automation")
                self.logger.success("Production-ready containerization")
                self.logger.success("Clean hexagonal architecture")
                self.logger.success("Security and contribution guidelines")
            else:
                self.logger.section(f"{colors.RED}Some Acceptance Criteria FAILED!{colors.RESET}")

            self.logger.info("\nSummary:")
            for passed in result.criteria_passed:
                self.logger.success(passed)
            for failed in result.criteria_failed:
                self.logger.failure(failed)

        except Exception as e:
            result.success = False
            result.error_message = str(e)
            self.logger.error("Demo failed", error=str(e))

        return result


async def main() -> None:
    """Entry point."""
    settings = DemoSettings()

    # For story 1.1, we don't need NATS running
    demo = Story11Demo(settings)
    result = await demo.run()

    # Exit with appropriate code
    exit(0 if result.success else 1)


if __name__ == "__main__":
    asyncio.run(main())
