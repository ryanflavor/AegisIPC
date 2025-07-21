"""Basic tests for ipc_cli package."""


def test_cli_import() -> None:
    """Test that the ipc_cli package can be imported."""
    import ipc_cli

    assert ipc_cli is not None


def test_list_operations() -> None:
    """Test basic list operations to verify pytest is working."""
    test_list = [1, 2, 3, 4, 5]
    assert len(test_list) == 5
    assert sum(test_list) == 15
    assert max(test_list) == 5
    assert min(test_list) == 1


class TestBasicClass:
    """Test class to verify pytest class collection."""

    def test_instance_creation(self) -> None:
        """Test that we can create class instances."""

        class SimpleClass:
            def __init__(self, value: int) -> None:
                self.value = value

        instance = SimpleClass(42)
        assert instance.value == 42

    def test_dictionary_operations(self) -> None:
        """Test basic dictionary operations."""
        test_dict = {"key1": "value1", "key2": "value2"}
        assert len(test_dict) == 2
        assert "key1" in test_dict
        assert test_dict.get("key3", "default") == "default"
