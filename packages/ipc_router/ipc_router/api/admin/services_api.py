"""Service management REST API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse
from ipc_client_sdk.models import ServiceInfo, ServiceListResponse

from ...application.services import ServiceRegistry
from ...domain.exceptions import NotFoundError
from ...infrastructure.logging import get_logger

logger = get_logger(__name__)


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

    @router.get(
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

    @router.get(
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

    @router.get(
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
