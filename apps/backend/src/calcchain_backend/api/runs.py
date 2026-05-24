from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from calcchain_backend.dependencies import get_run_service
from calcchain_backend.schemas.run import RunCreateRequest, RunCreateResponse, RunDetails, RunListResponse, RunLogsResponse
from calcchain_backend.services.run_service import RunService

router = APIRouter()


@router.post("", response_model=RunCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_run(request: RunCreateRequest, service: RunService = Depends(get_run_service)) -> RunCreateResponse:
    run = await service.create_run(request.build_config, request.run_options)
    return RunCreateResponse(run_id=run.id, status=run.status)


@router.get("", response_model=RunListResponse)
def list_runs(service: RunService = Depends(get_run_service)) -> RunListResponse:
    return RunListResponse(items=service.list_runs())


@router.get("/{run_id}", response_model=RunDetails)
def get_run(run_id: str, service: RunService = Depends(get_run_service)) -> RunDetails:
    run = service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return run


@router.post("/{run_id}/cancel", response_model=RunDetails)
async def cancel_run(run_id: str, service: RunService = Depends(get_run_service)) -> RunDetails:
    run = await service.cancel_run(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return run


@router.get("/{run_id}/events")
async def get_run_events(run_id: str, service: RunService = Depends(get_run_service)) -> StreamingResponse:
    if service.get_run(run_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return StreamingResponse(service.iter_events(run_id), media_type="text/event-stream")


@router.get("/{run_id}/logs", response_model=RunLogsResponse)
def get_run_logs(run_id: str, service: RunService = Depends(get_run_service)) -> RunLogsResponse:
    logs = service.get_logs(run_id)
    if logs is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return RunLogsResponse(items=logs)
