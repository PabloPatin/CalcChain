from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Diagnostic(ApiModel):
    code: str
    message: str
    severity: Literal["error", "warning", "info"] = "error"
    node_id: str | None = None
    port_id: str | None = None
    edge_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(ApiModel):
    detail: str
    code: str = "error"
