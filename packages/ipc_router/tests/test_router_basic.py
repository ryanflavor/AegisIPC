"""Basic tests for ipc_router package."""


def test_router_import() -> None:
    """Test that the ipc_router package can be imported."""
    import ipc_router

    assert ipc_router is not None


def test_router_layers_import() -> None:
    """Test that all layers can be imported."""
    import ipc_router.api
    import ipc_router.application
    import ipc_router.domain
    import ipc_router.infrastructure

    assert ipc_router.api is not None
    assert ipc_router.application is not None
    assert ipc_router.domain is not None
    assert ipc_router.infrastructure is not None


def test_basic_arithmetic() -> None:
    """Test basic arithmetic to verify pytest is working."""
    assert 1 + 1 == 2
    assert 2 * 3 == 6
    assert 10 / 2 == 5
