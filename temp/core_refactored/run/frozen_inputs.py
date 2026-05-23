from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from ..common.errors import RunExecutionError
from ..io.source import SourceRef, SourceRegistry
from ..utils.json import write_json
from ..workspace.file_map import FileMapEntry
from ..workspace.layout import JobLayout
from ..workspace.maps import FileSetMap
from ..workspace.snapshot import Snapshot, diff_snapshots

if TYPE_CHECKING:
    from ..build.builder import BuildResult


def freeze_effective_inputs(
    layout: JobLayout,
    build_result: 'BuildResult',
    pre_run_snapshot: Snapshot,
    *,
    freeze_non_versionable: bool = True,
    registry: SourceRegistry | None = None,
) -> FileSetMap | None:
    pre_run_entries = {entry.path: entry for entry in pre_run_snapshot.entries}
    input_paths = _input_paths(build_result)
    non_versionable_paths = _non_versionable_input_paths(build_result, registry) if freeze_non_versionable else set()
    changed_paths = _changed_input_paths(build_result.build_snapshot, pre_run_snapshot, input_paths)
    paths_to_freeze = sorted((changed_paths | non_versionable_paths) & set(pre_run_entries))
    if not paths_to_freeze:
        return None

    frozen_entries: list[FileMapEntry] = []
    for work_path in paths_to_freeze:
        snapshot_entry = pre_run_entries[work_path]
        destination = _safe_frozen_path(layout.frozen_inputs_dir, work_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        source_path = _safe_work_path(layout.work_dir, work_path)
        destination.write_bytes(source_path.read_bytes())
        frozen_entries.append(
            FileMapEntry(
                sha256=snapshot_entry.sha256,
                source_path=work_path,
                work_path=work_path,
                target_path=destination.relative_to(layout.frozen_inputs_dir).as_posix(),
            ),
        )

    frozen_set = FileSetMap(
        name='frozen_inputs',
        tree_sha256=_tree_sha256(frozen_entries),
        sources=[SourceRef.from_dict({'type': 'local', 'path': str(layout.frozen_inputs_dir)})],
        rules=None,
        map=frozen_entries,
    )
    write_json(frozen_set.to_dict(), layout.frozen_inputs_dir / 'frozen_inputs.json')
    return frozen_set


def _input_paths(build_result: 'BuildResult') -> set[str]:
    return {
        entry.work_path
        for input_set in build_result.input_sets
        for entry in input_set.map
        if entry.work_path is not None
    }


def _non_versionable_input_paths(build_result: 'BuildResult', registry: SourceRegistry | None) -> set[str]:
    if registry is None or not hasattr(registry, 'is_versionable'):
        return set()
    result: set[str] = set()
    for input_set in build_result.input_sets:
        if any(not registry.is_versionable(source) for source in input_set.sources):
            result.update(entry.work_path for entry in input_set.map if entry.work_path is not None)
    return result


def _changed_input_paths(build_snapshot: Snapshot, pre_run_snapshot: Snapshot, input_paths: set[str]) -> set[str]:
    diff = diff_snapshots(build_snapshot, pre_run_snapshot)
    changed = {entry.path for entry in [*diff.added, *diff.modified]}
    deleted = {entry.path for entry in diff.deleted}
    return (changed - deleted) & input_paths


def _safe_frozen_path(root: Path, relative_path: str) -> Path:
    return _safe_join(root, relative_path)


def _safe_work_path(root: Path, relative_path: str) -> Path:
    path = _safe_join(root, relative_path)
    if not path.is_file():
        raise RunExecutionError(f'input file to freeze is missing: {relative_path}')
    return path


def _safe_join(root: Path, relative_path: str) -> Path:
    normalized = relative_path.replace('\\', '/')
    if normalized.startswith('/') or _has_windows_drive(normalized):
        raise RunExecutionError(f'frozen input path must be relative: {relative_path}')
    path = PurePosixPath(normalized)
    if '..' in path.parts or path.as_posix() in {'', '.'}:
        raise RunExecutionError(f'frozen input path is unsafe: {relative_path}')
    root_resolved = root.resolve(strict=False)
    result = root.joinpath(*path.parts)
    try:
        result.resolve(strict=False).relative_to(root_resolved)
    except ValueError as err:
        raise RunExecutionError(f'frozen input path escapes service area: {relative_path}') from err
    return result


def _tree_sha256(entries: list[FileMapEntry]) -> str:
    from ..common.hash import tree_sha256

    return tree_sha256((entry.work_path or '', entry.sha256) for entry in entries)


def _has_windows_drive(value: str) -> bool:
    return len(value) >= 2 and value[1] == ':' and value[0].isalpha()
