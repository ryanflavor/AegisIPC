"""Unit tests for ResourceValidator domain service."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from ipc_router.domain.entities import Resource, ResourceMetadata
from ipc_router.domain.exceptions import ValidationError
from ipc_router.domain.services import ResourceValidator


class TestResourceValidator:
    """Test ResourceValidator domain service."""

    @pytest.fixture
    def validator(self) -> ResourceValidator:
        """Create a ResourceValidator instance."""
        return ResourceValidator()

    @pytest.fixture
    def valid_metadata(self) -> ResourceMetadata:
        """Create valid resource metadata."""
        return ResourceMetadata(
            resource_type="user_session",
            version=1,
            created_by="auth-service",
            last_modified=datetime.now(UTC),
            ttl_seconds=3600,
            priority=5,
        )

    @pytest.fixture
    def valid_resource(self, valid_metadata: ResourceMetadata) -> Resource:
        """Create a valid resource."""
        return Resource(
            resource_id="user-123",
            owner_instance_id="instance-1",
            service_name="user-service",
            registered_at=datetime.now(UTC),
            metadata=valid_metadata,
        )

    def test_validate_resource_id_valid(self, validator: ResourceValidator) -> None:
        """Test validating valid resource IDs."""
        # Valid resource IDs
        valid_ids = [
            "user-123",
            "session_456",
            "doc.789",
            "cache:key:001",
            "a",  # Single character
            "A-B_C.D:E",  # Mixed case and allowed special chars
            "12345",  # Numbers only
        ]

        for resource_id in valid_ids:
            # Should not raise
            validator.validate_resource_id(resource_id)

    def test_validate_resource_id_invalid(self, validator: ResourceValidator) -> None:
        """Test validating invalid resource IDs."""
        # Invalid resource IDs
        invalid_ids = [
            "",  # Empty
            " ",  # Whitespace only
            "user 123",  # Contains space
            "user\t123",  # Contains tab
            "user\n123",  # Contains newline
            "user@123",  # Invalid character
            "user#123",  # Invalid character
            "user$123",  # Invalid character
            "user%123",  # Invalid character
            "user&123",  # Invalid character
            "user*123",  # Invalid character
            "user/123",  # Invalid character
            "user\\123",  # Invalid character
            "user|123",  # Invalid character
            "user<123",  # Invalid character
            "user>123",  # Invalid character
            " user-123",  # Leading space
            "user-123 ",  # Trailing space
        ]

        for resource_id in invalid_ids:
            with pytest.raises(ValidationError):
                validator.validate_resource_id(resource_id)

    def test_validate_resource_id_too_long(self, validator: ResourceValidator) -> None:
        """Test validating resource ID that exceeds max length."""
        # Create a resource ID longer than 255 characters
        long_id = "a" * 256

        with pytest.raises(ValidationError) as exc_info:
            validator.validate_resource_id(long_id)
        assert "Resource ID exceeds maximum length of 255 characters" in str(exc_info.value)

        # Max length should be fine
        max_length_id = "a" * 255
        validator.validate_resource_id(max_length_id)  # Should not raise

    def test_validate_service_name_valid(self, validator: ResourceValidator) -> None:
        """Test validating valid service names."""
        valid_names = [
            "user-service",
            "auth_service",
            "api.gateway",
            "service-v2",
            "Service123",
            "a",  # Single character
        ]

        for service_name in valid_names:
            validator.validate_service_name(service_name)

    def test_validate_service_name_invalid(self, validator: ResourceValidator) -> None:
        """Test validating invalid service names."""
        # Test empty service names
        empty_names = ["", " "]
        for service_name in empty_names:
            with pytest.raises(ValidationError) as exc_info:
                validator.validate_service_name(service_name)
            assert "Service name cannot be empty" in str(exc_info.value)

        # Test service names with invalid characters (whitespace and control chars)
        invalid_char_names = [
            "service name",  # Contains space
            "service\tname",  # Contains tab
            "service\nname",  # Contains newline
            "service\rname",  # Contains carriage return
            " service",  # Leading space
            "service ",  # Trailing space
        ]
        for service_name in invalid_char_names:
            with pytest.raises(ValidationError) as exc_info:
                validator.validate_service_name(service_name)
            assert "Service name contains invalid characters" in str(exc_info.value)

    def test_validate_instance_id_valid(self, validator: ResourceValidator) -> None:
        """Test validating valid instance IDs."""
        valid_ids = [
            "instance-1",
            "instance_2",
            "host.domain.com",
            "192.168.1.1",
            "pod-abc123-xyz",
            "i",  # Single character
        ]

        for instance_id in valid_ids:
            validator.validate_instance_id(instance_id)

    def test_validate_instance_id_invalid(self, validator: ResourceValidator) -> None:
        """Test validating invalid instance IDs."""
        # Test empty instance IDs
        empty_ids = ["", " "]
        for instance_id in empty_ids:
            with pytest.raises(ValidationError) as exc_info:
                validator.validate_instance_id(instance_id)
            assert "Instance ID cannot be empty" in str(exc_info.value)

        # Test instance IDs with invalid characters (whitespace and control chars)
        invalid_char_ids = [
            "instance id",  # Contains space
            "instance\tid",  # Contains tab
            "instance\nid",  # Contains newline
            "instance\rid",  # Contains carriage return
            " instance",  # Leading space
            "instance ",  # Trailing space
        ]
        for instance_id in invalid_char_ids:
            with pytest.raises(ValidationError) as exc_info:
                validator.validate_instance_id(instance_id)
            assert "Instance ID contains invalid characters" in str(exc_info.value)

    def test_validate_metadata_valid(
        self, validator: ResourceValidator, valid_metadata: ResourceMetadata
    ) -> None:
        """Test validating valid metadata."""
        # Should not raise
        validator.validate_metadata(valid_metadata)

        # Test with minimal metadata
        minimal_metadata = ResourceMetadata(
            resource_type="session",
            version=1,
            created_by="auth",
            last_modified=datetime.now(UTC),
        )
        validator.validate_metadata(minimal_metadata)

    def test_validate_metadata_invalid_version(
        self, validator: ResourceValidator, valid_metadata: ResourceMetadata
    ) -> None:
        """Test validating metadata with invalid version."""
        # Negative version - ResourceMetadata raises ValueError in __post_init__
        with pytest.raises(ValueError) as exc_info:
            metadata = ResourceMetadata(
                resource_type="session",
                version=-1,
                created_by="auth",
                last_modified=datetime.now(UTC),
            )
        assert "Version must be non-negative" in str(exc_info.value)

        # Zero version is valid for ResourceMetadata but invalid for validator
        metadata = ResourceMetadata(
            resource_type="session",
            version=0,
            created_by="auth",
            last_modified=datetime.now(UTC),
        )
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_metadata(metadata)
        assert "Metadata version must be positive" in str(exc_info.value)

    def test_validate_metadata_invalid_ttl(
        self, validator: ResourceValidator, valid_metadata: ResourceMetadata
    ) -> None:
        """Test validating metadata with invalid TTL."""
        # Negative TTL - ResourceMetadata raises ValueError in __post_init__
        with pytest.raises(ValueError) as exc_info:
            metadata = ResourceMetadata(
                resource_type="session",
                version=1,
                created_by="auth",
                last_modified=datetime.now(UTC),
                ttl_seconds=-1,
            )
        assert "TTL must be positive" in str(exc_info.value)

        # Zero TTL - ResourceMetadata raises ValueError in __post_init__
        with pytest.raises(ValueError) as exc_info:
            metadata = ResourceMetadata(
                resource_type="session",
                version=1,
                created_by="auth",
                last_modified=datetime.now(UTC),
                ttl_seconds=0,
            )
        assert "TTL must be positive" in str(exc_info.value)

        # Valid positive TTL should pass both ResourceMetadata and validator
        metadata = ResourceMetadata(
            resource_type="session",
            version=1,
            created_by="auth",
            last_modified=datetime.now(UTC),
            ttl_seconds=3600,
        )
        validator.validate_metadata(metadata)  # Should not raise

    def test_validate_metadata_invalid_priority(
        self, validator: ResourceValidator, valid_metadata: ResourceMetadata
    ) -> None:
        """Test validating metadata with invalid priority."""
        # Negative priority - ResourceMetadata raises ValueError in __post_init__
        with pytest.raises(ValueError) as exc_info:
            metadata = ResourceMetadata(
                resource_type="session",
                version=1,
                created_by="auth",
                last_modified=datetime.now(UTC),
                priority=-1,
            )
        assert "Priority must be between 0 and 100" in str(exc_info.value)

        # Priority too high - ResourceMetadata raises ValueError in __post_init__
        with pytest.raises(ValueError) as exc_info:
            metadata = ResourceMetadata(
                resource_type="session",
                version=1,
                created_by="auth",
                last_modified=datetime.now(UTC),
                priority=101,
            )
        assert "Priority must be between 0 and 100" in str(exc_info.value)

        # Priority between 11-100 passes ResourceMetadata but fails validator
        metadata = ResourceMetadata(
            resource_type="session",
            version=1,
            created_by="auth",
            last_modified=datetime.now(UTC),
            priority=50,
        )
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_metadata(metadata)
        assert "Priority must be between 0 and 10" in str(exc_info.value)

        # Valid priorities for both ResourceMetadata and validator
        for priority in [0, 1, 5, 10]:
            metadata = ResourceMetadata(
                resource_type="session",
                version=1,
                created_by="auth",
                last_modified=datetime.now(UTC),
                priority=priority,
            )
            validator.validate_metadata(metadata)  # Should not raise

    def test_validate_resource_valid(
        self, validator: ResourceValidator, valid_resource: Resource
    ) -> None:
        """Test validating a valid resource."""
        # Should not raise
        validator.validate_resource(valid_resource)

    def test_validate_resource_without_metadata(self, validator: ResourceValidator) -> None:
        """Test validating resource without metadata."""
        resource = Resource(
            resource_id="res-001",
            owner_instance_id="instance-1",
            service_name="test-service",
            registered_at=datetime.now(UTC),
            metadata=None,
        )

        # Should not raise - metadata is optional
        validator.validate_resource(resource)

    def test_validate_resource_invalid_fields(self, validator: ResourceValidator) -> None:
        """Test validating resource with invalid fields."""
        # Invalid resource ID
        resource = Resource(
            resource_id="invalid resource id",
            owner_instance_id="instance-1",
            service_name="test-service",
            registered_at=datetime.now(UTC),
        )

        with pytest.raises(ValidationError) as exc_info:
            validator.validate_resource(resource)
        assert "Resource ID contains invalid characters" in str(exc_info.value)

        # Invalid service name
        resource.resource_id = "valid-id"
        resource.service_name = "invalid service"

        with pytest.raises(ValidationError) as exc_info:
            validator.validate_resource(resource)
        assert "Service name contains invalid characters" in str(exc_info.value)

        # Invalid instance ID
        resource.service_name = "valid-service"
        resource.owner_instance_id = "invalid instance"

        with pytest.raises(ValidationError) as exc_info:
            validator.validate_resource(resource)
        assert "Instance ID contains invalid characters" in str(exc_info.value)

    def test_validate_resource_with_invalid_metadata(
        self, validator: ResourceValidator, valid_resource: Resource
    ) -> None:
        """Test validating resource with invalid metadata."""
        # Can't create invalid metadata directly due to __post_init__ validation
        # Test with metadata that passes ResourceMetadata validation but fails validator
        # The validator checks for version < 1 but ResourceMetadata allows version=0
        metadata = ResourceMetadata(
            resource_type="session",
            version=0,  # Valid for ResourceMetadata but invalid for validator
            created_by="auth",
            last_modified=datetime.now(UTC),
        )

        valid_resource.metadata = metadata

        with pytest.raises(ValidationError) as exc_info:
            validator.validate_resource(valid_resource)
        assert "Metadata version must be positive" in str(exc_info.value)

    def test_can_transfer_resource_valid(self, validator: ResourceValidator) -> None:
        """Test checking if resource can be transferred."""
        # Non-expired resource can be transferred
        metadata = ResourceMetadata(
            resource_type="session",
            version=1,
            created_by="auth",
            last_modified=datetime.now(UTC),
            ttl_seconds=3600,
        )

        resource = Resource(
            resource_id="session-123",
            owner_instance_id="instance-1",
            service_name="auth-service",
            registered_at=datetime.now(UTC),
            metadata=metadata,
        )

        assert validator.can_transfer_resource(resource, "instance-2")

    def test_can_transfer_resource_expired(self, validator: ResourceValidator) -> None:
        """Test that expired resources cannot be transferred."""
        # Create expired resource
        past_time = datetime.now(UTC) - timedelta(hours=2)
        metadata = ResourceMetadata(
            resource_type="session",
            version=1,
            created_by="auth",
            last_modified=past_time,
            ttl_seconds=3600,  # 1 hour TTL
        )

        resource = Resource(
            resource_id="session-123",
            owner_instance_id="instance-1",
            service_name="auth-service",
            registered_at=past_time,
            metadata=metadata,
        )

        assert not validator.can_transfer_resource(resource, "instance-2")

    def test_can_transfer_resource_same_instance(self, validator: ResourceValidator) -> None:
        """Test that resources cannot be transferred to the same instance."""
        resource = Resource(
            resource_id="res-123",
            owner_instance_id="instance-1",
            service_name="service",
            registered_at=datetime.now(UTC),
        )

        assert not validator.can_transfer_resource(resource, "instance-1")
