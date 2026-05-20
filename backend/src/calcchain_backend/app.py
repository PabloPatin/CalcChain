from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from calcchain_backend.api.auth import router as auth_router
from calcchain_backend.api.status import router as status_router
from calcchain_backend.config import BackendConfig
from calcchain_backend.security.pairing import PairingManager
from calcchain_backend.security.sessions import SessionManager


def create_app(config: BackendConfig | None = None) -> FastAPI:
    config = config or BackendConfig()

    app = FastAPI(title="CalcChain Backend", version="0.1.0")
    app.state.config = config
    app.state.sessions = SessionManager(ttl_seconds=config.session_ttl_seconds)
    app.state.pairing = PairingManager(
        ttl_seconds=config.pairing_ttl_seconds,
        max_attempts_per_minute=config.max_pairing_attempts_per_minute,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    app.include_router(auth_router)
    app.include_router(status_router)

    return app
