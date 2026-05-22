from collections.abc import Mapping
from dataclasses import dataclass
import re
from typing import Any
from urllib.parse import urlsplit

from calcchain_capabilities import PluginRefMetadata
from calcchain_core.common.errors import ConfigFormatError, UnsupportedSchemaVersionError

LATEST_SCHEMA_VERSION = '1.0'
SUPPORTED_SCHEMA_VERSIONS = {'1.0'}
_SHA256_RE = re.compile(r'^[0-9a-fA-F]{64}$')

LOCAL_SOURCE_TYPE = 'local'


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
    sha256: str
    source_path: str | None = None
    work_path: str | None = None
    target_path: str | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]):
        return cls(
            sha256=required_sha256(data, 'sha256'),
            source_path=optional_str(data, 'source_path'),
            work_path=optional_str(data, 'work_path'),
            target_path=optional_str(data, 'target_path'),
        )

    def to_dict(self) -> dict[str, Any]:
        result = {'sha256': self.sha256}
        put_optional(result, 'source_path', self.source_path)
        put_optional(result, 'work_path', self.work_path)
        put_optional(result, 'target_path', self.target_path)
        return result


@dataclass(frozen=True)
class LockMetadata:
    created_at: str
    created_from: str
    source_sha256: str
    source_sha256_field: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, source_field: str):
        return cls(
            created_at=required_str(data, 'created_at'),
            created_from=required_str(data, 'created_from'),
            source_sha256=required_sha256(data, source_field),
            source_sha256_field=source_field,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            'created_at': self.created_at,
            'created_from': self.created_from,
            self.source_sha256_field: self.source_sha256,
        }


def schema_version(data: Mapping[str, Any]) -> str:
    version = data.get('schema_version', LATEST_SCHEMA_VERSION)
    if not isinstance(version, str):
        raise ConfigFormatError('schema_version must be a string')
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        raise UnsupportedSchemaVersionError(f'unsupported schema_version: {version}')
    return version


def validate_svn_revision(revision: Any, *, resolved_revision: bool, field: str) -> None:
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


def validate_svn_location(location: str, *, field: str) -> None:
    if '@' in urlsplit(location).netloc:
        raise ConfigFormatError(f'svn {field} location must not contain userinfo')


def ref_type(value: SourceType | str) -> SourceType | str:
    if isinstance(value, SourceType):
        return value
    value = string_value(value, 'type')
    if value == '':
        raise ConfigFormatError('type must not be empty')
    try:
        return SourceType(value)
    except ValueError:
        return value


def is_ref_type(value: SourceType | str, expected: SourceType) -> bool:
    return ref_type_value(value) == expected.value


def ref_type_value(value: SourceType | str) -> str:
    if isinstance(value, SourceType):
        return value.value
    return string_value(value, 'type')


def optional_plugin_metadata(data: Mapping[str, Any]) -> PluginRefMetadata | None:
    if 'plugin' not in data:
        return None
    try:
        return PluginRefMetadata.from_dict(mapping_value(data['plugin'], 'plugin'))
    except ValueError as error:
        raise ConfigFormatError(str(error)) from error


def extra_ref_fields(data: Mapping[str, Any], known_fields: set[str]) -> dict[str, Any]:
    return {
        string_value(key, 'ref field'): serializable_value(value, f'{key} value')
        for key, value in data.items()
        if key not in known_fields
    }


def serializable_mapping(data: Mapping[str, Any], field: str) -> dict[str, Any]:
    return {string_value(key, f'{field} key'): serializable_value(value, f'{field}.{key}') for key, value in data.items()}


def serializable_value(value: Any, field: str) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, list):
        return [serializable_value(item, f'{field} item') for item in value]
    if isinstance(value, Mapping):
        return {string_value(key, f'{field} key'): serializable_value(item, f'{field}.{key}') for key, item in value.items()}
    raise ConfigFormatError(f'{field} must be serializable')


def required_mapping(data: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    if key not in data:
        raise ConfigFormatError(f'missing required field: {key}')
    return mapping_value(data[key], key)


def optional_mapping(data: Mapping[str, Any], key: str) -> Mapping[str, Any] | None:
    if key not in data:
        return None
    return mapping_value(data[key], key)


def mapping_value(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ConfigFormatError(f'{field} must be an object')
    return value


def required_list(data: Mapping[str, Any], key: str) -> list[Any]:
    if key not in data:
        raise ConfigFormatError(f'missing required field: {key}')
    return list_value(data[key], key)


def optional_list(data: Mapping[str, Any], key: str) -> list[Any]:
    if key not in data:
        return []
    return list_value(data[key], key)


def list_value(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ConfigFormatError(f'{field} must be a list')
    return value


def required_str(data: Mapping[str, Any], key: str) -> str:
    if key not in data:
        raise ConfigFormatError(f'missing required field: {key}')
    return string_value(data[key], key)


def optional_str(data: Mapping[str, Any], key: str) -> str | None:
    if key not in data:
        return None
    return string_value(data[key], key)


def string_value(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ConfigFormatError(f'{field} must be a string')
    return value


def string_mapping(data: Mapping[str, Any]) -> dict[str, str]:
    return {string_value(key, 'mapping key'): string_value(value, f'{key} value') for key, value in data.items()}


def required_sha256(data: Mapping[str, Any], key: str) -> str:
    value = required_str(data, key)
    if _SHA256_RE.fullmatch(value) is None:
        raise ConfigFormatError(f'{key} must be a sha256 hex digest')
    return value.lower()


def put_optional(target: dict[str, Any], key: str, value: Any | None) -> None:
    if value is not None:
        target[key] = value
