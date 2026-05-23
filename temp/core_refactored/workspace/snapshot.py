from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..common.hash import sha256_file
from ..config import SNAPSHOT_SCHEMA_VERSION
from ..utils.files import normalize_path
from ..utils.json import read_json, write_json
from ..utils.validation import mapping_value, optional_str, required_list, required_str


@dataclass(frozen=True)
class SnapshotEntry:
    path: str
    sha256: str
    size: int
    kind: str = 'file'

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]):
        size = data.get('size')
        if not isinstance(size, int):
            from ..common.errors import ConfigFormatError

            raise ConfigFormatError('size must be an integer')
        return cls(
            path=required_str(data, 'path'),
            sha256=required_str(data, 'sha256'),
            size=size,
            kind=optional_str(data, 'kind') or 'file',
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            'path': self.path,
            'sha256': self.sha256,
            'size': self.size,
            'kind': self.kind,
        }


@dataclass(frozen=True)
class Snapshot:
    schema_version: str
    created_at: str
    entries: list[SnapshotEntry]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]):
        return cls(
            schema_version=optional_str(data, 'schema_version') or SNAPSHOT_SCHEMA_VERSION,
            created_at=required_str(data, 'created_at'),
            entries=[
                SnapshotEntry.from_dict(mapping_value(item, f'entries[{index}]'))
                for index, item in enumerate(required_list(data, 'entries'), start=1)
            ],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            'schema_version': self.schema_version,
            'created_at': self.created_at,
            'entries': [entry.to_dict() for entry in self.entries],
        }


def create_snapshot(root: Path) -> Snapshot:
    root = Path(root)
    entries = [
        _snapshot_entry(root, file)
        for file in sorted(root.rglob('*'))
        if file.is_file()
    ]
    return Snapshot(
        schema_version=SNAPSHOT_SCHEMA_VERSION,
        created_at=datetime.now(timezone.utc).isoformat(),
        entries=entries,
    )


def read_snapshot(path: Path) -> Snapshot:
    return Snapshot.from_dict(read_json(path))


def write_snapshot(snapshot: Snapshot, path: Path) -> None:
    write_json(snapshot.to_dict(), path)


def _snapshot_entry(root: Path, file: Path) -> SnapshotEntry:
    relative_path = normalize_path(file.relative_to(root).as_posix())
    return SnapshotEntry(
        path=relative_path,
        sha256=sha256_file(file),
        size=file.stat().st_size,
    )
