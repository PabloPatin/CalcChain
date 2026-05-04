from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path, PurePosixPath
import shutil
from typing import Any

from calcchain_core.build_plan import BuildPlan, BuildPlanEntry
from calcchain_core.errors import BuildExecutionError, SourceError
from calcchain_core.layout import JobLayout
from calcchain_core.maps import FileSetMap, create_file_set_map
from calcchain_core.models import SourceRef, SourceType
from calcchain_core.snapshot import Snapshot, create_snapshot
from calcchain_core.sources import SourceRegistry, sanitize_source_error_message
from calcchain_core.status import RuntimeStatus, write_runtime_status


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
    pre_run_snapshot: Snapshot | None = None
    runtime_status: RuntimeStatus | None = None
    dry_run: bool = False
    preview: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PreRunCheckResult:
    pre_run_snapshot: Snapshot
    runtime_status: RuntimeStatus
    blockers: list[str] = field(default_factory=list)
    frozen_inputs: Any | None = None
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

        preview = _preview_actions(layout, entries, plan)
        warnings = list(plan.warnings)
        code_set = create_file_set_map(code_entries)
        input_sets = [create_file_set_map(items) for _, items in sorted(input_entries_by_name.items())]

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
        _write_json(layout.build_artifacts_dir / 'code_map.json', code_set.to_dict())
        _write_json(layout.build_artifacts_dir / 'input_maps.json', [item.to_dict() for item in input_sets])
        if rules_artifact is not None:
            _write_json(layout.build_artifacts_dir / 'rules_artifact.json', rules_artifact.to_dict())

        build_snapshot = create_snapshot(layout.work_dir)
        _write_json(layout.snapshots_dir / 'build_snapshot.json', build_snapshot.to_dict())
        _write_json(layout.build_artifacts_dir / 'build_lock.json', plan.lock.to_dict())
        runtime_status = RuntimeStatus.built(warnings=warnings)
        write_runtime_status(layout.service_dir / 'runtime_status.json', runtime_status)

        return BuildResult(
            code_set=code_set,
            input_sets=input_sets,
            build_snapshot=build_snapshot,
            rules_artifact=rules_artifact,
            warnings=warnings,
            pre_run_snapshot=None,
            runtime_status=runtime_status,
            dry_run=False,
            preview=preview,
        )

    def check_pre_run(
        self,
        layout: JobLayout,
        build_result: BuildResult,
        plan: BuildPlan,
        *,
        dry_run: bool = False,
    ) -> PreRunCheckResult:
        pre_run_snapshot = create_snapshot(layout.work_dir)
        blockers = _pre_run_blockers(layout, build_result, plan, pre_run_snapshot)
        preview = _pre_run_preview_actions(layout, blockers)
        runtime_status = RuntimeStatus.built(warnings=build_result.warnings, blockers=blockers)
        if dry_run:
            return PreRunCheckResult(
                pre_run_snapshot=pre_run_snapshot,
                runtime_status=runtime_status,
                blockers=blockers,
                dry_run=True,
                preview=preview,
            )

        from calcchain_core.frozen_inputs import freeze_effective_inputs

        _write_json(layout.snapshots_dir / 'pre_run_snapshot.json', pre_run_snapshot.to_dict())
        frozen_inputs = freeze_effective_inputs(layout, build_result, pre_run_snapshot)
        write_runtime_status(layout.service_dir / 'runtime_status.json', runtime_status)
        return PreRunCheckResult(
            pre_run_snapshot=pre_run_snapshot,
            runtime_status=runtime_status,
            blockers=blockers,
            frozen_inputs=frozen_inputs,
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
        destination = layout.rules_dir / 'rules.json'
        source = plan.lock.rules.source if plan.lock.rules is not None else None
        source_bytes = self._read_rules_bytes(source)
        if source_bytes is None:
            warnings.append('rules.json local artifact was not copied because rules source bytes were unavailable')
            return None
        destination.write_bytes(source_bytes)
        sha256 = _sha256_bytes(source_bytes)
        return RulesArtifact(path=destination.relative_to(layout.job_dir).as_posix(), sha256=sha256)

    def _read_rules_bytes(self, source: SourceRef | None) -> bytes | None:
        if self._rules_file_path is not None:
            return self._rules_file_path.read_bytes()
        if source is None:
            return None
        if source.type is SourceType.LOCAL and Path(source.path).is_file():
            return Path(source.path).read_bytes()
        try:
            return self._registry.read_file(source, Path(source.path).name)
        except (OSError, SourceError):
            return None


def _entries_by_input_name(entries: list[BuildPlanEntry]) -> dict[str, list[BuildPlanEntry]]:
    result: dict[str, list[BuildPlanEntry]] = {}
    for entry in entries:
        if entry.role == 'input':
            result.setdefault(entry.source_name, []).append(entry)
    return result


def _preview_actions(layout: JobLayout, entries: list[BuildPlanEntry], plan: BuildPlan) -> list[str]:
    actions = [f'clean work dir: {layout.work_dir}', f'copy files: {len(entries)}']
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


def _pre_run_preview_actions(layout: JobLayout, blockers: list[str]) -> list[str]:
    actions = [
        f'create pre-run snapshot: {layout.snapshots_dir / "pre_run_snapshot.json"}',
        f'check code changes: {layout.work_dir}',
        f'check rules artifact: {layout.rules_dir / "rules.json"}',
        f'check build lock artifact: {layout.build_artifacts_dir / "build_lock.json"}',
        f'write runtime status: {layout.service_dir / "runtime_status.json"}',
        f'freeze effective inputs: {layout.frozen_inputs_dir}',
    ]
    if blockers:
        actions.append(f'record blockers: {len(blockers)}')
    return actions


def _pre_run_blockers(
    layout: JobLayout,
    build_result: BuildResult,
    plan: BuildPlan,
    pre_run_snapshot: Snapshot,
) -> list[str]:
    blockers: list[str] = []
    build_entries = {entry.path: entry for entry in build_result.build_snapshot.entries}
    pre_run_entries = {entry.path: entry for entry in pre_run_snapshot.entries}
    for work_path in _code_paths(build_result):
        before = build_entries.get(work_path)
        after = pre_run_entries.get(work_path)
        if before is None:
            blockers.append(f'code file was not present in build snapshot: {work_path}')
        elif after is None:
            blockers.append(f'code file changed before run: {work_path} was deleted')
        elif before.sha256 != after.sha256 or before.size != after.size:
            blockers.append(f'code file changed before run: {work_path}')

    rules_artifact = build_result.rules_artifact
    if rules_artifact is not None:
        rules_path = layout.job_dir / rules_artifact.path
        if not rules_path.is_file():
            blockers.append(f'rules artifact changed before run: {rules_artifact.path} was deleted')
        else:
            actual_sha256 = _sha256_file(rules_path)
            expected_sha256 = rules_artifact.sha256
            if expected_sha256 is None:
                expected_sha256 = actual_sha256
            if actual_sha256 != expected_sha256:
                blockers.append(f'rules artifact changed before run: {rules_artifact.path}')

    lock_path = layout.build_artifacts_dir / 'build_lock.json'
    expected_lock = _stable_json_sha256(plan.lock.to_dict())
    if not lock_path.is_file():
        blockers.append('build lock artifact changed before run: .calcchain/build/build_lock.json was deleted')
    else:
        try:
            lock_changed = _json_file_stable_sha256(lock_path) != expected_lock
        except ValueError:
            lock_changed = True
        if lock_changed:
            blockers.append('build lock artifact changed before run: .calcchain/build/build_lock.json')
    return blockers


def _code_paths(build_result: BuildResult) -> list[str]:
    return sorted(entry.work_path for entry in build_result.code_set.map if entry.work_path is not None)


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
        layout.publication_artifacts_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)


def _copy_entry(registry: SourceRegistry, work_dir: Path, entry: BuildPlanEntry) -> None:
    destination = _safe_join(work_dir, entry.work_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = registry.read_file(entry.source, entry.source_path)
    except SourceError as err:
        raise BuildExecutionError(sanitize_source_error_message(str(err), entry.source)) from err
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


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + '\n',
        encoding='utf-8',
    )


def _stable_json_sha256(data: Any) -> str:
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return _sha256_bytes(payload.encode('utf-8'))


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _json_file_stable_sha256(path: Path) -> str:
    return _stable_json_sha256(json.loads(path.read_text(encoding='utf-8')))


def _sha256_bytes(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()
