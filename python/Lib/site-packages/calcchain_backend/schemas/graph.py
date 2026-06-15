from __future__ import annotations

from typing import Any

from pydantic import Field

from calcchain_backend.schemas.common import ApiModel, Diagnostic


class GraphPosition(ApiModel):
    x: float = 0
    y: float = 0


class GraphNode(ApiModel):
    id: str
    type: str
    title: str | None = None
    position: GraphPosition | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class GraphEdgeEndpoint(ApiModel):
    node_id: str
    port_id: str


class GraphEdge(ApiModel):
    id: str
    source: GraphEdgeEndpoint
    target: GraphEdgeEndpoint


class GraphDocument(ApiModel):
    schema_version: str = "1.0"
    name: str | None = None
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class GraphValidateRequest(ApiModel):
    graph: GraphDocument


class GraphValidateResponse(ApiModel):
    valid: bool
    errors: list[Diagnostic] = Field(default_factory=list)
    warnings: list[Diagnostic] = Field(default_factory=list)


class GraphCompileRequest(ApiModel):
    graph: GraphDocument
    compile_options: dict[str, Any] = Field(default_factory=dict)


class GraphCompileResponse(ApiModel):
    valid: bool
    build_config: dict[str, Any] | None = None
    run_config: dict[str, Any] | None = None
    publish_config: dict[str, Any] | None = None
    rules_config: dict[str, Any] | None = None
    graph_config: dict[str, Any] | None = None
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    warnings: list[Diagnostic] = Field(default_factory=list)


class GraphManifestImportEnvironment(ApiModel):
    import_id: str
    target_job_dir: str
    manifest_path: str
    written_files: list[str] = Field(default_factory=list)
    restored_files: list[str] = Field(default_factory=list)


class GraphManifestImportResponse(ApiModel):
    valid: bool
    graph: GraphDocument | None = None
    build_config: dict[str, Any] | None = None
    run_config: dict[str, Any] | None = None
    publish_config: dict[str, Any] | None = None
    rules_config: dict[str, Any] | None = None
    environment: GraphManifestImportEnvironment | None = None
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    warnings: list[Diagnostic] = Field(default_factory=list)
