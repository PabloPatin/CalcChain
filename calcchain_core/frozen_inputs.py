from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path, PurePosixPath
from typing import Any

from calcchain_core.builder import BuildResult
from calcchain_core.errors import BuildExecutionError
from calcchain_core.hash import tree_sha256
from calcchain_core.layout import JobLayout
from calcchain_core.models import FileMapEntry, SourceRef, SourceType
from calcchain_core.snapshot import Snapshot, diff_snapshots


@dataclass(frozen=True)
class FrozenInputSet:
    name: str
    tree_sha256: str
    source: SourceRef
    map: list[FileMapEntry]

    def to_dict(self) -> dict[str, Any]:
        return {
            'name': self.name,
            'tree_sha256': self.tree_sha256,
            'source': self.source.to_dict(),
            'map': [entry.to_dict() for entry in self.map],
        }


def freeze_effective_inputs(
    layout: JobLayout,
    build_result: BuildResult,
    pre_run_snapshot: Snapshot,
    *,
    freeze_non_versionable: bool = True,
) -> FrozenInputSet | None:
    pre_run_entries = {entry.path: entry for entry in pre_run_snapshot.entries}
    input_paths = _input_paths(build_result)
    non_versionable_paths = _non_versionable_input_paths(build_result) if freeze_non_versionable else set()
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
        source_bytes = source_path.read_bytes()
        destination.write_bytes(source_bytes)
        frozen_entries.append(
            FileMapEntry(
                sha256=snapshot_entry.sha256,
                source_path=work_path,
                work_path=work_path,
                target_path=destination.relative_to(layout.frozen_inputs_dir).as_posix(),
            ),
        )

    frozen_set = FrozenInputSet(
        name='frozen_inputs',
        tree_sha256=tree_sha256((entry.work_path or '', entry.sha256) for entry in frozen_entries),
        source=SourceRef(type=SourceType.LOCAL, path=str(layout.frozen_inputs_dir)),
        map=frozen_entries,
    )
    _write_json(layout.frozen_inputs_dir / 'frozen_inputs.json', frozen_set.to_dict())
    return frozen_set


def _input_paths(build_result: BuildResult) -> set[str]:
    return {
        entry.work_path
        for input_set in build_result.input_sets
        for entry in input_set.map
        if entry.work_path is not None
    }


def _non_versionable_input_paths(build_result: BuildResult) -> set[str]:
    result: set[str] = set()
    for input_set in build_result.input_sets:
        sources = [input_set.source] if input_set.source is not None else list(input_set.sources)
        if any(source.type is SourceType.LOCAL for source in sources if source is not None):
            result.update(entry.work_path for entry in input_set.map if entry.work_path is not None)
    return result


def _changed_input_paths(build_snapshot: Snapshot, pre_run_snapshot: Snapshot, input_paths: set[str]) -> set[str]:
    diff = diff_snapshots(build_snapshot, pre_run_snapshot)
    changed = {entry.path for entry in diff.added + diff.modified}
    deleted = {entry.path for entry in diff.deleted}
    return (changed - deleted) & input_paths


def _safe_frozen_path(root: Path, relative_path: str) -> Path:
    return _safe_join(root, relative_path)


def _safe_work_path(root: Path, relative_path: str) -> Path:
    path = _safe_join(root, relative_path)
    if not path.is_file():
        raise BuildExecutionError(f'input file to freeze is missing: {relative_path}')
    return path


def _safe_join(root: Path, relative_path: str) -> Path:
    normalized = relative_path.replace('\\', '/')
    if normalized.startswith('/') or _has_windows_drive(normalized):
        raise BuildExecutionError(f'frozen input path must be relative: {relative_path}')
    path = PurePosixPath(normalized)
    if '..' in path.parts or path.as_posix() in {'', '.'}:
        raise BuildExecutionError(f'frozen input path is unsafe: {relative_path}')
    root_resolved = root.resolve()
    result = root.joinpath(*path.parts)
    try:
        result.resolve(strict=False).relative_to(root_resolved)
    except ValueError as err:
        raise BuildExecutionError(f'frozen input path escapes service area: {relative_path}') from err
    return result


def _has_windows_drive(value: str) -> bool:
    return len(value) >= 2 and value[1] == ':' and value[0].isalpha()


def _write_json(path: Path, data: Any) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + '\n',
        encoding='utf-8',
    )
