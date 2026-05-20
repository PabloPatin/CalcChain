from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from enum import StrEnum
import re
from typing import Any, Self
from urllib.parse import urlsplit

from calcchain_core.errors import ConfigFormatError, UnsupportedSchemaVersionError
from calcchain_capabilities import PluginRefMetadata

LATEST_SCHEMA_VERSION = '1.0'
SUPPORTED_SCHEMA_VERSIONS = {'1.0'}

_SHA256_RE = re.compile(r'^[0-9a-fA-F]{64}$')


class SourceType(StrEnum):
    LOCAL = 'local'
    SVN = 'svn'


class RuleSetType(StrEnum):
    CODE = 'code'
    INPUT = 'input'
    OUTPUT = 'output'
    LOGS = 'logs'
    TEMP = 'temp'
    IGNORE = 'ignore'


class JobStatus(StrEnum):
    BUILT = 'Built'
    SUCCEEDED = 'Succeeded'
    FAILED = 'Failed'
    TIMEOUT = 'Timeout'
    CANCELLED = 'Cancelled'
    KILLED = 'Killed'
    PUBLISHED = 'Published'


class RunStatus(StrEnum):
    SUCCEEDED = 'Succeeded'
    FAILED = 'Failed'
    TIMEOUT = 'Timeout'
    CANCELLED = 'Cancelled'
    KILLED = 'Killed'


@dataclass(frozen=True)
class SourceRef:
    type: SourceType | str
    path: str = ''
    location: str | None = None
    revision: str | int | None = None
    plugin: PluginRefMetadata | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, 'type', _ref_type(self.type))
        _string_value(self.path, 'path')

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
        *,
        resolved_revision: bool = False,
        reject_userinfo: bool = False,
    ) -> Self:
        ref_type = _ref_type(_required_str(data, 'type'))
        location = _optional_str(data, 'location')
        path = _optional_str(data, 'path') or ''
        revision = data.get('revision')
        plugin = _optional_plugin_metadata(data)
        extra = _extra_ref_fields(data, {'type', 'path', 'location', 'revision', 'plugin'})

        if _is_ref_type(ref_type, SourceType.LOCAL):
            if location is not None:
                raise ConfigFormatError('local source must not define location')
            if revision is not None:
                raise ConfigFormatError('local source must not define revision')
            if not path:
                raise ConfigFormatError('missing required field: path')
            return cls(type=ref_type, path=path, plugin=plugin, extra=extra)

        if not _is_ref_type(ref_type, SourceType.SVN):
            return cls(
                type=ref_type,
                location=location,
                path=path,
                revision=_serializable_value(revision, 'revision') if revision is not None else None,
                plugin=plugin,
                extra=extra,
            )

        if location is None:
            raise ConfigFormatError('svn source requires location')
        if not path:
            raise ConfigFormatError('missing required field: path')
        if reject_userinfo:
            _validate_svn_location(location, field='source')
        _validate_svn_revision(revision, resolved_revision=resolved_revision, field='source')
        if revision is None:
            revision = 'HEAD'
        return cls(type=ref_type, location=location, path=path, revision=revision, plugin=plugin, extra=extra)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {'type': _ref_type_value(self.type)}
        if _is_ref_type(self.type, SourceType.LOCAL) and not self.path:
            raise ConfigFormatError('missing required field: path')
        if self.location is not None:
            if _is_ref_type(self.type, SourceType.LOCAL):
                raise ConfigFormatError('local source must not define location')
            if _is_ref_type(self.type, SourceType.SVN):
                _validate_svn_location(self.location, field='source')
            result['location'] = self.location
        elif _is_ref_type(self.type, SourceType.SVN):
            raise ConfigFormatError('svn source requires location')
        if _is_ref_type(self.type, SourceType.SVN) and not self.path:
            raise ConfigFormatError('missing required field: path')
        if self.path or _is_ref_type(self.type, SourceType.LOCAL) or _is_ref_type(self.type, SourceType.SVN):
            result['path'] = self.path
        if self.revision is not None:
            if _is_ref_type(self.type, SourceType.LOCAL):
                raise ConfigFormatError('local source must not define revision')
            if _is_ref_type(self.type, SourceType.SVN):
                _validate_svn_revision(self.revision, resolved_revision=False, field='source')
                result['revision'] = self.revision
            else:
                result['revision'] = _serializable_value(self.revision, 'revision')
        if self.plugin is not None:
            result['plugin'] = self.plugin.to_dict()
        result.update(_serializable_mapping(self.extra, 'source extra'))
        return result


@dataclass(frozen=True)
class TargetRef:
    type: SourceType | str
    path: str = ''
    location: str | None = None
    revision: str | int | None = None
    plugin: PluginRefMetadata | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, 'type', _ref_type(self.type))
        _string_value(self.path, 'path')

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
        *,
        resolved_revision: bool = False,
        reject_userinfo: bool = False,
    ) -> Self:
        ref_type = _ref_type(_required_str(data, 'type'))
        path = _optional_str(data, 'path') or ''
        location = _optional_str(data, 'location')
        revision = data.get('revision')
        plugin = _optional_plugin_metadata(data)
        extra = _extra_ref_fields(data, {'type', 'path', 'location', 'revision', 'plugin'})

        if _is_ref_type(ref_type, SourceType.LOCAL):
            if location is not None:
                raise ConfigFormatError('local target must not define location')
            if revision is not None:
                raise ConfigFormatError('local target must not define revision')
            if not path:
                raise ConfigFormatError('missing required field: path')
            return cls(type=ref_type, path=path, plugin=plugin, extra=extra)

        if not _is_ref_type(ref_type, SourceType.SVN):
            return cls(
                type=ref_type,
                path=path,
                location=location,
                revision=_serializable_value(revision, 'revision') if revision is not None else None,
                plugin=plugin,
                extra=extra,
            )

        if location is None:
            raise ConfigFormatError('svn target requires location')
        if not path:
            raise ConfigFormatError('missing required field: path')
        if reject_userinfo:
            _validate_svn_location(location, field='target')
        _validate_svn_revision(revision, resolved_revision=resolved_revision, field='target')
        if revision is None:
            revision = 'HEAD'
        return cls(type=ref_type, location=location, path=path, revision=revision, plugin=plugin, extra=extra)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {'type': _ref_type_value(self.type)}
        if _is_ref_type(self.type, SourceType.LOCAL) and not self.path:
            raise ConfigFormatError('missing required field: path')
        if self.location is not None:
            if _is_ref_type(self.type, SourceType.LOCAL):
                raise ConfigFormatError('local target must not define location')
            if _is_ref_type(self.type, SourceType.SVN):
                _validate_svn_location(self.location, field='target')
            result['location'] = self.location
        elif _is_ref_type(self.type, SourceType.SVN):
            raise ConfigFormatError('svn target requires location')
        if _is_ref_type(self.type, SourceType.SVN) and not self.path:
            raise ConfigFormatError('missing required field: path')
        if self.path or _is_ref_type(self.type, SourceType.LOCAL) or _is_ref_type(self.type, SourceType.SVN):
            result['path'] = self.path
        if self.revision is not None:
            if _is_ref_type(self.type, SourceType.LOCAL):
                raise ConfigFormatError('local target must not define revision')
            if _is_ref_type(self.type, SourceType.SVN):
                _validate_svn_revision(self.revision, resolved_revision=False, field='target')
                result['revision'] = self.revision
            else:
                result['revision'] = _serializable_value(self.revision, 'revision')
        if self.plugin is not None:
            result['plugin'] = self.plugin.to_dict()
        result.update(_serializable_mapping(self.extra, 'target extra'))
        return result


@dataclass(frozen=True)
class ArtifactRef:
    sha256: str
    sources: list[SourceRef]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, reject_userinfo: bool = False) -> Self:
        sha256 = _required_sha256(data, 'sha256')
        sources = [
            SourceRef.from_dict(item, reject_userinfo=reject_userinfo)
            for item in _required_list(data, 'sources')
        ]
        if not sources:
            raise ConfigFormatError('artifact sources must not be empty')
        return cls(sha256=sha256, sources=sources)

    def to_dict(self) -> dict[str, Any]:
        return {'sha256': self.sha256, 'sources': [source.to_dict() for source in self.sources]}


@dataclass(frozen=True)
class RuleUse:
    set: str
    status: str | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        return cls(set=_required_str(data, 'set'), status=_optional_str(data, 'status'))

    def to_dict(self) -> dict[str, Any]:
        result = {'set': self.set}
        if self.status is not None:
            result['status'] = self.status
        return result


@dataclass(frozen=True)
class FileMapEntry:
    sha256: str
    source_path: str | None = None
    work_path: str | None = None
    target_path: str | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        return cls(
            sha256=_required_sha256(data, 'sha256'),
            source_path=_optional_str(data, 'source_path'),
            work_path=_optional_str(data, 'work_path'),
            target_path=_optional_str(data, 'target_path'),
        )

    def to_dict(self) -> dict[str, Any]:
        result = {'sha256': self.sha256}
        _put_optional(result, 'source_path', self.source_path)
        _put_optional(result, 'work_path', self.work_path)
        _put_optional(result, 'target_path', self.target_path)
        return result


@dataclass(frozen=True)
class CodeConfig:
    source: SourceRef
    name: str = ''
    version: str = ''
    rule_set: str | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, resolved_revision: bool = False) -> Self:
        source = SourceRef.from_dict(_required_mapping(data, 'source'), resolved_revision=resolved_revision)
        return cls(
            source=source,
            name=_optional_str(data, 'name') or _default_name_from_ref(source),
            version=_optional_str(data, 'version') or '',
            rule_set=_optional_str(data, 'rule_set'),
        )

    def to_dict(self) -> dict[str, Any]:
        result = {'name': self.name, 'version': self.version}
        _put_optional(result, 'rule_set', self.rule_set)
        result['source'] = self.source.to_dict()
        return result


@dataclass(frozen=True)
class InputConfig:
    source: SourceRef
    name: str
    rule_set: str | None = None

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
        *,
        index: int,
        resolved_revision: bool = False,
    ) -> Self:
        return cls(
            source=SourceRef.from_dict(
                _required_mapping(data, 'source'),
                resolved_revision=resolved_revision,
            ),
            name=_optional_str(data, 'name') or f'input_{index}',
            rule_set=_optional_str(data, 'rule_set'),
        )

    def to_dict(self) -> dict[str, Any]:
        result = {'name': self.name}
        _put_optional(result, 'rule_set', self.rule_set)
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
        return cls(
            name=_optional_str(data, 'name') or default_name,
            description=_optional_str(data, 'description') or '',
        )

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
            source = SourceRef.from_dict(
                _required_mapping(data, 'source'),
                resolved_revision=resolved_revision,
            )
        resolved = dict(_required_mapping(data, 'resolved')) if 'resolved' in data else None
        if resolved is not None:
            _schema_version(resolved)
            _required_sha256(resolved, 'sha256')
        return cls(source=source, resolved=resolved)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if self.source is not None:
            result['source'] = self.source.to_dict()
        if self.resolved is not None:
            result['resolved'] = dict(self.resolved)
        return result


@dataclass(frozen=True)
class LockMetadata:
    created_at: str
    created_from: str
    source_sha256: str
    source_sha256_field: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, source_field: str) -> Self:
        return cls(
            created_at=_required_str(data, 'created_at'),
            created_from=_required_str(data, 'created_from'),
            source_sha256=_required_sha256(data, source_field),
            source_sha256_field=source_field,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            'created_at': self.created_at,
            'created_from': self.created_from,
            self.source_sha256_field: self.source_sha256,
        }


@dataclass(frozen=True)
class BuildConfig:
    schema_version: str
    build: BuildInfo
    code: CodeConfig
    inputs: list[InputConfig]
    rules: RulesReference | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, default_build_name: str = '') -> Self:
        schema_version = _schema_version(data)
        code = CodeConfig.from_dict(_required_mapping(data, 'code'))
        inputs = [
            InputConfig.from_dict(item, index=index)
            for index, item in enumerate(_required_list(data, 'inputs'), start=1)
        ]
        if not inputs:
            raise ConfigFormatError('inputs must not be empty')
        rules = RulesReference.from_dict(_optional_mapping(data, 'rules'))
        _validate_rule_source_presence(code, inputs, rules)
        return cls(
            schema_version=schema_version,
            build=BuildInfo.from_dict(_optional_mapping(data, 'build'), default_name=default_build_name),
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
        schema_version = _schema_version(data)
        code = CodeConfig.from_dict(_required_mapping(data, 'code'), resolved_revision=True)
        inputs = [
            InputConfig.from_dict(item, index=index, resolved_revision=True)
            for index, item in enumerate(_required_list(data, 'inputs'), start=1)
        ]
        if not inputs:
            raise ConfigFormatError('inputs must not be empty')
        rules = RulesReference.from_dict(_optional_mapping(data, 'rules'), resolved_revision=True)
        _validate_rule_source_presence(code, inputs, rules)
        return cls(
            schema_version=schema_version,
            lock=LockMetadata.from_dict(_required_mapping(data, 'lock'), source_field='build_toml_sha256'),
            build=BuildInfo.from_dict(_optional_mapping(data, 'build')),
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


@dataclass(frozen=True)
class RunConfig:
    schema_version: str
    executable: str
    args: list[str] = field(default_factory=list)
    cwd: str = '.'
    timeout_seconds: int | None = None
    encoding: str = 'utf-8'
    stdin_mode: str = 'none'
    stdin_text: str = ''
    env: dict[str, str] = field(default_factory=dict)
    secret_env: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        schema_version = _schema_version(data)
        run = _required_mapping(data, 'run')
        if 'output_rule_set' in data or 'output_rule_set' in run:
            raise ConfigFormatError('run.toml must not define output_rule_set')
        if 'env' in run:
            raise ConfigFormatError('env must be a top-level table')
        if 'secret_env' in run:
            raise ConfigFormatError('secret_env must be a top-level list of names')
        timeout = run.get('timeout_seconds')
        if timeout is not None and not isinstance(timeout, int):
            raise ConfigFormatError('timeout_seconds must be an integer or null')
        stdin_mode = _optional_str(run, 'stdin_mode') or 'none'
        if stdin_mode not in {'none', 'script', 'manual'}:
            raise ConfigFormatError('stdin_mode must be none, script, or manual')
        return cls(
            schema_version=schema_version,
            executable=_required_str(run, 'executable'),
            args=[_string_value(item, 'args item') for item in _optional_list(run, 'args')],
            cwd=_optional_str(run, 'cwd') or '.',
            timeout_seconds=timeout,
            encoding=_optional_str(run, 'encoding') or 'utf-8',
            stdin_mode=stdin_mode,
            stdin_text=_optional_str(run, 'stdin_text') or '',
            env=_string_mapping(_optional_mapping(data, 'env') or {}),
            secret_env=[_string_value(item, 'secret_env item') for item in _optional_list(data, 'secret_env')],
        )

    def to_dict(self) -> dict[str, Any]:
        run: dict[str, Any] = {
            'executable': self.executable,
            'args': list(self.args),
            'cwd': self.cwd,
            'timeout_seconds': self.timeout_seconds,
            'encoding': self.encoding,
            'stdin_mode': self.stdin_mode,
            'stdin_text': self.stdin_text,
        }
        result: dict[str, Any] = {'schema_version': self.schema_version, 'run': run}
        if self.env:
            result['env'] = dict(self.env)
        if self.secret_env:
            result['secret_env'] = list(self.secret_env)
        return result


@dataclass(frozen=True)
class PublishTarget:
    name: str
    target: TargetRef
    rule_sets: list[str]
    message: str

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
        *,
        default_message: str,
        resolved_revision: bool = False,
    ) -> Self:
        target_data = {
            key: value
            for key, value in data.items()
            if key not in {'name', 'rule_sets', 'message'}
        }
        return cls(
            name=_required_str(data, 'name'),
            target=TargetRef.from_dict(target_data, resolved_revision=resolved_revision),
            rule_sets=[_string_value(item, 'rule_sets item') for item in _required_list(data, 'rule_sets')],
            message=_optional_str(data, 'message') or default_message,
        )

    def to_dict(self) -> dict[str, Any]:
        result = {'name': self.name, **self.target.to_dict(), 'rule_sets': list(self.rule_sets)}
        if self.message:
            result['message'] = self.message
        return result


@dataclass(frozen=True)
class PublishConfig:
    schema_version: str
    message: str
    service_target: TargetRef
    targets: list[PublishTarget]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        schema_version = _schema_version(data)
        publish = _optional_mapping(data, 'publish') or {}
        if 'dry_run' in data or 'dry_run' in publish:
            raise ConfigFormatError('publish.toml must not store dry_run')
        if 'service_layout' in data or 'service_layout' in publish:
            raise ConfigFormatError('publish.toml must not define service_layout')
        message = _optional_str(publish, 'message') or ''
        return cls(
            schema_version=schema_version,
            message=message,
            service_target=TargetRef.from_dict(_required_mapping(data, 'service_target')),
            targets=[
                PublishTarget.from_dict(item, default_message=message)
                for item in _optional_list(data, 'targets')
            ],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            'schema_version': self.schema_version,
            'publish': {'message': self.message},
            'service_target': self.service_target.to_dict(),
            'targets': [target.to_dict() for target in self.targets],
        }


@dataclass(frozen=True)
class PublishLock:
    schema_version: str
    lock: LockMetadata
    message: str
    service_target: TargetRef
    targets: list[PublishTarget]
    published: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        schema_version = _schema_version(data)
        publish = _optional_mapping(data, 'publish') or {}
        message = _optional_str(publish, 'message') or ''
        return cls(
            schema_version=schema_version,
            lock=LockMetadata.from_dict(_required_mapping(data, 'lock'), source_field='publish_toml_sha256'),
            message=message,
            service_target=TargetRef.from_dict(
                _required_mapping(data, 'service_target'),
                resolved_revision=True,
            ),
            targets=[
                PublishTarget.from_dict(
                    item,
                    default_message=message,
                    resolved_revision=True,
                )
                for item in _optional_list(data, 'targets')
            ],
            published=dict(_optional_mapping(data, 'published') or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            'schema_version': self.schema_version,
            'lock': self.lock.to_dict(),
            'publish': {'message': self.message},
            'service_target': self.service_target.to_dict(),
            'targets': [target.to_dict() for target in self.targets],
        }
        if self.published:
            result['published'] = deepcopy(self.published)
        return result


@dataclass(frozen=True)
class Rule:
    source: str
    destination: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        return cls(source=_required_str(data, 'source'), destination=_required_str(data, 'destination'))

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
            type=RuleSetType(_required_str(data, 'type')),
            status=_optional_str(data, 'status') or '',
            description=_optional_str(data, 'description') or '',
            ensure_all_files=ensure_all_files,
            rules=[Rule.from_dict(item) for item in _required_list(data, 'rules')],
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
        schema_version = _schema_version(data)
        rule_sets = {
            _string_value(name, 'rule set name'): RuleSet.from_dict(_mapping_value(value, 'rule set'))
            for name, value in _required_mapping(data, 'rule_sets').items()
        }
        if not rule_sets:
            raise ConfigFormatError('rule_sets must not be empty')
        return cls(
            schema_version=schema_version,
            rules_file=dict(_optional_mapping(data, 'rules_file') or {}),
            rule_sets=rule_sets,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            'schema_version': self.schema_version,
            'rules_file': dict(self.rules_file),
            'rule_sets': {name: rule_set.to_dict() for name, rule_set in self.rule_sets.items()},
        }


@dataclass(frozen=True)
class Manifest:
    schema_version: str
    data: dict[str, Any]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        schema_version = _schema_version(data)
        _required_mapping(data, 'job')
        _required_mapping(data, 'build')
        _validate_manifest_secret_markers(data)
        _validate_manifest_refs(data)
        manifest_data = deepcopy(dict(data))
        manifest_data['schema_version'] = schema_version
        return cls(schema_version=schema_version, data=manifest_data)

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(self.data)


def _schema_version(data: Mapping[str, Any]) -> str:
    version = data.get('schema_version', LATEST_SCHEMA_VERSION)
    if not isinstance(version, str):
        raise ConfigFormatError('schema_version must be a string')
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        raise UnsupportedSchemaVersionError(f'unsupported schema_version: {version}')
    return version


def _validate_rule_source_presence(
    code: CodeConfig,
    inputs: Sequence[InputConfig],
    rules: RulesReference | None,
) -> None:
    has_rule_use = code.rule_set is not None or any(item.rule_set is not None for item in inputs)
    if has_rule_use and (rules is None or rules.source is None):
        raise ConfigFormatError('rules.source is required when rule_set is used')


def _validate_manifest_refs(value: Any) -> None:
    if isinstance(value, Mapping):
        if 'type' in value and 'path' in value:
            SourceRef.from_dict(value, reject_userinfo=True)
        if 'sha256' in value and 'sources' in value:
            ArtifactRef.from_dict(value, reject_userinfo=True)
        if 'source' in value and isinstance(value['source'], Mapping):
            SourceRef.from_dict(value['source'], reject_userinfo=True)
        if 'target' in value and isinstance(value['target'], Mapping):
            TargetRef.from_dict(value['target'], reject_userinfo=True)
        if 'rules' in value and isinstance(value['rules'], Mapping) and 'set' in value['rules']:
            RuleUse.from_dict(value['rules'])
        if 'map' in value and isinstance(value['map'], list):
            for entry in value['map']:
                FileMapEntry.from_dict(_mapping_value(entry, 'map entry'))
        for item in value.values():
            _validate_manifest_refs(item)
    elif isinstance(value, list):
        for item in value:
            _validate_manifest_refs(item)


def _validate_manifest_secret_markers(data: Mapping[str, Any]) -> None:
    run = data.get('run')
    if run is None:
        return
    run_mapping = _mapping_value(run, 'run')
    env = run_mapping.get('env')
    if env is None:
        return
    env_mapping = _mapping_value(env, 'run.env')
    if 'secrets' not in env_mapping:
        return
    for secret in _list_value(env_mapping['secrets'], 'run.env.secrets'):
        _string_value(secret, 'run.env.secrets item')


def _validate_svn_revision(
    revision: Any,
    *,
    resolved_revision: bool,
    field: str,
) -> None:
    if revision is None:
        if resolved_revision:
            raise ConfigFormatError(f'resolved svn {field} revision is required')
        return
    if resolved_revision:
        if isinstance(revision, int) and revision >= 0:
            return
        if isinstance(revision, str) and revision.isdecimal():
            return
        raise ConfigFormatError(f'resolved svn {field} revision must be concrete')
    if isinstance(revision, int) and revision >= 0:
        return
    if isinstance(revision, str) and (revision == 'HEAD' or revision.isdecimal()):
        return
    raise ConfigFormatError(f'svn {field} revision must be HEAD or a concrete revision')


def _validate_svn_location(location: str, *, field: str) -> None:
    if '@' in urlsplit(location).netloc:
        raise ConfigFormatError(f'svn {field} location must not contain userinfo')


def _ref_type(value: SourceType | str) -> SourceType | str:
    if isinstance(value, SourceType):
        return value
    value = _string_value(value, 'type')
    if value == '':
        raise ConfigFormatError('type must not be empty')
    try:
        return SourceType(value)
    except ValueError:
        return value


def _is_ref_type(value: SourceType | str, expected: SourceType) -> bool:
    return _ref_type_value(value) == expected.value


def _ref_type_value(value: SourceType | str) -> str:
    if isinstance(value, SourceType):
        return value.value
    return _string_value(value, 'type')


def _optional_plugin_metadata(data: Mapping[str, Any]) -> PluginRefMetadata | None:
    if 'plugin' not in data:
        return None
    try:
        return PluginRefMetadata.from_dict(_mapping_value(data['plugin'], 'plugin'))
    except ValueError as error:
        raise ConfigFormatError(str(error)) from error


def _extra_ref_fields(data: Mapping[str, Any], known_fields: set[str]) -> dict[str, Any]:
    return {
        _string_value(key, 'ref field'): _serializable_value(value, f'{key} value')
        for key, value in data.items()
        if key not in known_fields
    }


def _serializable_mapping(data: Mapping[str, Any], field: str) -> dict[str, Any]:
    return {
        _string_value(key, f'{field} key'): _serializable_value(value, f'{field}.{key}')
        for key, value in data.items()
    }


def _serializable_value(value: Any, field: str) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, list):
        return [_serializable_value(item, f'{field} item') for item in value]
    if isinstance(value, Mapping):
        return {
            _string_value(key, f'{field} key'): _serializable_value(item, f'{field}.{key}')
            for key, item in value.items()
        }
    raise ConfigFormatError(f'{field} must be serializable')


def _required_mapping(data: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    if key not in data:
        raise ConfigFormatError(f'missing required field: {key}')
    return _mapping_value(data[key], key)


def _optional_mapping(data: Mapping[str, Any], key: str) -> Mapping[str, Any] | None:
    if key not in data:
        return None
    return _mapping_value(data[key], key)


def _mapping_value(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ConfigFormatError(f'{field} must be an object')
    return value


def _required_list(data: Mapping[str, Any], key: str) -> list[Any]:
    if key not in data:
        raise ConfigFormatError(f'missing required field: {key}')
    return _list_value(data[key], key)


def _optional_list(data: Mapping[str, Any], key: str) -> list[Any]:
    if key not in data:
        return []
    return _list_value(data[key], key)


def _list_value(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ConfigFormatError(f'{field} must be a list')
    return value


def _required_str(data: Mapping[str, Any], key: str) -> str:
    if key not in data:
        raise ConfigFormatError(f'missing required field: {key}')
    return _string_value(data[key], key)


def _optional_str(data: Mapping[str, Any], key: str) -> str | None:
    if key not in data:
        return None
    return _string_value(data[key], key)


def _string_value(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ConfigFormatError(f'{field} must be a string')
    return value


def _string_mapping(data: Mapping[str, Any]) -> dict[str, str]:
    return {
        _string_value(key, 'mapping key'): _string_value(value, f'{key} value')
        for key, value in data.items()
    }


def _required_sha256(data: Mapping[str, Any], key: str) -> str:
    value = _required_str(data, key)
    if _SHA256_RE.fullmatch(value) is None:
        raise ConfigFormatError(f'{key} must be a sha256 hex digest')
    return value.lower()


def _put_optional(target: dict[str, Any], key: str, value: Any | None) -> None:
    if value is not None:
        target[key] = value


def _default_name_from_ref(ref: SourceRef) -> str:
    path = ref.path or ref.location or ''
    normalized = path.replace('\\', '/').strip('/')
    if not normalized:
        return ''
    return normalized.rsplit('/', maxsplit=1)[-1]
