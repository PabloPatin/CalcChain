from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..io.source import SourceRef
from ..utils.validation import (
    mapping_value,
    optional_list,
    optional_mapping,
    optional_str,
    required_sha256,
    required_mapping,
)
from ..config import BUILD_CONFIG_SCHEMA_VERSION, RULES_FILE_SCHEMA_VERSION


@dataclass(frozen=True)
class CodeConfig:
    source: SourceRef
    name: str = ''
    version: str = ''
    rule_set: str | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]):
        return cls(
            source=SourceRef.from_dict(dict(required_mapping(data, 'source'))),
            name=optional_str(data, 'name') or '',
            version=optional_str(data, 'version') or '',
            rule_set=optional_str(data, 'rule_set'),
        )

    def to_dict(self) -> dict[str, Any]:
        result = {
            'name': self.name,
            'version': self.version,
            'source': self.source.to_dict(),
        }
        if self.rule_set is not None:
            result['rule_set'] = self.rule_set
        return result


@dataclass(frozen=True)
class InputConfig:
    source: SourceRef
    name: str
    rule_set: str | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, index: int):
        return cls(
            source=SourceRef.from_dict(dict(required_mapping(data, 'source'))),
            name=optional_str(data, 'name') or f'input_{index}',
            rule_set=optional_str(data, 'rule_set'),
        )

    def to_dict(self) -> dict[str, Any]:
        result = {
            'name': self.name,
            'source': self.source.to_dict(),
        }
        if self.rule_set is not None:
            result['rule_set'] = self.rule_set
        return result


@dataclass(frozen=True)
class BuildInfo:
    name: str
    description: str = ''

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None, *, default_name: str = ''):
        if data is None:
            return cls(name=default_name)
        return cls(
            name=optional_str(data, 'name') or default_name,
            description=optional_str(data, 'description') or '',
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            'name': self.name,
            'description': self.description,
        }


@dataclass(frozen=True)
class RulesReference:
    source: SourceRef | None = None
    resolved: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None):
        if data is None:
            return None
        source = SourceRef.from_dict(dict(required_mapping(data, 'source'))) if 'source' in data else None
        resolved = None
        if 'resolved' in data:
            resolved_data = required_mapping(data, 'resolved')
            resolved = {
                'schema_version': optional_str(resolved_data, 'schema_version') or RULES_FILE_SCHEMA_VERSION,
                'sha256': required_sha256(resolved_data, 'sha256'),
            }
        return cls(source=source, resolved=resolved)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if self.source is not None:
            result['source'] = self.source.to_dict()
        if self.resolved is not None:
            result['resolved'] = dict(self.resolved)
        return result


@dataclass(frozen=True)
class BuildConfig:
    schema_version: str
    build: BuildInfo
    code: CodeConfig
    inputs: list[InputConfig]
    rules: RulesReference | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, default_build_name: str = ''):
        version = optional_str(data, 'schema_version') or BUILD_CONFIG_SCHEMA_VERSION
        code = CodeConfig.from_dict(required_mapping(data, 'code'))
        input_items = optional_list(data, 'inputs')
        inputs = [
            InputConfig.from_dict(mapping_value(item, f'inputs[{index}]'), index=index)
            for index, item in enumerate(input_items, start=1)
        ]
        rules = RulesReference.from_dict(optional_mapping(data, 'rules'))
        return cls(
            schema_version=version,
            build=BuildInfo.from_dict(optional_mapping(data, 'build'), default_name=default_build_name),
            code=code,
            inputs=inputs,
            rules=rules,
        )

    def to_dict(self) -> dict[str, Any]:
        result = {
            'schema_version': self.schema_version,
            'build': self.build.to_dict(),
            'code': self.code.to_dict(),
            'inputs': [item.to_dict() for item in self.inputs],
        }
        if self.rules is not None:
            result['rules'] = self.rules.to_dict()
        return result
