from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from ..common.errors import RulesError
from ..rules import RuleSet
from ..rules.mapping.trans_map import TranslationMapError, create_file_translation_map
from ..utils.validation import optional_str


@dataclass(frozen=True)
class FileMapEntry:
    sha256: str = ''
    source_path: str | None = None
    work_path: str | None = None
    target_path: str | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]):
        return cls(
            sha256=optional_str(data, 'sha256') or '',
            source_path=optional_str(data, 'source_path'),
            work_path=optional_str(data, 'work_path'),
            target_path=optional_str(data, 'target_path'),
        )

    def to_dict(self) -> dict[str, Any]:
        result = {'sha256': self.sha256}
        if self.source_path is not None:
            result['source_path'] = self.source_path
        if self.work_path is not None:
            result['work_path'] = self.work_path
        if self.target_path is not None:
            result['target_path'] = self.target_path
        return result


def apply_rule_set(files: list[str], rule_set: RuleSet) -> list[FileMapEntry]:
    safe_files = [_normalize_relative_path(file, field='source path') for file in files]
    if len(safe_files) != len(set(safe_files)):
        raise RulesError('source file list contains duplicate paths')
    try:
        translation_map = create_file_translation_map(
            files=[Path(file) for file in safe_files],
            rules=[[rule.source, rule.destination] for rule in rule_set.rules],
            additional_markers={},
            check_skipped_files=rule_set.ensure_all_files,
        )
    except TranslationMapError as err:
        raise RulesError(str(err)) from err

    entries = [
        FileMapEntry(
            source_path=_normalize_relative_path(source.as_posix(), field='source path'),
            work_path=_normalize_relative_path(destination.as_posix(), field='destination path'),
        )
        for source, destination in translation_map.items()
    ]
    _ensure_unique_destinations(entry.work_path for entry in entries)
    return sorted(entries, key=lambda entry: (entry.work_path or '', entry.source_path or ''))


def full_tree_map(files: list[str]) -> list[FileMapEntry]:
    entries = [
        FileMapEntry(source_path=safe_file, work_path=safe_file)
        for safe_file in sorted(_normalize_relative_path(file, field='source path') for file in files)
    ]
    _ensure_unique_destinations(entry.work_path for entry in entries)
    return entries


def _ensure_unique_destinations(destinations: Iterable[str | None]) -> None:
    seen: set[str] = set()
    for destination in destinations:
        if destination is None:
            raise RulesError('destination path is required')
        if destination in seen:
            raise RulesError(f'duplicate destination path: {destination}')
        seen.add(destination)


def _normalize_relative_path(value: str, *, field: str) -> str:
    normalized = value.replace('\\', '/')
    if normalized.startswith('/') or _has_windows_drive(normalized):
        raise RulesError(f'{field} must be relative: {value}')
    path = PurePosixPath(normalized)
    if '..' in path.parts:
        raise RulesError(f'{field} must not contain path traversal: {value}')
    result = path.as_posix()
    if result in {'', '.'}:
        raise RulesError(f'{field} must identify a file: {value}')
    return result


def _has_windows_drive(value: str) -> bool:
    return len(value) >= 2 and value[1] == ':' and value[0].isalpha()
