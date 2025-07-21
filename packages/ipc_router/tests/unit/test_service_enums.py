"""Unit tests for service-related enums."""

from __future__ import annotations

import pytest
from ipc_router.domain.enums import ServiceStatus


class TestServiceStatus:
    """Tests for ServiceStatus enum."""

    def test_service_status_values(self) -> None:
        """Test that all expected status values exist."""
        assert ServiceStatus.ONLINE.value == "ONLINE"
        assert ServiceStatus.OFFLINE.value == "OFFLINE"
        assert ServiceStatus.UNHEALTHY.value == "UNHEALTHY"

    def test_service_status_members(self) -> None:
        """Test that all enum members are accessible."""
        assert ServiceStatus.ONLINE in ServiceStatus
        assert ServiceStatus.OFFLINE in ServiceStatus
        assert ServiceStatus.UNHEALTHY in ServiceStatus

    def test_service_status_from_value(self) -> None:
        """Test creating enum from string value."""
        assert ServiceStatus("ONLINE") == ServiceStatus.ONLINE
        assert ServiceStatus("OFFLINE") == ServiceStatus.OFFLINE
        assert ServiceStatus("UNHEALTHY") == ServiceStatus.UNHEALTHY

    def test_service_status_invalid_value(self) -> None:
        """Test that invalid values raise ValueError."""
        with pytest.raises(ValueError, match="'INVALID' is not a valid ServiceStatus"):
            ServiceStatus("INVALID")

    def test_service_status_iteration(self) -> None:
        """Test iterating over enum values."""
        statuses = list(ServiceStatus)
        assert len(statuses) == 3
        assert ServiceStatus.ONLINE in statuses
        assert ServiceStatus.OFFLINE in statuses
        assert ServiceStatus.UNHEALTHY in statuses

    def test_service_status_comparison(self) -> None:
        """Test enum comparison."""
        assert ServiceStatus.ONLINE == ServiceStatus.ONLINE
        assert ServiceStatus.ONLINE != ServiceStatus.OFFLINE
        assert ServiceStatus.OFFLINE != ServiceStatus.UNHEALTHY

    def test_service_status_string_representation(self) -> None:
        """Test string representation of enum."""
        assert str(ServiceStatus.ONLINE) == "ServiceStatus.ONLINE"
        assert repr(ServiceStatus.ONLINE) == "<ServiceStatus.ONLINE: 'ONLINE'>"
