from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from calcchain_backend.schemas.common import ApiModel

RunStatus = Literal["queued", "running", "success", "failed", "cancelling", "cancelled"]


class RunCreateRequest(ApiModel):
    build_config: dict[str, Any]
    run_options: dict[str, Any] = Field(default_factory=dict)


class RunSummary(ApiModel):
    id: str
    name: str | None = None
    status: RunStatus
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class RunDetails(RunSummary):
    progress: dict[str, Any] = Field(default_factory=dict)
    build_config: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class RunCreateResponse(ApiModel):
    run_id: str
    status: RunStatus


class RunListResponse(ApiModel):
    items: list[RunSummary]


class LogItem(ApiModel):
    timestamp: datetime
    level: Literal["debug", "info", "warning", "error"] = "info"
    message: str


class RunLogsResponse(ApiModel):
    items: list[LogItem]


class RunEvent(ApiModel):
    id: int
    type: str
    timestamp: datetime
    data: dict[str, Any] = Field(default_factory=dict)
