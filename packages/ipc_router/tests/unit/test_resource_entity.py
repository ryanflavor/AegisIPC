"""Unit tests for Resource domain entity."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ipc_router.domain.entities import Resource, ResourceMetadata


class TestResourceMetadata:
    """Test ResourceMetadata value object."""

    def test_create_minimal_metadata(self) -> None:
        """Test creating metadata with minimal required fields."""
        metadata = ResourceMetadata(
            resource_type="user_session",
            version=1,
            created_by="test-service",
            last_modified=datetime.now(UTC),
        )

        assert metadata.resource_type == "user_session"
        assert metadata.version == 1
        assert metadata.created_by == "test-service"
        assert metadata.tags == []
        assert metadata.attributes == {}
        assert metadata.ttl_seconds is None
        assert metadata.priority == 0

    def test_create_full_metadata(self) -> None:
        """Test creating metadata with all fields."""
        now = datetime.now(UTC)
        metadata = ResourceMetadata(
            resource_type="document",
            version=2,
            tags=["active", "shared"],
            attributes={"owner": "user123", "size": 1024},
            created_by="doc-service",
            last_modified=now,
            ttl_seconds=3600,
            priority=5,
        )

        assert metadata.resource_type == "document"
        assert metadata.version == 2
        assert metadata.tags == ["active", "shared"]
        assert metadata.attributes == {"owner": "user123", "size": 1024}
        assert metadata.created_by == "doc-service"
        assert metadata.last_modified == now
        assert metadata.ttl_seconds == 3600
        assert metadata.priority == 5

    def test_metadata_is_expired(self) -> None:
        """Test checking if metadata is expired based on TTL."""
        # Create metadata with 1 hour TTL, registered 2 hours ago
        past_time = datetime.now(UTC) - timedelta(hours=2)
        metadata = ResourceMetadata(
            resource_type="session",
            version=1,
            created_by="auth-service",
            last_modified=past_time,
            ttl_seconds=3600,  # 1 hour
        )

        # Resource should be expired since it was registered 2 hours ago with 1 hour TTL
        assert metadata.is_expired()

        # Create metadata with no TTL (permanent)
        permanent_metadata = ResourceMetadata(
            resource_type="config",
            version=1,
            created_by="config-service",
            last_modified=past_time,
            ttl_seconds=None,
        )

        # Permanent resource should never expire
        assert not permanent_metadata.is_expired()

        # Create metadata with future expiry
        recent_time = datetime.now(UTC) - timedelta(minutes=30)
        recent_metadata = ResourceMetadata(
            resource_type="cache",
            version=1,
            created_by="cache-service",
            last_modified=recent_time,
            ttl_seconds=3600,  # 1 hour
        )

        # Resource registered 30 minutes ago with 1 hour TTL should not be expired
        assert not recent_metadata.is_expired()

    def test_metadata_equality(self) -> None:
        """Test metadata equality comparison."""
        now = datetime.now(UTC)
        metadata1 = ResourceMetadata(
            resource_type="user",
            version=1,
            created_by="user-service",
            last_modified=now,
        )

        metadata2 = ResourceMetadata(
            resource_type="user",
            version=1,
            created_by="user-service",
            last_modified=now,
        )

        metadata3 = ResourceMetadata(
            resource_type="user",
            version=2,  # Different version
            created_by="user-service",
            last_modified=now,
        )

        assert metadata1 == metadata2
        assert metadata1 != metadata3


class TestResource:
    """Test Resource entity."""

    def test_create_resource(self) -> None:
        """Test creating a resource with required fields."""
        now = datetime.now(UTC)
        metadata = ResourceMetadata(
            resource_type="user_session",
            version=1,
            created_by="auth-service",
            last_modified=now,
        )

        resource = Resource(
            resource_id="user-123",
            owner_instance_id="instance-1",
            service_name="user-service",
            registered_at=now,
            metadata=metadata,
        )

        assert resource.resource_id == "user-123"
        assert resource.owner_instance_id == "instance-1"
        assert resource.service_name == "user-service"
        assert resource.registered_at == now
        assert resource.metadata == metadata

    def test_resource_is_expired(self) -> None:
        """Test checking if resource is expired."""
        # Create expired resource
        past_time = datetime.now(UTC) - timedelta(hours=2)
        metadata = ResourceMetadata(
            resource_type="session",
            version=1,
            created_by="auth-service",
            last_modified=past_time,
            ttl_seconds=3600,  # 1 hour TTL
        )

        resource = Resource(
            resource_id="session-456",
            owner_instance_id="auth-instance-1",
            service_name="auth-service",
            registered_at=past_time,
            metadata=metadata,
        )

        assert resource.is_expired()

        # Create non-expired resource
        recent_time = datetime.now(UTC) - timedelta(minutes=30)
        recent_metadata = ResourceMetadata(
            resource_type="cache",
            version=1,
            created_by="cache-service",
            last_modified=recent_time,
            ttl_seconds=3600,  # 1 hour TTL
        )

        recent_resource = Resource(
            resource_id="cache-789",
            owner_instance_id="cache-instance-1",
            service_name="cache-service",
            registered_at=recent_time,
            metadata=recent_metadata,
        )

        assert not recent_resource.is_expired()

    def test_resource_without_metadata(self) -> None:
        """Test creating resource without metadata."""
        now = datetime.now(UTC)
        resource = Resource(
            resource_id="res-001",
            owner_instance_id="instance-1",
            service_name="test-service",
            registered_at=now,
            metadata=None,
        )

        assert resource.resource_id == "res-001"
        assert resource.owner_instance_id == "instance-1"
        assert resource.service_name == "test-service"
        assert resource.registered_at == now
        assert resource.metadata is None
        assert not resource.is_expired()  # Resources without metadata never expire

    def test_resource_equality(self) -> None:
        """Test resource equality based on resource_id."""
        now = datetime.now(UTC)
        metadata = ResourceMetadata(
            resource_type="doc",
            version=1,
            created_by="doc-service",
            last_modified=now,
        )

        resource1 = Resource(
            resource_id="doc-123",
            owner_instance_id="instance-1",
            service_name="doc-service",
            registered_at=now,
            metadata=metadata,
        )

        resource2 = Resource(
            resource_id="doc-123",  # Same resource_id
            owner_instance_id="instance-2",  # Different owner
            service_name="doc-service",
            registered_at=now,
            metadata=metadata,
        )

        resource3 = Resource(
            resource_id="doc-456",  # Different resource_id
            owner_instance_id="instance-1",
            service_name="doc-service",
            registered_at=now,
            metadata=metadata,
        )

        # Resources are equal if they have the same resource_id
        assert resource1 == resource2
        assert resource1 != resource3

    def test_resource_hash(self) -> None:
        """Test resource can be used in sets and dicts."""
        now = datetime.now(UTC)
        resource1 = Resource(
            resource_id="res-1",
            owner_instance_id="instance-1",
            service_name="service-1",
            registered_at=now,
        )

        resource2 = Resource(
            resource_id="res-1",  # Same ID
            owner_instance_id="instance-2",
            service_name="service-1",
            registered_at=now,
        )

        resource3 = Resource(
            resource_id="res-2",  # Different ID
            owner_instance_id="instance-1",
            service_name="service-1",
            registered_at=now,
        )

        # Test in set
        resource_set = {resource1, resource2, resource3}
        assert len(resource_set) == 2  # resource1 and resource2 are considered the same

        # Test as dict key
        resource_dict = {resource1: "value1", resource2: "value2", resource3: "value3"}
        assert len(resource_dict) == 2
        assert resource_dict[resource1] == "value2"  # resource2 overwrote resource1

    def test_resource_repr(self) -> None:
        """Test resource string representation."""
        now = datetime.now(UTC)
        resource = Resource(
            resource_id="test-resource",
            owner_instance_id="test-instance",
            service_name="test-service",
            registered_at=now,
        )

        repr_str = repr(resource)
        assert "test-resource" in repr_str
        assert "test-instance" in repr_str
        assert "test-service" in repr_str
