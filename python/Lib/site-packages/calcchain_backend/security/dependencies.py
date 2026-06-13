from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from calcchain_backend.config import BackendConfig
from calcchain_backend.security.sessions import SessionManager

bearer_scheme = HTTPBearer(auto_error=False)


def get_config(request: Request) -> BackendConfig:
    return request.app.state.config


def get_sessions(request: Request) -> SessionManager:
    return request.app.state.sessions


def extract_bearer_token(credentials: HTTPAuthorizationCredentials | None) -> str | None:
    if credentials is None:
        return None
    if credentials.scheme.lower() != "bearer":
        return None
    return credentials.credentials


def require_session(
    config: Annotated[BackendConfig, Depends(get_config)],
    sessions: Annotated[SessionManager, Depends(get_sessions)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> None:
    if not config.auth_required:
        return

    token = extract_bearer_token(credentials)
    if not sessions.is_valid(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid session token required",
        )
