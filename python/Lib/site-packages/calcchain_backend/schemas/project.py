from __future__ import annotations

from datetime import datetime

from pydantic import Field

from calcchain_backend.schemas.common import ApiModel
from calcchain_backend.schemas.graph import GraphDocument


class ProjectCreateRequest(ApiModel):
    name: str
    description: str | None = None
    graph: GraphDocument = Field(default_factory=GraphDocument)


class ProjectUpdateRequest(ApiModel):
    name: str | None = None
    description: str | None = None
    graph: GraphDocument | None = None


class Project(ApiModel):
    id: str
    name: str
    description: str | None = None
    graph: GraphDocument
    created_at: datetime
    updated_at: datetime


class ProjectListResponse(ApiModel):
    items: list[Project]
