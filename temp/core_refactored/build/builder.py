from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
import hashlib
import shutil
from typing import Any

from ..common.errors import BuildExecutionError, SourceError
from ..common.status import RuntimeStatus, write_runtime_status
from ..io.source import SourceRegistry
from ..utils.json import write_json
from ..workspace import JobLayout, Snapshot, create_snapshot, file_set_from_entries, write_snapshot
from ..workspace.maps import FileSetMap
from .plan import BuildPlan, BuildPlanEntry


@dataclass(frozen=True)
class RulesArtifact:
    path: str
    sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {'path': self.path}
        if self.sha256 is not None:
            result['sha256'] = self.sha256
        return result


@dataclass(frozen=True)
class BuildResult:
    code_set: FileSetMap
    input_sets: list[FileSetMap]
    build_snapshot: Snapshot
    rules_artifact: RulesArtifact | None = None
    warnings: list[str] = field(default_factory=list)
    runtime_status: RuntimeStatus | None = None
    dry_run: bool = False
    preview: list[str] = field(default_factory=list)


class EnvironmentBuilder:
    def __init__(
        self,
        registry: SourceRegistry | None = None,
        *,
        rules_file_path: Path | None = None,
    ):
        self._registry = registry or SourceRegistry()
        self._rules_file_path = Path(rules_file_path) if rules_file_path is not None else None

    def build(self, layout: JobLayout, plan: BuildPlan, *, dry_run: bool = False) -> BuildResult:
        entries = list(plan.entries)
        code_entries = [entry for entry in entries if entry.role == 'code']
        input_entries_by_name = _entries_by_input_name(entries)
        if not code_entries:
            raise BuildExecutionError('build plan has no code entries')

        warnings = list(plan.warnings)
        preview = _preview_actions(layout, entries, plan)
        code_set = file_set_from_entries(_file_set_name(code_entries, 'code'), code_entries)
        input_sets = [
            file_set_from_entries(name, items)
            for name, items in sorted(input_entries_by_name.items())
        ]

        if dry_run:
            return BuildResult(
                code_set=code_set,
                input_sets=input_sets,
                build_snapshot=Snapshot(schema_version='1.0', created_at='', entries=[]),
                warnings=warnings,
                dry_run=True,
                preview=preview,
            )

        _reset_work_dir(layout.work_dir)
        _ensure_service_dirs(layout)
        for entry in entries:
            _copy_entry(self._registry, layout.work_dir, entry)

        rules_artifact = self._copy_rules_artifact(layout, plan, warnings)
        write_json(code_set.to_dict(), layout.build_artifacts_dir / 'code_map.json')
        write_json([item.to_dict() for item in input_sets], layout.build_artifacts_dir / 'input_maps.json')
        if rules_artifact is not None:
            write_json(rules_artifact.to_dict(), layout.build_artifacts_dir / 'rules_artifact.json')

        build_snapshot = create_snapshot(layout.work_dir)
        write_snapshot(build_snapshot, layout.snapshots_dir / 'build_snapshot.json')
        write_json(plan.lock.to_dict(), layout.build_artifacts_dir / 'build_lock.json')
        runtime_status = RuntimeStatus.built(warnings=warnings)
        write_runtime_status(layout.service_dir / 'runtime_status.json', runtime_status)

        return BuildResult(
            code_set=code_set,
            input_sets=input_sets,
            build_snapshot=build_snapshot,
            rules_artifact=rules_artifact,
            warnings=warnings,
            runtime_status=runtime_status,
            dry_run=False,
            preview=preview,
        )

    def _copy_rules_artifact(
        self,
        layout: JobLayout,
        plan: BuildPlan,
        warnings: list[str],
    ) -> RulesArtifact | None:
        if not any(entry.rules is not None for entry in plan.entries):
            return None
        if self._rules_file_path is None:
            warnings.append('rules artifact was not copied because rules_file_path was not provided')
            return None

        destination = layout.rules_dir / 'rules.json'
        destination.parent.mkdir(parents=True, exist_ok=True)
        data = self._rules_file_path.read_bytes()
        destination.write_bytes(data)
        return RulesArtifact(
            path=destination.relative_to(layout.job_dir).as_posix(),
            sha256=hashlib.sha256(data).hexdigest(),
        )


def _entries_by_input_name(entries: list[BuildPlanEntry]) -> dict[str, list[BuildPlanEntry]]:
    result: dict[str, list[BuildPlanEntry]] = {}
    for entry in entries:
        if entry.role == 'input':
            result.setdefault(entry.source_name, []).append(entry)
    return result


def _file_set_name(entries: list[BuildPlanEntry], default: str) -> str:
    for entry in entries:
        if entry.source_name:
            return entry.source_name
    return default


def _preview_actions(layout: JobLayout, entries: list[BuildPlanEntry], plan: BuildPlan) -> list[str]:
    actions = [
        f'clean work dir: {layout.work_dir}',
        f'copy files: {len(entries)}',
    ]
    if any(entry.rules is not None for entry in plan.entries):
        actions.append(f'copy rules artifact: {layout.rules_dir / "rules.json"}')
    actions.extend(
        [
            f'write build maps: {layout.build_artifacts_dir}',
            f'write snapshots: {layout.snapshots_dir}',
            f'write runtime status: {layout.service_dir / "runtime_status.json"}',
        ],
    )
    return actions


def _reset_work_dir(work_dir: Path) -> None:
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)


def _ensure_service_dirs(layout: JobLayout) -> None:
    for directory in (
        layout.service_dir,
        layout.rules_dir,
        layout.logs_dir,
        layout.frozen_inputs_dir,
        layout.snapshots_dir,
        layout.build_artifacts_dir,
        layout.publish_artifacts_dir,
        layout.reports_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)


def _copy_entry(registry: SourceRegistry, work_dir: Path, entry: BuildPlanEntry) -> None:
    destination = _safe_join(work_dir, entry.work_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = registry.read_file(entry.source, entry.source_path)
    except SourceError as err:
        raise BuildExecutionError(str(err)) from err
    destination.write_bytes(data)


def _safe_join(root: Path, relative_path: str) -> Path:
    normalized = relative_path.replace('\\', '/')
    if normalized.startswith('/') or _has_windows_drive(normalized):
        raise BuildExecutionError(f'work path must be relative: {relative_path}')
    path = PurePosixPath(normalized)
    if '..' in path.parts or path.as_posix() in {'', '.'}:
        raise BuildExecutionError(f'work path is unsafe: {relative_path}')
    root_resolved = root.resolve()
    result = root.joinpath(*path.parts)
    try:
        result.resolve(strict=False).relative_to(root_resolved)
    except ValueError as err:
        raise BuildExecutionError(f'work path escapes work dir: {relative_path}') from err
    return result


def _has_windows_drive(value: str) -> bool:
    return len(value) >= 2 and value[1] == ':' and value[0].isalpha()
