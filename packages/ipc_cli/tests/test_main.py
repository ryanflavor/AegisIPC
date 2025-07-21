"""Tests for CLI main module."""

from ipc_cli.main import app
from typer.testing import CliRunner

runner = CliRunner()


class TestCLICommands:
    """Test CLI commands."""

    def test_version_command(self) -> None:
        """Test version command."""
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert "IPC CLI version 0.1.0" in result.stdout

    def test_hello_command(self) -> None:
        """Test hello command."""
        result = runner.invoke(app, ["hello"])
        assert result.exit_code == 0
        assert "Hello from AegisIPC CLI!" in result.stdout

    def test_help_command(self) -> None:
        """Test help command."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        # Check for key components - Typer may format differently
        assert any(word in result.stdout.lower() for word in ["usage", "command", "help"])
        assert "version" in result.stdout
        assert "hello" in result.stdout

    def test_invalid_command(self) -> None:
        """Test invalid command."""
        result = runner.invoke(app, ["invalid"])
        assert result.exit_code != 0
        assert "No such command" in result.stdout or "Error" in result.stdout
