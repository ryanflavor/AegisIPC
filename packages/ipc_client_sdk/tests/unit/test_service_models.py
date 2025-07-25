"""Unit tests for service registration and discovery data models."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from ipc_client_sdk.models.service_models import (
    ServiceInfo,
    ServiceInstanceInfo,
    ServiceListResponse,
    ServiceRegistrationRequest,
    ServiceRegistrationResponse,
)
from pydantic import ValidationError


class TestServiceRegistrationRequest:
    """Tests for ServiceRegistrationRequest model."""

    def test_valid_registration_request(self) -> None:
        """Test creating a valid registration request."""
        request = ServiceRegistrationRequest(
            service_name="user-service",
            instance_id="usr_srv_01_abc123",
            metadata={"version": "1.0.0", "region": "us-east-1"},
        )

        assert request.service_name == "user-service"
        assert request.instance_id == "usr_srv_01_abc123"
        assert request.metadata == {"version": "1.0.0", "region": "us-east-1"}

    def test_registration_request_minimal(self) -> None:
        """Test creating registration request with minimal data."""
        request = ServiceRegistrationRequest(
            service_name="test-service",
            instance_id="test_instance_01",
        )

        assert request.service_name == "test-service"
        assert request.instance_id == "test_instance_01"
        assert request.metadata == {}

    def test_registration_request_strips_whitespace(self) -> None:
        """Test that service name and instance ID are stripped of whitespace."""
        request = ServiceRegistrationRequest(
            service_name="  test-service  ",
            instance_id="  test_instance  ",
        )

        assert request.service_name == "test-service"
        assert request.instance_id == "test_instance"

    def test_registration_request_empty_service_name(self) -> None:
        """Test that empty service name raises validation error."""
        with pytest.raises(ValidationError) as exc_info:
            ServiceRegistrationRequest(
                service_name="",
                instance_id="test_instance",
            )

        errors = exc_info.value.errors()
        assert len(errors) == 1
        assert errors[0]["loc"] == ("service_name",)
        assert "Value must not be empty" in errors[0]["msg"]

    def test_registration_request_whitespace_only_service_name(self) -> None:
        """Test that whitespace-only service name raises validation error."""
        with pytest.raises(ValidationError) as exc_info:
            ServiceRegistrationRequest(
                service_name="   ",
                instance_id="test_instance",
            )

        errors = exc_info.value.errors()
        assert len(errors) == 1
        assert errors[0]["loc"] == ("service_name",)
        assert "Value must not be empty" in errors[0]["msg"]

    def test_registration_request_empty_instance_id(self) -> None:
        """Test that empty instance ID raises validation error."""
        with pytest.raises(ValidationError) as exc_info:
            ServiceRegistrationRequest(
                service_name="test-service",
                instance_id="",
            )

        errors = exc_info.value.errors()
        assert len(errors) == 1
        assert errors[0]["loc"] == ("instance_id",)
        assert "Value must not be empty" in errors[0]["msg"]

    def test_registration_request_short_instance_id(self) -> None:
        """Test that instance ID shorter than 8 characters raises validation error."""
        with pytest.raises(ValidationError) as exc_info:
            ServiceRegistrationRequest(
                service_name="test-service",
                instance_id="short",
            )

        errors = exc_info.value.errors()
        assert len(errors) == 1
        assert errors[0]["loc"] == ("instance_id",)
        assert "Instance ID must be at least 8 characters" in errors[0]["msg"]

    def test_registration_request_exactly_8_chars_instance_id(self) -> None:
        """Test that instance ID with exactly 8 characters is valid."""
        request = ServiceRegistrationRequest(
            service_name="test-service",
            instance_id="12345678",
        )

        assert request.instance_id == "12345678"

    def test_registration_request_json_serialization(self) -> None:
        """Test JSON serialization of registration request."""
        request = ServiceRegistrationRequest(
            service_name="user-service",
            instance_id="usr_srv_01_abc123",
            metadata={"version": "1.0.0"},
        )

        json_data = request.model_dump()
        assert json_data == {
            "service_name": "user-service",
            "instance_id": "usr_srv_01_abc123",
            "role": "standby",  # Default role
            "metadata": {"version": "1.0.0"},
        }

    def test_registration_request_from_json(self) -> None:
        """Test creating registration request from JSON data."""
        json_data = {
            "service_name": "user-service",
            "instance_id": "usr_srv_01_abc123",
            "metadata": {"version": "1.0.0"},
        }

        request = ServiceRegistrationRequest(**json_data)
        assert request.service_name == "user-service"
        assert request.instance_id == "usr_srv_01_abc123"
        assert request.metadata == {"version": "1.0.0"}
        assert request.role == "standby"  # Default role

    def test_registration_request_with_role(self) -> None:
        """Test creating registration request with role."""
        # Test with active role
        active_request = ServiceRegistrationRequest(
            service_name="user-service",
            instance_id="usr_srv_01_abc123",
            role="active",
        )
        assert active_request.role == "active"

        # Test with standby role
        standby_request = ServiceRegistrationRequest(
            service_name="user-service",
            instance_id="usr_srv_02_abc123",
            role="standby",
        )
        assert standby_request.role == "standby"

        # Test default role when not specified
        default_request = ServiceRegistrationRequest(
            service_name="user-service",
            instance_id="usr_srv_03_abc123",
        )
        assert default_request.role == "standby"

    def test_registration_request_invalid_role(self) -> None:
        """Test that invalid role raises validation error."""
        with pytest.raises(ValidationError) as exc_info:
            ServiceRegistrationRequest(
                service_name="user-service",
                instance_id="usr_srv_01_abc123",
                role="invalid",  # type: ignore
            )

        errors = exc_info.value.errors()
        assert len(errors) == 1
        assert errors[0]["loc"] == ("role",)


class TestServiceRegistrationResponse:
    """Tests for ServiceRegistrationResponse model."""

    def test_valid_registration_response(self) -> None:
        """Test creating a valid registration response."""
        now = datetime.now(UTC)
        response = ServiceRegistrationResponse(
            success=True,
            service_name="user-service",
            instance_id="usr_srv_01_abc123",
            role="ACTIVE",
            registered_at=now,
            message="Service instance registered successfully",
        )

        assert response.success is True
        assert response.service_name == "user-service"
        assert response.instance_id == "usr_srv_01_abc123"
        assert response.role == "ACTIVE"
        assert response.registered_at == now
        assert response.message == "Service instance registered successfully"

    def test_registration_response_without_message(self) -> None:
        """Test registration response without optional message."""
        now = datetime.now(UTC)
        response = ServiceRegistrationResponse(
            success=True,
            service_name="test-service",
            instance_id="test_01",
            role="STANDBY",
            registered_at=now,
        )

        assert response.success is True
        assert response.role == "STANDBY"
        assert response.message is None

    def test_registration_response_failure(self) -> None:
        """Test registration response for failure case."""
        now = datetime.now(UTC)
        response = ServiceRegistrationResponse(
            success=False,
            service_name="test-service",
            instance_id="test_01",
            role="ACTIVE",
            registered_at=now,
            message="Service already registered",
        )

        assert response.success is False
        assert response.role == "ACTIVE"
        assert response.message == "Service already registered"

    def test_registration_response_json_serialization(self) -> None:
        """Test JSON serialization of registration response."""
        now = datetime.now(UTC)
        response = ServiceRegistrationResponse(
            success=True,
            service_name="user-service",
            instance_id="usr_srv_01",
            registered_at=now,
            message="Success",
        )

        json_data = response.model_dump()
        assert json_data["success"] is True
        assert json_data["service_name"] == "user-service"
        assert json_data["instance_id"] == "usr_srv_01"
        assert json_data["registered_at"] == now
        assert json_data["message"] == "Success"


class TestServiceInstanceInfo:
    """Tests for ServiceInstanceInfo model."""

    def test_valid_service_instance_info(self) -> None:
        """Test creating valid service instance info."""
        now = datetime.now(UTC)
        info = ServiceInstanceInfo(
            instance_id="instance_01",
            status="ONLINE",
            registered_at=now,
            last_heartbeat=now,
            metadata={"version": "1.0.0"},
        )

        assert info.instance_id == "instance_01"
        assert info.status == "ONLINE"
        assert info.registered_at == now
        assert info.last_heartbeat == now
        assert info.metadata == {"version": "1.0.0"}

    def test_service_instance_info_minimal(self) -> None:
        """Test creating service instance info with minimal data."""
        now = datetime.now(UTC)
        info = ServiceInstanceInfo(
            instance_id="instance_01",
            status="OFFLINE",
            registered_at=now,
            last_heartbeat=now,
        )

        assert info.instance_id == "instance_01"
        assert info.status == "OFFLINE"
        assert info.metadata == {}
        assert info.role is None  # Default role

    def test_service_instance_info_with_role(self) -> None:
        """Test creating service instance info with role."""
        now = datetime.now(UTC)

        # Test with ACTIVE role
        active_info = ServiceInstanceInfo(
            instance_id="active_instance",
            status="ONLINE",
            role="ACTIVE",
            registered_at=now,
            last_heartbeat=now,
        )
        assert active_info.role == "ACTIVE"

        # Test with STANDBY role
        standby_info = ServiceInstanceInfo(
            instance_id="standby_instance",
            status="ONLINE",
            role="STANDBY",
            registered_at=now,
            last_heartbeat=now,
        )
        assert standby_info.role == "STANDBY"

    def test_service_instance_info_all_statuses(self) -> None:
        """Test service instance info with all possible statuses."""
        now = datetime.now(UTC)

        for status in ["ONLINE", "OFFLINE", "UNHEALTHY"]:
            info = ServiceInstanceInfo(
                instance_id="instance_01",
                status=status,
                registered_at=now,
                last_heartbeat=now,
            )
            assert info.status == status


class TestServiceInfo:
    """Tests for ServiceInfo model."""

    def test_valid_service_info(self) -> None:
        """Test creating valid service info."""
        now = datetime.now(UTC)
        instance1 = ServiceInstanceInfo(
            instance_id="instance_01",
            status="ONLINE",
            registered_at=now,
            last_heartbeat=now,
        )
        instance2 = ServiceInstanceInfo(
            instance_id="instance_02",
            status="OFFLINE",
            registered_at=now,
            last_heartbeat=now,
        )

        service = ServiceInfo(
            name="user-service",
            instances=[instance1, instance2],
            created_at=now,
            metadata={"owner": "team-a"},
        )

        assert service.name == "user-service"
        assert len(service.instances) == 2
        assert service.instances[0] == instance1
        assert service.instances[1] == instance2
        assert service.created_at == now
        assert service.metadata == {"owner": "team-a"}

    def test_service_info_empty_instances(self) -> None:
        """Test service info with no instances."""
        now = datetime.now(UTC)
        service = ServiceInfo(
            name="test-service",
            instances=[],
            created_at=now,
        )

        assert service.name == "test-service"
        assert service.instances == []
        assert service.metadata == {}

    def test_service_info_instance_count_property(self) -> None:
        """Test instance_count property."""
        now = datetime.now(UTC)
        service = ServiceInfo(
            name="test-service",
            instances=[],
            created_at=now,
        )

        assert service.instance_count == 0

        # Add instances
        for i in range(3):
            instance = ServiceInstanceInfo(
                instance_id=f"instance_{i}",
                status="ONLINE",
                registered_at=now,
                last_heartbeat=now,
            )
            service.instances.append(instance)

        assert service.instance_count == 3

    def test_service_info_healthy_instance_count_property(self) -> None:
        """Test healthy_instance_count property."""
        now = datetime.now(UTC)
        online1 = ServiceInstanceInfo(
            instance_id="online_01",
            status="ONLINE",
            registered_at=now,
            last_heartbeat=now,
        )
        online2 = ServiceInstanceInfo(
            instance_id="online_02",
            status="ONLINE",
            registered_at=now,
            last_heartbeat=now,
        )
        offline = ServiceInstanceInfo(
            instance_id="offline_01",
            status="OFFLINE",
            registered_at=now,
            last_heartbeat=now,
        )
        unhealthy = ServiceInstanceInfo(
            instance_id="unhealthy_01",
            status="UNHEALTHY",
            registered_at=now,
            last_heartbeat=now,
        )

        service = ServiceInfo(
            name="test-service",
            instances=[online1, online2, offline, unhealthy],
            created_at=now,
        )

        assert service.instance_count == 4
        assert service.healthy_instance_count == 2  # Only ONLINE instances


class TestServiceListResponse:
    """Tests for ServiceListResponse model."""

    def test_valid_service_list_response(self) -> None:
        """Test creating valid service list response."""
        now = datetime.now(UTC)
        instance = ServiceInstanceInfo(
            instance_id="instance_01",
            status="ONLINE",
            registered_at=now,
            last_heartbeat=now,
        )
        service = ServiceInfo(
            name="user-service",
            instances=[instance],
            created_at=now,
        )

        response = ServiceListResponse(
            services=[service],
            total_count=1,
        )

        assert len(response.services) == 1
        assert response.services[0] == service
        assert response.total_count == 1

    def test_service_list_response_empty(self) -> None:
        """Test empty service list response."""
        response = ServiceListResponse(
            services=[],
            total_count=0,
        )

        assert response.services == []
        assert response.total_count == 0

    def test_service_list_response_multiple_services(self) -> None:
        """Test service list response with multiple services."""
        now = datetime.now(UTC)
        services = []

        for i in range(3):
            instance = ServiceInstanceInfo(
                instance_id=f"instance_{i}",
                status="ONLINE",
                registered_at=now,
                last_heartbeat=now,
            )
            service = ServiceInfo(
                name=f"service_{i}",
                instances=[instance],
                created_at=now,
            )
            services.append(service)

        response = ServiceListResponse(
            services=services,
            total_count=3,
        )

        assert len(response.services) == 3
        assert response.total_count == 3

    def test_service_list_response_json_serialization(self) -> None:
        """Test JSON serialization of service list response."""
        now = datetime.now(UTC)
        instance = ServiceInstanceInfo(
            instance_id="instance_01",
            status="ONLINE",
            registered_at=now,
            last_heartbeat=now,
        )
        service = ServiceInfo(
            name="user-service",
            instances=[instance],
            created_at=now,
        )

        response = ServiceListResponse(
            services=[service],
            total_count=1,
        )

        json_data = response.model_dump()
        assert json_data["total_count"] == 1
        assert len(json_data["services"]) == 1
        assert json_data["services"][0]["name"] == "user-service"
