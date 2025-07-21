"""Basic tests for ipc_client_sdk package."""

import pytest


def test_sdk_import() -> None:
    """Test that the ipc_client_sdk package can be imported."""
    import ipc_client_sdk

    assert ipc_client_sdk is not None


def test_basic_string_operations() -> None:
    """Test basic string operations to verify pytest is working."""
    test_string = "AegisIPC"
    assert test_string.lower() == "aegisipc"
    assert test_string.upper() == "AEGISIPC"
    assert len(test_string) == 8


@pytest.mark.parametrize(
    "input_value,expected",
    [
        (1, 1),
        (2, 4),
        (3, 9),
        (4, 16),
        (5, 25),
    ],
)
def test_parametrized_square(input_value: int, expected: int) -> None:
    """Test parametrized square calculation."""
    assert input_value**2 == expected
