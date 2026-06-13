from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse

from calcchain_backend.dependencies import get_artifact_service, get_run_service
from calcchain_backend.schemas.artifact import ArtifactListResponse, ArtifactPreview
from calcchain_backend.services.artifact_service import ArtifactService
from calcchain_backend.services.run_service import RunService

router = APIRouter()


def _ensure_run_exists(run_id: str, run_service: RunService) -> None:
    if run_service.get_run(run_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")


@router.get("/{run_id}/artifacts", response_model=ArtifactListResponse)
def list_run_artifacts(
    run_id: str,
    run_service: RunService = Depends(get_run_service),
    artifact_service: ArtifactService = Depends(get_artifact_service),
) -> ArtifactListResponse:
    _ensure_run_exists(run_id, run_service)
    return ArtifactListResponse(items=artifact_service.list_artifacts(run_id))


@router.get("/{run_id}/artifacts/{artifact_id}")
def download_run_artifact(
    run_id: str,
    artifact_id: str,
    run_service: RunService = Depends(get_run_service),
    artifact_service: ArtifactService = Depends(get_artifact_service),
) -> FileResponse:
    _ensure_run_exists(run_id, run_service)
    path = artifact_service.artifact_path(run_id, artifact_id)
    if path is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found")
    return FileResponse(path, filename=path.name)


@router.get("/{run_id}/artifacts/{artifact_id}/preview", response_model=ArtifactPreview)
def preview_run_artifact(
    run_id: str,
    artifact_id: str,
    run_service: RunService = Depends(get_run_service),
    artifact_service: ArtifactService = Depends(get_artifact_service),
) -> ArtifactPreview:
    _ensure_run_exists(run_id, run_service)
    preview = artifact_service.preview_artifact(run_id, artifact_id)
    if preview is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found")
    return preview
