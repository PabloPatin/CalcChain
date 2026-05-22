from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Self

from calcchain_core.common.errors import ConfigFormatError
from calcchain_core.models.common import (
    LockMetadata,
    optional_mapping,
    optional_str,
    put_optional,
    required_list,
    required_mapping,
    required_sha256,
    schema_version,
)
from calcchain_core.models.sources import SourceRef


@dataclass(frozen=True)
class CodeConfig:
    source: SourceRef
    name: str = ''
    version: str = ''
    rule_set: str | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, resolved_revision: bool = False) -> Self:
        source = SourceRef.from_dict(required_mapping(data, 'source'), resolved_revision=resolved_revision)
        return cls(
            source=source,
            name=optional_str(data, 'name') or _default_name_from_ref(source),
            version=optional_str(data, 'version') or '',
            rule_set=optional_str(data, 'rule_set'),
        )

    def to_dict(self) -> dict[str, Any]:
        result = {'name': self.name, 'version': self.version}
        put_optional(result, 'rule_set', self.rule_set)
        result['source'] = self.source.to_dict()
        return result


@dataclass(frozen=True)
class InputConfig:
    source: SourceRef
    name: str
    rule_set: str | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, index: int, resolved_revision: bool = False) -> Self:
        return cls(
            source=SourceRef.from_dict(required_mapping(data, 'source'), resolved_revision=resolved_revision),
            name=optional_str(data, 'name') or f'input_{index}',
            rule_set=optional_str(data, 'rule_set'),
        )

    def to_dict(self) -> dict[str, Any]:
        result = {'name': self.name}
        put_optional(result, 'rule_set', self.rule_set)
        result['source'] = self.source.to_dict()
        return result


@dataclass(frozen=True)
class BuildInfo:
    name: str
    description: str = ''

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None, *, default_name: str = '') -> Self:
        if data is None:
            return cls(name=default_name, description='')
        return cls(name=optional_str(data, 'name') or default_name, description=optional_str(data, 'description') or '')

    def to_dict(self) -> dict[str, Any]:
        return {'name': self.name, 'description': self.description}


@dataclass(frozen=True)
class RulesReference:
    source: SourceRef | None = None
    resolved: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None, *, resolved_revision: bool = False) -> Self | None:
        if data is None:
            return None
        source = None
        if 'source' in data:
            source = SourceRef.from_dict(required_mapping(data, 'source'), resolved_revision=resolved_revision)
        resolved = dict(required_mapping(data, 'resolved')) if 'resolved' in data else None
        if resolved is not None:
            schema_version(resolved)
            required_sha256(resolved, 'sha256')
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
    def from_dict(cls, data: Mapping[str, Any], *, default_build_name: str = '') -> Self:
        version = schema_version(data)
        code = CodeConfig.from_dict(required_mapping(data, 'code'))
        inputs = [InputConfig.from_dict(item, index=index) for index, item in enumerate(required_list(data, 'inputs'), start=1)]
        if not inputs:
            raise ConfigFormatError('inputs must not be empty')
        rules = RulesReference.from_dict(optional_mapping(data, 'rules'))
        _validate_rule_source_presence(code, inputs, rules)
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


@dataclass(frozen=True)
class BuildLock:
    schema_version: str
    lock: LockMetadata
    build: BuildInfo
    code: CodeConfig
    inputs: list[InputConfig]
    rules: RulesReference | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        version = schema_version(data)
        code = CodeConfig.from_dict(required_mapping(data, 'code'), resolved_revision=True)
        inputs = [
            InputConfig.from_dict(item, index=index, resolved_revision=True)
            for index, item in enumerate(required_list(data, 'inputs'), start=1)
        ]
        if not inputs:
            raise ConfigFormatError('inputs must not be empty')
        rules = RulesReference.from_dict(optional_mapping(data, 'rules'), resolved_revision=True)
        _validate_rule_source_presence(code, inputs, rules)
        return cls(
            schema_version=version,
            lock=LockMetadata.from_dict(required_mapping(data, 'lock'), source_field='build_toml_sha256'),
            build=BuildInfo.from_dict(optional_mapping(data, 'build')),
            code=code,
            inputs=inputs,
            rules=rules,
        )

    def to_dict(self) -> dict[str, Any]:
        result = {
            'schema_version': self.schema_version,
            'lock': self.lock.to_dict(),
            'build': self.build.to_dict(),
            'code': self.code.to_dict(),
            'inputs': [item.to_dict() for item in self.inputs],
        }
        if self.rules is not None:
            result['rules'] = self.rules.to_dict()
        return result


def _validate_rule_source_presence(code: CodeConfig, inputs: Sequence[InputConfig], rules: RulesReference | None) -> None:
    has_rule_use = code.rule_set is not None or any(item.rule_set is not None for item in inputs)
    if has_rule_use and (rules is None or rules.source is None):
        raise ConfigFormatError('rules.source is required when rule_set is used')


def _default_name_from_ref(ref: SourceRef) -> str:
    path = ref.path or ref.location or ''
    normalized = path.replace('\\', '/').strip('/')
    if not normalized:
        return ''
    return normalized.rsplit('/', maxsplit=1)[-1]
