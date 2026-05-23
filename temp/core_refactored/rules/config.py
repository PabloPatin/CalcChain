from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
import json
from pathlib import Path, PurePosixPath
from typing import Any

from ..common.errors import ConfigFormatError, RulesError
from ..utils.validation import (
    mapping_value,
    optional_mapping,
    optional_str,
    required_list,
    required_mapping,
    required_str,
    string_value,
)
from .mapping.trans_map import TranslationMapError, create_file_translation_map
from ..config import RULES_FILE_SCHEMA_VERSION

class RuleSetType(StrEnum):
    CODE = 'code'
    INPUT = 'input'
    OUTPUT = 'output'
    LOGS = 'logs'
    TEMP = 'temp'
    IGNORE = 'ignore'


@dataclass(frozen=True)
class Rule:
    source: str
    destination: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]):
        return cls(source=required_str(data, 'source'), destination=required_str(data, 'destination'))

    def to_dict(self) -> dict[str, Any]:
        return {'source': self.source, 'destination': self.destination}


@dataclass(frozen=True)
class RuleSet:
    type: RuleSetType
    status: str
    description: str
    ensure_all_files: bool
    rules: list[Rule]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]):
        ensure_all_files = data.get('ensure_all_files', False)
        if not isinstance(ensure_all_files, bool):
            raise ConfigFormatError('ensure_all_files must be boolean')
        return cls(
            type=_rule_set_type(required_str(data, 'type')),
            status=optional_str(data, 'status') or '',
            description=optional_str(data, 'description') or '',
            ensure_all_files=ensure_all_files,
            rules=[Rule.from_dict(mapping_value(item, 'rule')) for item in required_list(data, 'rules')],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            'type': self.type.value,
            'status': self.status,
            'description': self.description,
            'ensure_all_files': self.ensure_all_files,
            'rules': [rule.to_dict() for rule in self.rules],
        }


@dataclass(frozen=True)
class RulesFile:
    schema_version: str
    rules_file: dict[str, Any]
    rule_sets: dict[str, RuleSet]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]):
        rule_sets = {
            string_value(name, 'rule set name'): RuleSet.from_dict(mapping_value(value, 'rule set'))
            for name, value in required_mapping(data, 'rule_sets').items()
        }
        if not rule_sets:
            raise ConfigFormatError('rule_sets must not be empty')
        return cls(
            schema_version=optional_str(data, 'schema_version') or RULES_FILE_SCHEMA_VERSION,
            rules_file=dict(optional_mapping(data, 'rules_file') or {}),
            rule_sets=rule_sets,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            'schema_version': self.schema_version,
            'rules_file': dict(self.rules_file),
            'rule_sets': {name: rule_set.to_dict() for name, rule_set in self.rule_sets.items()},
        }


@dataclass(frozen=True)
class RuleUse:
    set: str
    status: str | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]):
        return cls(set=required_str(data, 'set'), status=optional_str(data, 'status'))

    def to_dict(self) -> dict[str, Any]:
        result = {'set': self.set}
        if self.status is not None:
            result['status'] = self.status
        return result


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


def read_rules(path: Path) -> RulesFile:
    return load_rules(path)


def load_rules(path: Path) -> RulesFile:
    path = Path(path)
    try:
        with path.open('r', encoding='utf-8') as file:
            data = json.load(file)
    except json.JSONDecodeError as err:
        raise ConfigFormatError(f'invalid rules json: {path}') from err
    return RulesFile.from_dict(mapping_value(data, 'rules file'))


def get_rule_set(rules: RulesFile, name: str, expected_type: RuleSetType) -> RuleSet:
    try:
        rule_set = rules.rule_sets[name]
    except KeyError as err:
        raise RulesError(f'missing rule set: {name}') from err
    if rule_set.type is not expected_type:
        raise RulesError(f'rule set {name} has type {rule_set.type.value}, expected {expected_type.value}')
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


def _rule_set_type(value: str) -> RuleSetType:
    try:
        return RuleSetType(value)
    except ValueError as err:
        raise ConfigFormatError(f'unsupported rule set type: {value}') from err
