from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

from calcchain_backend.schemas.common import now_utc
from calcchain_backend.schemas.project import Project, ProjectCreateRequest, ProjectUpdateRequest


class ProjectStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def list_projects(self) -> list[Project]:
        return sorted(self._read_all().values(), key=lambda project: project.updated_at, reverse=True)

    def create_project(self, request: ProjectCreateRequest) -> Project:
        now = now_utc()
        project = Project(
            id=f"project_{uuid.uuid4().hex[:16]}",
            name=request.name,
            description=request.description,
            graph=request.graph,
            created_at=now,
            updated_at=now,
        )
        projects = self._read_all()
        projects[project.id] = project
        self._write_all(projects)
        return project

    def get_project(self, project_id: str) -> Project | None:
        return self._read_all().get(project_id)

    def update_project(self, project_id: str, request: ProjectUpdateRequest) -> Project | None:
        projects = self._read_all()
        current = projects.get(project_id)
        if current is None:
            return None
        updated = current.model_copy(
            update={
                "name": request.name if request.name is not None else current.name,
                "description": request.description if request.description is not None else current.description,
                "graph": request.graph if request.graph is not None else current.graph,
                "updated_at": now_utc(),
            },
        )
        projects[project_id] = updated
        self._write_all(projects)
        return updated

    def delete_project(self, project_id: str) -> bool:
        projects = self._read_all()
        if project_id not in projects:
            return False
        del projects[project_id]
        self._write_all(projects)
        return True

    def _read_all(self) -> dict[str, Project]:
        if not self._path.is_file():
            return {}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        items = raw.get("items", []) if isinstance(raw, dict) else []
        projects: dict[str, Project] = {}
        for item in items:
            try:
                project = Project.model_validate(item)
            except Exception:
                continue
            projects[project.id] = project
        return projects

    def _write_all(self, projects: dict[str, Project]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"items": [project.model_dump(mode="json") for project in projects.values()]}
        self._path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
