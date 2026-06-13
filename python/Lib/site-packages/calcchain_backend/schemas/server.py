from __future__ import annotations

from calcchain_backend.schemas.common import ApiModel


class ServerInfo(ApiModel):
    app: str
    version: str
    api_version: str
    mode: str
    auth_required: bool = False


class HealthResponse(ApiModel):
    status: str = "ok"
