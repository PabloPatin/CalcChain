from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from calcchain_backend.dependencies import get_graph_service, get_project_store
from calcchain_backend.schemas.project import Project, ProjectCreateRequest, ProjectListResponse, ProjectUpdateRequest
from calcchain_backend.services.graph_service import GraphService
from calcchain_backend.services.project_store import ProjectStore

router = APIRouter()


@router.get("", response_model=ProjectListResponse)
def list_projects(store: ProjectStore = Depends(get_project_store)) -> ProjectListResponse:
    return ProjectListResponse(items=store.list_projects())


@router.post("", response_model=Project, status_code=status.HTTP_201_CREATED)
def create_project(
    request: ProjectCreateRequest,
    store: ProjectStore = Depends(get_project_store),
    graph_service: GraphService = Depends(get_graph_service),
) -> Project:
    return store.create_project(
        request.model_copy(update={"graph": graph_service.sanitize_graph(request.graph)}),
    )


@router.get("/{project_id}", response_model=Project)
def get_project(project_id: str, store: ProjectStore = Depends(get_project_store)) -> Project:
    project = store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


@router.put("/{project_id}", response_model=Project)
def update_project(
    project_id: str,
    request: ProjectUpdateRequest,
    store: ProjectStore = Depends(get_project_store),
    graph_service: GraphService = Depends(get_graph_service),
) -> Project:
    sanitized = request
    if request.graph is not None:
        sanitized = request.model_copy(update={"graph": graph_service.sanitize_graph(request.graph)})
    project = store.update_project(project_id, sanitized)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: str, store: ProjectStore = Depends(get_project_store)) -> None:
    deleted = store.delete_project(project_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
