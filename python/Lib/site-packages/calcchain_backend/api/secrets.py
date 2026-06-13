from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from calcchain_backend.dependencies import get_secret_service, get_session_key
from calcchain_backend.schemas.secrets import (
    ClearSessionSecretsResponse,
    DeleteSessionSecretResponse,
    SecretRequirementsRequest,
    SecretRequirementsResponse,
    SessionSecretListResponse,
    StoreSessionSecretRequest,
    StoreSessionSecretResponse,
)
from calcchain_backend.services.secret_service import SecretService

router = APIRouter()


@router.post("/requirements", response_model=SecretRequirementsResponse)
def get_secret_requirements(
    payload: SecretRequirementsRequest,
    session_key: str = Depends(get_session_key),
    secret_service: SecretService = Depends(get_secret_service),
) -> SecretRequirementsResponse:
    if payload.graph is not None:
        return secret_service.get_requirements_for_graph(session_key, payload.graph)
    if payload.build_config is not None:
        return secret_service.get_requirements_for_build_config(session_key, payload.build_config)
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Either graph or build_config must be provided")


@router.get("/session", response_model=SessionSecretListResponse)
def list_session_secrets(
    session_key: str = Depends(get_session_key),
    secret_service: SecretService = Depends(get_secret_service),
) -> SessionSecretListResponse:
    return secret_service.list_session_secrets(session_key)


@router.post("/session", response_model=StoreSessionSecretResponse)
def store_session_secret(
    payload: StoreSessionSecretRequest,
    session_key: str = Depends(get_session_key),
    secret_service: SecretService = Depends(get_secret_service),
) -> StoreSessionSecretResponse:
    values = {name: value.get_secret_value() for name, value in payload.values.items()}
    return secret_service.put_session_secret(
        session_key=session_key,
        secret_ref=payload.secret_ref,
        kind=payload.kind,
        values=values,
        ttl_seconds=payload.ttl_seconds,
    )


@router.delete("/session/{secret_ref:path}", response_model=DeleteSessionSecretResponse)
def delete_session_secret(
    secret_ref: str,
    session_key: str = Depends(get_session_key),
    secret_service: SecretService = Depends(get_secret_service),
) -> DeleteSessionSecretResponse:
    return secret_service.delete_session_secret(session_key, secret_ref)


@router.post("/session/clear", response_model=ClearSessionSecretsResponse)
def clear_session_secrets(
    session_key: str = Depends(get_session_key),
    secret_service: SecretService = Depends(get_secret_service),
) -> ClearSessionSecretsResponse:
    return secret_service.clear_session_secrets(session_key)
