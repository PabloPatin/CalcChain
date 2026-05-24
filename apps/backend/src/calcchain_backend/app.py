from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from calcchain_backend import __version__
from calcchain_backend.api import artifacts, catalog, graphs, plugins, projects, runs, secrets, server
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
    yield


def create_app(settings: BackendSettings | None = None) -> FastAPI:
    settings = settings or create_settings(Path.cwd())

    app = FastAPI(
        title="CalcChain Backend API",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.plugin_service = PluginService(settings)
    app.state.catalog_service = CatalogService(app.state.plugin_service)
    app.state.graph_service = GraphService(app.state.catalog_service)
    app.state.project_store = ProjectStore(settings.projects_path)
    app.state.artifact_service = ArtifactService(settings.runs_dir)
    app.state.run_service = RunService(app.state.artifact_service)
    app.state.secret_service = SecretService(app.state.catalog_service)

    # For local development. Tighten this before exposing the backend outside LAN.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(server.router, prefix="/api/server", tags=["server"])
    app.include_router(catalog.router, prefix="/api/catalog", tags=["catalog"])
    app.include_router(graphs.router, prefix="/api/graphs", tags=["graphs"])
    app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
    app.include_router(runs.router, prefix="/api/runs", tags=["runs"])
    app.include_router(artifacts.router, prefix="/api/runs", tags=["artifacts"])
    app.include_router(plugins.router, prefix="/api/plugins", tags=["plugins"])
    app.include_router(secrets.router, prefix="/api/secrets", tags=["secrets"])
    return app


app = create_app()
