from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from fastapi import Request

from calcchain_backend.services.artifact_service import ArtifactService
from calcchain_backend.services.catalog_service import CatalogService
from calcchain_backend.services.graph_service import GraphService
from calcchain_backend.services.plugin_service import PluginService
from calcchain_backend.services.project_store import ProjectStore
from calcchain_backend.services.run_service import RunService
from calcchain_backend.services.secret_service import SecretService
from calcchain_backend.settings import BackendSettings, create_settings


@lru_cache(maxsize=1)
def get_default_settings() -> BackendSettings:
    return create_settings(Path.cwd())


def get_settings(request: Request) -> BackendSettings:
    return request.app.state.settings


def get_plugin_service(request: Request) -> PluginService:
    return request.app.state.plugin_service


def get_catalog_service(request: Request) -> CatalogService:
    return request.app.state.catalog_service


def get_graph_service(request: Request) -> GraphService:
    return request.app.state.graph_service


def get_project_store(request: Request) -> ProjectStore:
    return request.app.state.project_store


def get_run_service(request: Request) -> RunService:
    return request.app.state.run_service


def get_artifact_service(request: Request) -> ArtifactService:
    return request.app.state.artifact_service


def get_secret_service(request: Request) -> SecretService:
    return request.app.state.secret_service
