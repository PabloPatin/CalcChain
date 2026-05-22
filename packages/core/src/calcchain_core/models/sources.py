from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Self

from calcchain_capabilities import PluginRefMetadata
from calcchain_core.common.errors import ConfigFormatError
from calcchain_core.models.common import (
    SourceType,
    extra_ref_fields,
    is_ref_type,
    optional_plugin_metadata,
    optional_str,
    ref_type,
    ref_type_value,
    required_list,
    required_sha256,
    required_str,
    serializable_mapping,
    serializable_value,
    string_value,
    validate_svn_location,
    validate_svn_revision,
)


@dataclass(frozen=True)
class LocalSourceRef:
    path: str
    plugin: PluginRefMetadata | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        string_value(self.path, 'path')
        if not self.path:
            raise ConfigFormatError('missing required field: path')

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        parsed_type = ref_type(required_str(data, 'type'))
        if not is_ref_type(parsed_type, SourceType.LOCAL):
            raise ConfigFormatError('local source must have type local')
        if optional_str(data, 'location') is not None:
            raise ConfigFormatError('local source must not define location')
        if data.get('revision') is not None:
            raise ConfigFormatError('local source must not define revision')
        path = optional_str(data, 'path') or ''
        if not path:
            raise ConfigFormatError('missing required field: path')
        return cls(
            path=path,
            plugin=optional_plugin_metadata(data),
            extra=extra_ref_fields(data, {'type', 'path', 'location', 'revision', 'plugin'}),
        )

    def to_dict(self) -> dict[str, Any]:
        if not self.path:
            raise ConfigFormatError('missing required field: path')
        result: dict[str, Any] = {'type': SourceType.LOCAL.value, 'path': self.path}
        if self.plugin is not None:
            result['plugin'] = self.plugin.to_dict()
        result.update(serializable_mapping(self.extra, 'source extra'))
        return result


@dataclass(frozen=True)
class SvnSourceRef:
    location: str
    path: str
    revision: str | int = 'HEAD'
    plugin: PluginRefMetadata | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        string_value(self.path, 'path')
        if not self.path:
            raise ConfigFormatError('missing required field: path')
        validate_svn_location(self.location, field='source')
        validate_svn_revision(self.revision, resolved_revision=False, field='source')

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, resolved_revision: bool = False, reject_userinfo: bool = False) -> Self:
        parsed_type = ref_type(required_str(data, 'type'))
        if not is_ref_type(parsed_type, SourceType.SVN):
            raise ConfigFormatError('svn source must have type svn')
        location = optional_str(data, 'location')
        if location is None:
            raise ConfigFormatError('svn source requires location')
        path = optional_str(data, 'path') or ''
        if not path:
            raise ConfigFormatError('missing required field: path')
        if reject_userinfo:
            validate_svn_location(location, field='source')
        revision = data.get('revision')
        validate_svn_revision(revision, resolved_revision=resolved_revision, field='source')
        if revision is None:
            revision = 'HEAD'
        return cls(
            location=location,
            path=path,
            revision=revision,
            plugin=optional_plugin_metadata(data),
            extra=extra_ref_fields(data, {'type', 'path', 'location', 'revision', 'plugin'}),
        )

    def to_dict(self) -> dict[str, Any]:
        validate_svn_location(self.location, field='source')
        validate_svn_revision(self.revision, resolved_revision=False, field='source')
        result: dict[str, Any] = {
            'type': SourceType.SVN.value,
            'location': self.location,
            'path': self.path,
            'revision': self.revision,
        }
        if self.plugin is not None:
            result['plugin'] = self.plugin.to_dict()
        result.update(serializable_mapping(self.extra, 'source extra'))
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
        object.__setattr__(self, 'type', ref_type(self.type))
        string_value(self.path, 'path')

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, resolved_revision: bool = False, reject_userinfo: bool = False) -> Self:
        parsed_type = ref_type(required_str(data, 'type'))
        path = optional_str(data, 'path') or ''
        location = optional_str(data, 'location')
        revision = data.get('revision')
        plugin = optional_plugin_metadata(data)
        extra = extra_ref_fields(data, {'type', 'path', 'location', 'revision', 'plugin'})

        if is_ref_type(parsed_type, SourceType.LOCAL):
            if location is not None:
                raise ConfigFormatError('local target must not define location')
            if revision is not None:
                raise ConfigFormatError('local target must not define revision')
            if not path:
                raise ConfigFormatError('missing required field: path')
            return cls(type=parsed_type, path=path, plugin=plugin, extra=extra)

        if not is_ref_type(parsed_type, SourceType.SVN):
            return cls(
                type=parsed_type,
                path=path,
                location=location,
                revision=serializable_value(revision, 'revision') if revision is not None else None,
                plugin=plugin,
                extra=extra,
            )

        if location is None:
            raise ConfigFormatError('svn target requires location')
        if not path:
            raise ConfigFormatError('missing required field: path')
        if reject_userinfo:
            validate_svn_location(location, field='target')
        validate_svn_revision(revision, resolved_revision=resolved_revision, field='target')
        if revision is None:
            revision = 'HEAD'
        return cls(type=parsed_type, location=location, path=path, revision=revision, plugin=plugin, extra=extra)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {'type': ref_type_value(self.type)}
        if is_ref_type(self.type, SourceType.LOCAL) and not self.path:
            raise ConfigFormatError('missing required field: path')
        if self.location is not None:
            if is_ref_type(self.type, SourceType.LOCAL):
                raise ConfigFormatError('local target must not define location')
            if is_ref_type(self.type, SourceType.SVN):
                validate_svn_location(self.location, field='target')
            result['location'] = self.location
        elif is_ref_type(self.type, SourceType.SVN):
            raise ConfigFormatError('svn target requires location')
        if is_ref_type(self.type, SourceType.SVN) and not self.path:
            raise ConfigFormatError('missing required field: path')
        if self.path or is_ref_type(self.type, SourceType.LOCAL) or is_ref_type(self.type, SourceType.SVN):
            result['path'] = self.path
        if self.revision is not None:
            if is_ref_type(self.type, SourceType.LOCAL):
                raise ConfigFormatError('local target must not define revision')
            if is_ref_type(self.type, SourceType.SVN):
                validate_svn_revision(self.revision, resolved_revision=False, field='target')
                result['revision'] = self.revision
            else:
                result['revision'] = serializable_value(self.revision, 'revision')
        if self.plugin is not None:
            result['plugin'] = self.plugin.to_dict()
        result.update(serializable_mapping(self.extra, 'target extra'))
        return result


@dataclass(frozen=True)
class ArtifactRef:
    sha256: str
    sources: list[LocalSourceRef | SvnSourceRef]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, reject_userinfo: bool = False) -> Self:
        sha256 = required_sha256(data, 'sha256')
        sources = [_source_ref_from_dict(item, reject_userinfo=reject_userinfo) for item in required_list(data, 'sources')]
        if not sources:
            raise ConfigFormatError('artifact sources must not be empty')
        return cls(sha256=sha256, sources=sources)

    def to_dict(self) -> dict[str, Any]:
        return {'sha256': self.sha256, 'sources': [source.to_dict() for source in self.sources]}


def _source_ref_from_dict(data: Mapping[str, Any], *, reject_userinfo: bool = False) -> LocalSourceRef | SvnSourceRef:
    parsed_type = ref_type(required_str(data, 'type'))
    if is_ref_type(parsed_type, SourceType.LOCAL):
        return LocalSourceRef.from_dict(data)
    if is_ref_type(parsed_type, SourceType.SVN):
        return SvnSourceRef.from_dict(data, reject_userinfo=reject_userinfo)
    raise ConfigFormatError(f'unsupported source type: {ref_type_value(parsed_type)}')
