from dataclasses import dataclass, field

from ..build.builder import BuildResult, RulesArtifact
from ..common.hash import sha256_dict
from ..common.status import RuntimeStatus, write_runtime_status
from ..io.source import SourceRegistry
from ..utils.json import read_json
from ..workspace.layout import JobLayout
from ..workspace.maps import FileSetMap
from ..workspace.snapshot import Snapshot, create_snapshot, write_snapshot
from .frozen_inputs import freeze_effective_inputs


@dataclass(frozen=True)
class PreRunPreparationResult:
    pre_run_snapshot: Snapshot
    runtime_status: RuntimeStatus
    blockers: list[str] = field(default_factory=list)
    frozen_inputs: FileSetMap | None = None
    dry_run: bool = False
    preview: list[str] = field(default_factory=list)


class PreRunPreparer:
    def __init__(self, registry: SourceRegistry | None = None):
        self._registry = registry or SourceRegistry()

    def prepare(
        self,
        layout: JobLayout,
        build_result: BuildResult,
        *,
        dry_run: bool = False,
    ) -> PreRunPreparationResult:
        pre_run_snapshot = create_snapshot(layout.work_dir)
        blockers = _pre_run_blockers(layout, build_result, pre_run_snapshot)
        preview = _pre_run_preview_actions(layout, blockers)
        runtime_status = RuntimeStatus.built(warnings=build_result.warnings, blockers=blockers)
        if dry_run:
            return PreRunPreparationResult(
                pre_run_snapshot=pre_run_snapshot,
                runtime_status=runtime_status,
                blockers=blockers,
                dry_run=True,
                preview=preview,
            )

        write_snapshot(pre_run_snapshot, layout.snapshots_dir / 'pre_run_snapshot.json')
        frozen_inputs = freeze_effective_inputs(layout, build_result, pre_run_snapshot, registry=self._registry)
        write_runtime_status(layout.service_dir / 'runtime_status.json', runtime_status)
        return PreRunPreparationResult(
            pre_run_snapshot=pre_run_snapshot,
            runtime_status=runtime_status,
            blockers=blockers,
            frozen_inputs=frozen_inputs,
            dry_run=False,
            preview=preview,
        )


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

    _append_rules_blockers(layout, build_result.rules_artifact, blockers)
    _append_build_lock_blockers(layout, build_result, blockers)
    return blockers


def _append_rules_blockers(
    layout: JobLayout,
    rules_artifact: RulesArtifact | None,
    blockers: list[str],
) -> None:
    if rules_artifact is None:
        return
    rules_path = layout.job_dir / rules_artifact.path
    if not rules_path.is_file():
        blockers.append(f'rules artifact changed before run: {rules_artifact.path} was deleted')
        return

    actual_sha256 = _sha256_bytes(rules_path.read_bytes())
    expected_sha256 = rules_artifact.sha256 or actual_sha256
    if actual_sha256 != expected_sha256:
        blockers.append(f'rules artifact changed before run: {rules_artifact.path}')


def _append_build_lock_blockers(
    layout: JobLayout,
    build_result: BuildResult,
    blockers: list[str],
) -> None:
    if build_result.build_lock_sha256 is None:
        blockers.append('build lock expected hash is missing before run')
        return

    lock_path = layout.build_artifacts_dir / 'build_lock.json'
    if not lock_path.is_file():
        blockers.append('build lock artifact changed before run: .calcchain/build/build_lock.json was deleted')
        return

    try:
        actual = sha256_dict(read_json(lock_path))
    except (OSError, ValueError):
        blockers.append('build lock artifact changed before run: .calcchain/build/build_lock.json')
        return
    if actual != build_result.build_lock_sha256:
        blockers.append('build lock artifact changed before run: .calcchain/build/build_lock.json')


def _code_paths(build_result: BuildResult) -> list[str]:
    return sorted(entry.work_path for entry in build_result.code_set.map if entry.work_path is not None)


def _sha256_bytes(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()
