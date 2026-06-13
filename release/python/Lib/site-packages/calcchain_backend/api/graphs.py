from __future__ import annotations

from fastapi import APIRouter, Depends

from calcchain_backend.dependencies import get_graph_service
from calcchain_backend.schemas.graph import GraphCompileRequest, GraphCompileResponse, GraphValidateRequest, GraphValidateResponse
from calcchain_backend.services.graph_service import GraphService

router = APIRouter()


@router.post("/validate", response_model=GraphValidateResponse)
def validate_graph(request: GraphValidateRequest, service: GraphService = Depends(get_graph_service)) -> GraphValidateResponse:
    return service.validate(request.graph)


@router.post("/compile", response_model=GraphCompileResponse)
def compile_graph(request: GraphCompileRequest, service: GraphService = Depends(get_graph_service)) -> GraphCompileResponse:
    return service.compile(request.graph, request.compile_options)
