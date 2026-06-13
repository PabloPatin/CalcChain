from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from calcchain_backend.schemas.common import ApiModel

PluginStatus = Literal["active", "disabled", "pending_restart", "error"]


class PluginCapability(ApiModel):
    namespace: str
    id: str


class PluginInfo(ApiModel):
    id: str
    version: str | None = None
    name: str | None = None
    enabled: bool = True
    loaded: bool = False
    status: PluginStatus = "active"
    restart_required: bool = False
    capabilities: list[PluginCapability] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PluginListResponse(ApiModel):
    items: list[PluginInfo]


class PluginPatchRequest(ApiModel):
    enabled: bool


class PluginRuntimeDiagnostic(ApiModel):
    plugin_id: str | None = None
    phase: str
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class PluginRuntimeStatusResponse(ApiModel):
    active: bool
    plugin_ids: list[str] = Field(default_factory=list)
    capabilities: list[PluginCapability] = Field(default_factory=list)
    diagnostics: list[PluginRuntimeDiagnostic] = Field(default_factory=list)
    error: str | None = None
