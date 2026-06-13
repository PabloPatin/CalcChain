from __future__ import annotations

import json
import mimetypes
import shutil
from pathlib import Path
from typing import Any

from calcchain_backend.schemas.artifact import ArtifactPreview, ArtifactSummary


class ArtifactService:
    def __init__(self, runs_dir: Path) -> None:
        self._runs_dir = runs_dir

    def run_dir(self, run_id: str) -> Path:
        return self._runs_dir / run_id

    def job_dir(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "job"

    def create_run_artifacts(self, run_id: str, manifest: dict[str, Any]) -> None:
        artifacts_dir = self._artifacts_dir(run_id)
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        (artifacts_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    def collect_core_artifacts(self, run_id: str, job_dir: Path, run_metadata: dict[str, Any]) -> None:
        artifacts_dir = self._artifacts_dir(run_id)
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        (artifacts_dir / "run.json").write_text(json.dumps(run_metadata, ensure_ascii=False, indent=2), encoding="utf-8")

        for source, artifact_name in _core_artifact_candidates(job_dir):
            if source.is_file():
                shutil.copy2(source, artifacts_dir / artifact_name)

    def list_artifacts(self, run_id: str) -> list[ArtifactSummary]:
        artifacts_dir = self._artifacts_dir(run_id)
        if not artifacts_dir.is_dir():
            return []
        items: list[ArtifactSummary] = []
        for path in sorted(artifacts_dir.iterdir()):
            if path.is_file():
                mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                items.append(ArtifactSummary(id=path.name, name=path.name, mime_type=mime_type, size=path.stat().st_size))
        return items

    def artifact_path(self, run_id: str, artifact_id: str) -> Path | None:
        safe_name = Path(artifact_id).name
        path = self._artifacts_dir(run_id) / safe_name
        if not path.is_file():
            return None
        return path

    def preview_artifact(self, run_id: str, artifact_id: str) -> ArtifactPreview | None:
        path = self.artifact_path(run_id, artifact_id)
        if path is None:
            return None
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if path.stat().st_size > 512_000:
            return ArtifactPreview(artifact_id=artifact_id, kind="unsupported", message="Artifact is too large for preview")
        if mime_type == "application/json" or path.suffix.lower() == ".json":
            try:
                return ArtifactPreview(artifact_id=artifact_id, kind="json", content=json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                return ArtifactPreview(artifact_id=artifact_id, kind="unsupported", message="JSON preview failed")
        if mime_type.startswith("text/") or path.suffix.lower() in {".log", ".txt", ".csv", ".toml", ".yaml", ".yml"}:
            return ArtifactPreview(artifact_id=artifact_id, kind="text", content=path.read_text(encoding="utf-8", errors="replace"))
        return ArtifactPreview(artifact_id=artifact_id, kind="unsupported", message=f"Preview is not supported for {mime_type}")

    def _artifacts_dir(self, run_id: str) -> Path:
        return self._runs_dir / run_id / "artifacts"


def _core_artifact_candidates(job_dir: Path) -> list[tuple[Path, str]]:
    service_dir = job_dir / ".calcchain"
    logs_dir = service_dir / "logs"
    return [
        (job_dir / "build.toml", "build.toml"),
        (job_dir / "build.lock.toml", "build.lock.toml"),
        (job_dir / "run.toml", "run.toml"),
        (job_dir / "publish.toml", "publish.toml"),
        (job_dir / "publish.lock.toml", "publish.lock.toml"),
        (job_dir / "rules.json", "rules.json"),
        (job_dir / "graph.json", "graph.json"),
        (service_dir / "manifest.json", "manifest.json"),
        (service_dir / "runtime_status.json", "runtime_status.json"),
        (logs_dir / "stdout.txt", "stdout.txt"),
        (logs_dir / "stderr.txt", "stderr.txt"),
        (logs_dir / "stdin.txt", "stdin.txt"),
    ]
