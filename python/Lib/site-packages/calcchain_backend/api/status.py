from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from calcchain_backend.config import BackendConfig
from calcchain_backend.security.dependencies import get_config, require_session

router = APIRouter(prefix="/api", tags=["status"])


class HealthResponse(BaseModel):
    ok: bool
    auth_required: bool


@router.get("/health", response_model=HealthResponse)
def health(config: Annotated[BackendConfig, Depends(get_config)]) -> HealthResponse:
    return HealthResponse(ok=True, auth_required=config.auth_required)


@router.get("/session/check", dependencies=[Depends(require_session)])
def protected_check() -> dict[str, bool]:
    return {"ok": True}
