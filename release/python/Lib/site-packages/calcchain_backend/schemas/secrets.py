from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, SecretStr, model_validator

from calcchain_backend.schemas.common import ApiModel
from calcchain_backend.schemas.graph import GraphDocument


SecretScope = Literal["session"]
SecretRequirementStatus = Literal["missing", "partial", "satisfied"]


class SecretFieldRequirement(ApiModel):
    name: str
    title: str | None = None
    description: str | None = None
    secret: bool = True
    required: bool = True
    config_path: str | None = None


class SecretUsage(ApiModel):
    node_id: str
    node_title: str | None = None
    node_type: str | None = None
    port_id: str | None = None


class SecretRequirement(ApiModel):
    secret_ref: str
    kind: str
    title: str
    description: str | None = None
    fields: list[SecretFieldRequirement]
    used_by: list[SecretUsage] = Field(default_factory=list)
    status: SecretRequirementStatus = "missing"


class SecretRequirementsRequest(ApiModel):
    graph: GraphDocument | None = None
    build_config: dict[str, Any] | None = None

    @model_validator(mode="after")
    def require_graph_or_build_config(self) -> "SecretRequirementsRequest":
        if self.graph is None and self.build_config is None:
            raise ValueError("Either graph or build_config must be provided")
        return self


class SecretRequirementsResponse(ApiModel):
    requirements: list[SecretRequirement] = Field(default_factory=list)


class StoreSessionSecretRequest(ApiModel):
    secret_ref: str
    kind: str
    scope: SecretScope = "session"
    ttl_seconds: int | None = Field(default=4 * 60 * 60, ge=60, le=24 * 60 * 60)
    values: dict[str, SecretStr]

    @model_validator(mode="after")
    def require_values(self) -> "StoreSessionSecretRequest":
        if not self.values:
            raise ValueError("At least one secret value must be provided")
        return self


class SecretFieldStatus(ApiModel):
    name: str
    secret: bool
    has_value: bool


class SessionSecretStatus(ApiModel):
    secret_ref: str
    kind: str
    scope: SecretScope = "session"
    fields: list[SecretFieldStatus] = Field(default_factory=list)
    created_at: datetime
    expires_at: datetime | None = None


class SessionSecretListResponse(ApiModel):
    items: list[SessionSecretStatus] = Field(default_factory=list)


class StoreSessionSecretResponse(ApiModel):
    secret_ref: str
    status: Literal["stored"] = "stored"
    item: SessionSecretStatus


class DeleteSessionSecretResponse(ApiModel):
    secret_ref: str
    status: Literal["deleted", "not_found"]


class ClearSessionSecretsResponse(ApiModel):
    status: Literal["cleared"] = "cleared"
    deleted_count: int
