from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from calcchain_backend.schemas.common import ApiModel


class ArtifactSummary(ApiModel):
    id: str
    name: str
    kind: Literal["file", "directory"] = "file"
    mime_type: str = "application/octet-stream"
    size: int = 0


class ArtifactListResponse(ApiModel):
    items: list[ArtifactSummary]


class ArtifactPreview(ApiModel):
    artifact_id: str
    kind: Literal["text", "json", "unsupported"]
    content: str | dict[str, Any] | list[Any] | None = None
    message: str | None = None
