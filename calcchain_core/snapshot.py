from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from calcchain_core.hash import sha256_file


@dataclass(frozen=True)
class SnapshotEntry:
    path: str
    sha256: str
    size: int
    mtime_utc: str
    kind: str = 'file'

    def to_dict(self) -> dict[str, Any]:
        return {
            'path': self.path,
            'sha256': self.sha256,
            'size': self.size,
            'mtime_utc': self.mtime_utc,
            'kind': self.kind,
        }


@dataclass(frozen=True)
class Snapshot:
    schema_version: str
    created_at: str
    entries: list[SnapshotEntry]

    def to_dict(self) -> dict[str, Any]:
        return {
            'schema_version': self.schema_version,
            'created_at': self.created_at,
            'entries': [entry.to_dict() for entry in self.entries],
        }


@dataclass(frozen=True)
class SnapshotDiff:
    added: list[SnapshotEntry]
    modified: list[SnapshotEntry]
    deleted: list[SnapshotEntry]
    unchanged: list[SnapshotEntry]

    def to_dict(self) -> dict[str, Any]:
        return {
            'added': [entry.to_dict() for entry in self.added],
            'modified': [entry.to_dict() for entry in self.modified],
            'deleted': [entry.to_dict() for entry in self.deleted],
            'unchanged': [entry.to_dict() for entry in self.unchanged],
        }


def create_snapshot(root: Path) -> Snapshot:
    root = Path(root)
    entries: list[SnapshotEntry] = []
    if root.exists():
        for path in sorted(file for file in root.rglob('*') if file.is_file()):
            stat = path.stat()
            entries.append(
                SnapshotEntry(
                    path=path.relative_to(root).as_posix(),
                    sha256=sha256_file(path),
                    size=stat.st_size,
                    mtime_utc=datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                ),
            )
    return Snapshot(
        schema_version='1.0',
        created_at=datetime.now(timezone.utc).isoformat(),
        entries=entries,
    )


def diff_snapshots(before: Snapshot, after: Snapshot) -> SnapshotDiff:
    before_by_path = {entry.path: entry for entry in before.entries}
    after_by_path = {entry.path: entry for entry in after.entries}

    added = [after_by_path[path] for path in sorted(after_by_path.keys() - before_by_path.keys())]
    deleted = [before_by_path[path] for path in sorted(before_by_path.keys() - after_by_path.keys())]
    modified = [
        after_by_path[path]
        for path in sorted(before_by_path.keys() & after_by_path.keys())
        if before_by_path[path].sha256 != after_by_path[path].sha256
        or before_by_path[path].size != after_by_path[path].size
    ]
    unchanged = [
        after_by_path[path]
        for path in sorted(before_by_path.keys() & after_by_path.keys())
        if before_by_path[path].sha256 == after_by_path[path].sha256
        and before_by_path[path].size == after_by_path[path].size
    ]
    return SnapshotDiff(added=added, modified=modified, deleted=deleted, unchanged=unchanged)
