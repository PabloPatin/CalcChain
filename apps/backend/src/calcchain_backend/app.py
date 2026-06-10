from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from calcchain_backend import __version__
from calcchain_backend.api import artifacts, auth, catalog, graphs, plugins, projects, runs, secrets, server
from calcchain_backend.config import BackendConfig
from calcchain_backend.control import ControlServer
from calcchain_backend.security.dependencies import require_session
from calcchain_backend.security.pairing import PairingManager
from calcchain_backend.security.sessions import SessionManager
from calcchain_backend.services.artifact_service import ArtifactService
from calcchain_backend.services.catalog_service import CatalogService
from calcchain_backend.services.graph_service import GraphService
from calcchain_backend.services.plugin_service import PluginService
from calcchain_backend.services.project_store import ProjectStore
from calcchain_backend.services.run_service import RunService
from calcchain_backend.services.secret_service import SecretService
from calcchain_backend.settings import BackendSettings, create_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: BackendSettings = app.state.settings
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    settings.runs_dir.mkdir(parents=True, exist_ok=True)
    control_server = getattr(app.state, "control_server", None)
    if control_server is not None:
        control_server.start()
    try:
        yield
    finally:
        if control_server is not None:
            control_server.close()


def create_app(settings: BackendSettings | None = None) -> FastAPI:
    settings = settings or create_settings(Path.cwd())

    app = FastAPI(
        title="CalcChain Backend API",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.config = _backend_config(settings)
    app.state.sessions = SessionManager(settings.session_ttl_seconds)
    app.state.pairing = PairingManager(
        ttl_seconds=settings.pairing_ttl_seconds,
        max_attempts_per_minute=settings.max_pairing_attempts_per_minute,
    )
    app.state.control_server = ControlServer(app.state.pairing) if settings.auth_required else None
    app.state.plugin_service = PluginService(settings)
    app.state.catalog_service = CatalogService(app.state.plugin_service)
    app.state.graph_service = GraphService(app.state.catalog_service)
    app.state.project_store = ProjectStore(settings.projects_path)
    app.state.artifact_service = ArtifactService(settings.runs_dir)
    app.state.secret_service = SecretService(app.state.catalog_service)
    app.state.run_service = RunService(app.state.artifact_service, app.state.secret_service, app.state.plugin_service)

    # For local development. Tighten this before exposing the backend outside LAN.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    protected = [Depends(require_session)] if settings.auth_required else []
    app.include_router(server.router, prefix="/api/server", tags=["server"])
    app.include_router(auth.router, tags=["auth"])
    app.include_router(catalog.router, prefix="/api/catalog", tags=["catalog"], dependencies=protected)
    app.include_router(graphs.router, prefix="/api/graphs", tags=["graphs"], dependencies=protected)
    app.include_router(projects.router, prefix="/api/projects", tags=["projects"], dependencies=protected)
    app.include_router(runs.router, prefix="/api/runs", tags=["runs"], dependencies=protected)
    app.include_router(artifacts.router, prefix="/api/runs", tags=["artifacts"], dependencies=protected)
    app.include_router(plugins.router, prefix="/api/plugins", tags=["plugins"], dependencies=protected)
    app.include_router(secrets.router, prefix="/api/secrets", tags=["secrets"], dependencies=protected)
    _mount_frontend(app, settings.frontend_static_dir)
    return app


def create_app_from_env() -> FastAPI:
    """Uvicorn reload factory.

    Reload mode requires an import string, so CLI arguments are passed to the
    reloaded worker through narrowly scoped environment variables.
    """
    project_root = os.environ.get("CALCCHAIN_BACKEND_PROJECT_ROOT")
    app_root = os.environ.get("CALCCHAIN_BACKEND_APP_ROOT")
    state_dir = os.environ.get("CALCCHAIN_BACKEND_STATE_DIR")
    projects_dir = os.environ.get("CALCCHAIN_BACKEND_PROJECTS_DIR")
    plugin_root = os.environ.get("CALCCHAIN_BACKEND_PLUGIN_ROOT")
    static_dir = os.environ.get("CALCCHAIN_BACKEND_STATIC_DIR")
    mode = os.environ.get("CALCCHAIN_BACKEND_MODE") or "local"
    host = os.environ.get("CALCCHAIN_BACKEND_HOST") or "127.0.0.1"
    raw_port = os.environ.get("CALCCHAIN_BACKEND_PORT")
    try:
        port = int(raw_port) if raw_port else 8765
    except ValueError:
        port = 8765
    return create_app(
        create_settings(
            project_root,
            app_root=app_root,
            state_dir=state_dir,
            user_projects_dir=projects_dir,
            plugin_root=plugin_root,
            static_dir=static_dir,
            mode=mode,
            host=host,
            port=port,
        )
    )


def _backend_config(settings: BackendSettings) -> BackendConfig:
    return BackendConfig(
        host=settings.host,
        port=settings.port,
        lan=settings.mode == "lan",
        auth_required=settings.auth_required,
        pairing_ttl_seconds=settings.pairing_ttl_seconds,
        session_ttl_seconds=settings.session_ttl_seconds,
        max_pairing_attempts_per_minute=settings.max_pairing_attempts_per_minute,
    )


def _mount_frontend(app: FastAPI, static_dir: Path | None) -> None:
    if static_dir is None:
        return

    static_root = static_dir.resolve()
    index_path = static_root / "index.html"
    if not index_path.is_file():
        return

    @app.get("/", include_in_schema=False)
    def serve_frontend_root() -> FileResponse:
        return FileResponse(index_path)

    @app.get("/{frontend_path:path}", include_in_schema=False)
    def serve_frontend_path(frontend_path: str) -> FileResponse:
        if frontend_path == "api" or frontend_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")

        response_path = _frontend_response_path(static_root, frontend_path)
        if response_path is None:
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(response_path)


def _frontend_response_path(static_root: Path, frontend_path: str) -> Path | None:
    index_path = static_root / "index.html"
    candidate = (static_root / frontend_path).resolve()

    if _is_relative_to(candidate, static_root) and candidate.is_file():
        return candidate

    if index_path.is_file():
        return index_path
    return None


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


app = create_app()
