from __future__ import annotations

from fastapi import APIRouter, Depends

from calcchain_backend import __version__
from calcchain_backend.dependencies import get_settings
from calcchain_backend.schemas.server import HealthResponse, ServerInfo
from calcchain_backend.settings import BackendSettings

router = APIRouter()


@router.get("/info", response_model=ServerInfo)
def get_server_info(settings: BackendSettings = Depends(get_settings)) -> ServerInfo:
    return ServerInfo(
        app=settings.app_name,
        version=__version__,
        api_version=settings.api_version,
        mode=settings.mode,
        auth_required=settings.auth_required,
    )


@router.get("/health", response_model=HealthResponse)
def get_server_health() -> HealthResponse:
    return HealthResponse(status="ok")
