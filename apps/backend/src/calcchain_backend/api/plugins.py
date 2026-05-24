from __future__ import annotations

from fastapi import APIRouter, Depends

from calcchain_backend.dependencies import get_plugin_service
from calcchain_backend.schemas.plugin import PluginInfo, PluginListResponse, PluginPatchRequest
from calcchain_backend.services.plugin_service import PluginService

router = APIRouter()


@router.get("", response_model=PluginListResponse)
def list_plugins(service: PluginService = Depends(get_plugin_service)) -> PluginListResponse:
    return PluginListResponse(items=service.list_plugins())


@router.patch("/{plugin_id}", response_model=PluginInfo)
def patch_plugin(plugin_id: str, request: PluginPatchRequest, service: PluginService = Depends(get_plugin_service)) -> PluginInfo:
    return service.patch_plugin(plugin_id, enabled=request.enabled)
