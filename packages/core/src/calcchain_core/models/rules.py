from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Self

from calcchain_core.common.errors import ConfigFormatError
from calcchain_core.models.common import mapping_value, optional_mapping, optional_str, required_list, required_mapping, required_str, schema_version, string_value


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
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
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
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        ensure_all_files = data.get('ensure_all_files', False)
        if not isinstance(ensure_all_files, bool):
            raise ConfigFormatError('ensure_all_files must be boolean')
        return cls(
            type=RuleSetType(required_str(data, 'type')),
            status=optional_str(data, 'status') or '',
            description=optional_str(data, 'description') or '',
            ensure_all_files=ensure_all_files,
            rules=[Rule.from_dict(item) for item in required_list(data, 'rules')],
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
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        version = schema_version(data)
        rule_sets = {
            string_value(name, 'rule set name'): RuleSet.from_dict(mapping_value(value, 'rule set'))
            for name, value in required_mapping(data, 'rule_sets').items()
        }
        if not rule_sets:
            raise ConfigFormatError('rule_sets must not be empty')
        return cls(schema_version=version, rules_file=dict(optional_mapping(data, 'rules_file') or {}), rule_sets=rule_sets)

    def to_dict(self) -> dict[str, Any]:
        return {
            'schema_version': self.schema_version,
            'rules_file': dict(self.rules_file),
            'rule_sets': {name: rule_set.to_dict() for name, rule_set in self.rule_sets.items()},
        }
