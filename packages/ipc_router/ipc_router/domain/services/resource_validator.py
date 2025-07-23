"""Domain service for resource ownership validation.

This module provides validation logic for resource operations,
ensuring ownership rules and constraints are enforced.
"""

from __future__ import annotations

from ipc_router.domain.entities import ResourceMetadata
from ipc_router.domain.entities.resource import Resource
from ipc_router.domain.exceptions import (
    ResourceLimitExceededError,
    ResourceOwnershipError,
    ValidationError,
)


class ResourceValidator:
    """Validates resource ownership and constraints."""

    def __init__(self, max_resources_per_instance: int = 1000) -> None:
        """Initialize the resource validator.

        Args:
            max_resources_per_instance: Maximum resources allowed per instance
        """
        self.max_resources_per_instance = max_resources_per_instance

    def validate_ownership(
        self, resource: Resource, instance_id: str, operation: str = "operate on"
    ) -> None:
        """Validate that an instance owns a resource.

        Args:
            resource: The resource to validate
            instance_id: The instance claiming ownership
            operation: Description of the operation being attempted

        Raises:
            ResourceOwnershipError: If the instance doesn't own the resource
        """
        if not resource.is_owned_by(instance_id):
            raise ResourceOwnershipError(
                resource_id=resource.resource_id,
                instance_id=instance_id,
                actual_owner=resource.owner_instance_id,
            )

    def validate_resource_id(self, resource_id: str) -> None:
        """Validate resource ID format.

        Args:
            resource_id: The resource ID to validate

        Raises:
            ValidationError: If the resource ID is invalid
        """
        if not resource_id or not resource_id.strip():
            raise ValidationError("Resource ID cannot be empty")

        # Check max length
        if len(resource_id) > 255:
            raise ValidationError("Resource ID exceeds maximum length of 255 characters")

        # Ensure resource ID doesn't contain problematic characters
        # Check for whitespace and control characters
        if any(char in resource_id for char in ["\n", "\r", "\t", "\x00", " "]):
            raise ValidationError("Resource ID contains invalid characters")

        # Check for other special characters that might cause issues
        invalid_chars = [
            "/",
            "\\",
            "*",
            "?",
            '"',
            "<",
            ">",
            "|",
            "#",
            "%",
            "&",
            "{",
            "}",
            "$",
            "!",
            "`",
            "@",
            "+",
            "=",
        ]
        if any(char in resource_id for char in invalid_chars):
            raise ValidationError(
                f"Resource ID contains invalid character: {next(char for char in invalid_chars if char in resource_id)}"
            )

    def validate_resource_limit(
        self, instance_id: str, current_count: int, additional_count: int = 1
    ) -> None:
        """Validate that adding resources won't exceed the limit.

        Args:
            instance_id: The instance ID
            current_count: Current number of resources owned
            additional_count: Number of resources being added

        Raises:
            ResourceLimitExceededError: If the limit would be exceeded
        """
        new_total = current_count + additional_count
        if new_total > self.max_resources_per_instance:
            raise ResourceLimitExceededError(
                instance_id=instance_id,
                current_count=current_count,
                limit=self.max_resources_per_instance,
            )

    def can_force_ownership(
        self, resource: Resource | None, requesting_instance: str, force: bool
    ) -> bool:
        """Check if ownership can be forcefully taken.

        Args:
            resource: Existing resource (if any)
            requesting_instance: Instance requesting ownership
            force: Whether force flag is set

        Returns:
            True if ownership can be taken, False otherwise
        """
        # If resource doesn't exist, it can be claimed
        if resource is None:
            return True

        # If already owned by requesting instance, no conflict
        if resource.is_owned_by(requesting_instance):
            return True

        # Return True if force flag is set, False otherwise
        return force

    def validate_transfer(
        self, resource: Resource, from_instance_id: str, to_instance_id: str
    ) -> None:
        """Validate a resource transfer operation.

        Args:
            resource: The resource to transfer
            from_instance_id: Current owner instance ID
            to_instance_id: Target instance ID

        Raises:
            ResourceOwnershipError: If from_instance doesn't own the resource
            ValidationError: If attempting to transfer to same instance
        """
        # Validate current ownership
        self.validate_ownership(resource, from_instance_id, "transfer")

        # Allow transfer to same instance (no-op)
        # This simplifies client code that doesn't need to check if source == target

    def validate_service_name(self, service_name: str) -> None:
        """Validate service name format.

        Args:
            service_name: The service name to validate

        Raises:
            ValidationError: If the service name is invalid
        """
        if not service_name or not service_name.strip():
            raise ValidationError("Service name cannot be empty")

        # Check for invalid characters in service name
        if any(char in service_name for char in ["\n", "\r", "\t", "\x00", " "]):
            raise ValidationError("Service name contains invalid characters")

    def validate_instance_id(self, instance_id: str) -> None:
        """Validate instance ID format.

        Args:
            instance_id: The instance ID to validate

        Raises:
            ValidationError: If the instance ID is invalid
        """
        if not instance_id or not instance_id.strip():
            raise ValidationError("Instance ID cannot be empty")

        # Check for invalid characters in instance ID
        if any(char in instance_id for char in ["\n", "\r", "\t", "\x00", " "]):
            raise ValidationError("Instance ID contains invalid characters")

    def validate_metadata(self, metadata: ResourceMetadata) -> None:
        """Validate resource metadata.

        Args:
            metadata: The resource metadata to validate

        Raises:
            ValidationError: If the metadata is invalid
        """
        if not isinstance(metadata, ResourceMetadata):
            raise ValidationError("Metadata must be a ResourceMetadata instance")

        # Validate version
        if metadata.version < 1:
            raise ValidationError("Metadata version must be positive")

        # Validate TTL if set
        if metadata.ttl_seconds is not None and metadata.ttl_seconds < 0:
            raise ValidationError("TTL seconds cannot be negative")

        # Validate priority
        if metadata.priority < 0 or metadata.priority > 10:
            raise ValidationError("Priority must be between 0 and 10")

    def validate_resource(self, resource: Resource) -> None:
        """Validate a complete resource.

        Args:
            resource: The resource to validate

        Raises:
            ValidationError: If the resource is invalid
        """
        # Validate resource ID
        self.validate_resource_id(resource.resource_id)

        # Validate service name
        self.validate_service_name(resource.service_name)

        # Validate instance ID
        self.validate_instance_id(resource.owner_instance_id)

        # Validate metadata if present
        if resource.metadata:
            self.validate_metadata(resource.metadata)

    def can_transfer_resource(self, resource: Resource, to_instance_id: str) -> bool:
        """Check if a resource can be transferred to another instance.

        Args:
            resource: The resource to check
            to_instance_id: Target instance ID

        Returns:
            True if the resource can be transferred, False otherwise
        """
        # Can't transfer to same instance
        if resource.owner_instance_id == to_instance_id:
            return False

        # Check if resource is expired
        return not resource.is_expired()
