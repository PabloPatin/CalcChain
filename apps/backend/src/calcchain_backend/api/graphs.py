from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from calcchain_backend.dependencies import get_core_runtime, get_graph_service, get_manifest_import_service, get_settings
from calcchain_backend.schemas.graph import (
    GraphCompileRequest,
    GraphCompileResponse,
    GraphManifestImportResponse,
    GraphValidateRequest,
    GraphValidateResponse,
)
from calcchain_backend.settings import BackendSettings
from calcchain_backend.services.graph_service import GraphService
from calcchain_backend.services.manifest_import_service import ManifestImportService

router = APIRouter()


@router.post("/validate", response_model=GraphValidateResponse)
def validate_graph(request: GraphValidateRequest, service: GraphService = Depends(get_graph_service)) -> GraphValidateResponse:
    return service.validate(request.graph)


@router.post("/compile", response_model=GraphCompileResponse)
def compile_graph(request: GraphCompileRequest, service: GraphService = Depends(get_graph_service)) -> GraphCompileResponse:
    return service.compile(request.graph, request.compile_options)


@router.post("/import/manifest", response_model=GraphManifestImportResponse)
async def import_manifest_graph(
    request: Request,
    service: ManifestImportService = Depends(get_manifest_import_service),
    settings: BackendSettings = Depends(get_settings),
    runtime=Depends(get_core_runtime),
) -> GraphManifestImportResponse:
    return service.import_manifest(
        await request.body(),
        imports_root=settings.state_dir / "manifest_imports",
        runtime=runtime,
    )
