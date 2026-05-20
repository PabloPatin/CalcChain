from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from calcchain_backend.config import BackendConfig
from calcchain_backend.security.dependencies import (
    bearer_scheme,
    extract_bearer_token,
    get_config,
    get_sessions,
)
from calcchain_backend.security.sessions import SessionManager

router = APIRouter(prefix="/api/auth", tags=["auth"])


class AuthStateResponse(BaseModel):
    auth_required: bool
    authenticated: bool


class PairingRequest(BaseModel):
    code: str = Field(min_length=8, max_length=8, pattern=r"^\d{8}$")


class PairingResponse(BaseModel):
    token: str
    token_type: str = "bearer"
    expires_in_seconds: int


def client_id_from_request(request: Request) -> str:
    if request.client is None:
        return "unknown"
    return request.client.host


@router.get("/state", response_model=AuthStateResponse)
def auth_state(
    config: Annotated[BackendConfig, Depends(get_config)],
    sessions: Annotated[SessionManager, Depends(get_sessions)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> AuthStateResponse:
    if not config.auth_required:
        return AuthStateResponse(auth_required=False, authenticated=True)

    token = extract_bearer_token(credentials)
    return AuthStateResponse(
        auth_required=True,
        authenticated=sessions.is_valid(token),
    )


@router.post("/pair", response_model=PairingResponse)
def pair_browser(
    payload: PairingRequest,
    request: Request,
    config: Annotated[BackendConfig, Depends(get_config)],
    sessions: Annotated[SessionManager, Depends(get_sessions)],
) -> PairingResponse:
    if not config.auth_required:
        token, _session = sessions.create()
        return PairingResponse(token=token, expires_in_seconds=config.session_ttl_seconds)

    pairing = request.app.state.pairing
    ok = pairing.verify_once(payload.code, client_id=client_id_from_request(request))
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid, expired, or rate-limited pairing code",
        )

    token, _session = sessions.create()
    return PairingResponse(token=token, expires_in_seconds=config.session_ttl_seconds)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    sessions: Annotated[SessionManager, Depends(get_sessions)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> None:
    sessions.revoke(extract_bearer_token(credentials))
