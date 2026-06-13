from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from calcchain_backend.schemas.common import ApiModel


PortDirection = Literal["input", "output"]


class PortDescriptor(ApiModel):
    id: str
    title: str
    direction: PortDirection
    kind: str
    required: bool = False
    max_connections: int | None = None


class BlockDescriptor(ApiModel):
    type: str
    title: str
    category: str
    description: str | None = None
    ports: list[PortDescriptor] = Field(default_factory=list)
    config_schema: dict[str, Any] = Field(default_factory=dict)
    plugin_id: str | None = None


class ConnectionRule(ApiModel):
    id: str
    from_kind: str
    to_kind: str
    description: str | None = None


class CatalogResponse(ApiModel):
    catalog_version: str
    port_kinds: list[str]
    blocks: list[BlockDescriptor]
    connection_rules: list[ConnectionRule]
    plugins: list[str] = Field(default_factory=list)
