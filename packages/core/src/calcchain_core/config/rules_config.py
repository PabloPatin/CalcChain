import json
from pathlib import Path, PurePosixPath
from typing import Iterable

from calcchain_core.common.errors import ConfigFormatError, RulesError
from calcchain_core.mapping.trans_map import TranslationMapError, create_file_translation_map
from calcchain_core.models import FileMapEntry, RuleSet, RuleSetType, RulesFile


def read_rules(path: Path) -> RulesFile:
    return load_rules(path)


def load_rules(path: Path) -> RulesFile:
    path = Path(path)
    try:
        with path.open('r', encoding='utf-8') as file:
            data = json.load(file)
    except json.JSONDecodeError as err:
        raise ConfigFormatError(f'invalid rules json: {path}') from err
    return RulesFile.from_dict(data)


def get_rule_set(rules: RulesFile, name: str, expected_type: RuleSetType) -> RuleSet:
    try:
        rule_set = rules.rule_sets[name]
    except KeyError as err:
        raise RulesError(f'missing rule set: {name}') from err
    if rule_set.type is not expected_type:
        raise RulesError(
            f'rule set {name} has type {rule_set.type.value}, expected {expected_type.value}',
        )
    return rule_set


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
            sha256='',
            source_path=_normalize_relative_path(source.as_posix(), field='source path'),
            work_path=_normalize_relative_path(destination.as_posix(), field='destination path'),
        )
        for source, destination in translation_map.items()
    ]
    _ensure_unique_destinations(entry.work_path for entry in entries)
    return sorted(entries, key=lambda entry: (entry.work_path or '', entry.source_path or ''))


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
