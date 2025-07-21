"""Tests for version module."""

from ipc_router.version import __version__


def test_version_format() -> None:
    """Test that version is in expected format."""
    assert isinstance(__version__, str)
    assert __version__ == "0.1.0"

    # Test version parts
    parts = __version__.split(".")
    assert len(parts) == 3
    assert all(part.isdigit() for part in parts)
