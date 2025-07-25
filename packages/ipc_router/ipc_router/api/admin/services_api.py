"""Service management REST API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse
from ipc_client_sdk.models import ServiceInfo, ServiceListResponse
from pydantic import BaseModel, Field

from ipc_router.application.services import ServiceRegistry
from ipc_router.domain.exceptions import NotFoundError
from ipc_router.infrastructure.logging import get_logger

logger = get_logger(__name__)


class ServiceRoleInfo(BaseModel):
    """Information about service instances by role."""

    service_name: str = Field(..., description="Name of the service")
    active_instances: list[str] = Field(
        default_factory=list, description="List of active instance IDs"
    )
    standby_instances: list[str] = Field(
        default_factory=list, description="List of standby instance IDs"
    )


class ServiceRolesResponse(BaseModel):
    """Response containing role information for a service."""

    service_name: str = Field(..., description="Name of the service")
    roles: ServiceRoleInfo = Field(..., description="Role information")


def create_services_router(service_registry: ServiceRegistry) -> APIRouter:
    """Create the services management router.

    Args:
        service_registry: Service registry instance

    Returns:
        Configured FastAPI router
    """
    router = APIRouter(
        prefix="/api/v1/admin",
        tags=["Service Management"],
        responses={
            404: {"description": "Service not found"},
            500: {"description": "Internal server error"},
        },
    )

    @router.get(  # type: ignore[misc]
        "/services",
        response_model=ServiceListResponse,
        summary="List all registered services",
        description="Retrieve a list of all registered services and their instances",
    )
    async def list_services() -> ServiceListResponse:
        """List all registered services.

        Returns:
            ServiceListResponse containing all services and their instances
        """
        try:
            logger.info("Listing all services")
            response = await service_registry.list_services()

            logger.debug(
                "Listed services",
                extra={
                    "service_count": response.total_count,
                    "services": [s.name for s in response.services],
                },
            )

            return response

        except Exception as e:
            logger.error(
                "Failed to list services",
                exc_info=e,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve services",
            ) from e

    @router.get(  # type: ignore[misc]
        "/services/{service_name}",
        response_model=ServiceInfo,
        summary="Get service details",
        description="Retrieve detailed information about a specific service",
        responses={
            200: {
                "description": "Service details",
                "model": ServiceInfo,
            },
        },
    )
    async def get_service(service_name: str) -> ServiceInfo:
        """Get information about a specific service.

        Args:
            service_name: Name of the service to retrieve

        Returns:
            ServiceInfo containing service details and instances

        Raises:
            HTTPException: 404 if service not found
        """
        try:
            logger.info(
                "Getting service details",
                extra={"service_name": service_name},
            )

            service_info = await service_registry.get_service(service_name)

            logger.debug(
                "Retrieved service details",
                extra={
                    "service_name": service_name,
                    "instance_count": service_info.instance_count,
                },
            )

            return service_info

        except NotFoundError:
            logger.warning(
                "Service not found",
                extra={"service_name": service_name},
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Service '{service_name}' not found",
            ) from None
        except Exception as e:
            logger.error(
                "Failed to get service",
                exc_info=e,
                extra={"service_name": service_name},
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve service information",
            ) from e

    @router.get(  # type: ignore[misc]
        "/health",
        summary="Check system health",
        description="Get health status of all registered services",
    )
    async def check_health() -> JSONResponse:
        """Check the health of all services.

        Returns:
            JSON response with health status
        """
        try:
            health_status = await service_registry.check_health()

            # Determine overall health
            is_healthy = health_status["health_percentage"] >= 80

            return JSONResponse(
                status_code=(
                    status.HTTP_200_OK if is_healthy else status.HTTP_503_SERVICE_UNAVAILABLE
                ),
                content={
                    "status": "healthy" if is_healthy else "unhealthy",
                    **health_status,
                },
            )

        except Exception as e:
            logger.error(
                "Health check failed",
                exc_info=e,
            )
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={
                    "status": "error",
                    "error": str(e),
                },
            )

    @router.get(  # type: ignore[misc]
        "/services/{service_name}/roles",
        response_model=ServiceRolesResponse,
        summary="Get service role information",
        description="Retrieve active/standby role information for a specific service",
        responses={
            200: {
                "description": "Service role details",
                "model": ServiceRolesResponse,
            },
        },
    )
    async def get_service_roles(service_name: str) -> ServiceRolesResponse:
        """Get role information for a specific service.

        Args:
            service_name: Name of the service to retrieve role info for

        Returns:
            ServiceRolesResponse containing active/standby instance information

        Raises:
            HTTPException: 404 if service not found
        """
        try:
            from ipc_router.domain.enums import ServiceRole

            logger.info(
                "Getting service role information",
                extra={"service_name": service_name},
            )

            # Verify service exists first
            await service_registry.get_service(service_name)

            # Get instances by role using optimized method
            active_instances_data = await service_registry.get_instances_by_role(
                service_name, ServiceRole.ACTIVE
            )
            standby_instances_data = await service_registry.get_instances_by_role(
                service_name, ServiceRole.STANDBY
            )

            # Extract instance IDs
            active_instances = [inst.instance_id for inst in active_instances_data]
            standby_instances = [inst.instance_id for inst in standby_instances_data]

            # Also include instances with None role as standby (backward compatibility)
            service_info = await service_registry.get_service(service_name)
            for instance in service_info.instances:
                if instance.role is None and instance.instance_id not in standby_instances:
                    standby_instances.append(instance.instance_id)

            role_info = ServiceRoleInfo(
                service_name=service_name,
                active_instances=active_instances,
                standby_instances=standby_instances,
            )

            logger.debug(
                "Retrieved service role information",
                extra={
                    "service_name": service_name,
                    "active_count": len(active_instances),
                    "standby_count": len(standby_instances),
                },
            )

            return ServiceRolesResponse(
                service_name=service_name,
                roles=role_info,
            )

        except NotFoundError:
            logger.warning(
                "Service not found",
                extra={"service_name": service_name},
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Service '{service_name}' not found",
            ) from None
        except Exception as e:
            logger.error(
                "Failed to get service role information",
                exc_info=e,
                extra={"service_name": service_name},
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve service role information",
            ) from e

    return router


def create_admin_router(service_registry: ServiceRegistry) -> APIRouter:
    """Create the complete admin router with all sub-routers.

    Args:
        service_registry: Service registry instance

    Returns:
        Configured FastAPI router with all admin endpoints
    """
    admin_router = APIRouter()

    # Include services router
    services_router = create_services_router(service_registry)
    admin_router.include_router(services_router)

    return admin_router
