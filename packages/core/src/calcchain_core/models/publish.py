from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Self

from calcchain_core.common.errors import ConfigFormatError
from calcchain_core.models.common import LockMetadata, optional_list, optional_mapping, optional_str, required_list, required_mapping, required_str, schema_version, string_value
from calcchain_core.models.sources import TargetRef


@dataclass(frozen=True)
class PublishTarget:
    name: str
    target: TargetRef
    rule_sets: list[str]
    message: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, default_message: str, resolved_revision: bool = False) -> Self:
        target_data = {key: value for key, value in data.items() if key not in {'name', 'rule_sets', 'message'}}
        return cls(
            name=required_str(data, 'name'),
            target=TargetRef.from_dict(target_data, resolved_revision=resolved_revision),
            rule_sets=[string_value(item, 'rule_sets item') for item in required_list(data, 'rule_sets')],
            message=optional_str(data, 'message') or default_message,
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
        version = schema_version(data)
        publish = optional_mapping(data, 'publish') or {}
        if 'dry_run' in data or 'dry_run' in publish:
            raise ConfigFormatError('publish.toml must not store dry_run')
        if 'service_layout' in data or 'service_layout' in publish:
            raise ConfigFormatError('publish.toml must not define service_layout')
        message = optional_str(publish, 'message') or ''
        return cls(
            schema_version=version,
            message=message,
            service_target=TargetRef.from_dict(required_mapping(data, 'service_target')),
            targets=[PublishTarget.from_dict(item, default_message=message) for item in optional_list(data, 'targets')],
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
        version = schema_version(data)
        publish = optional_mapping(data, 'publish') or {}
        message = optional_str(publish, 'message') or ''
        return cls(
            schema_version=version,
            lock=LockMetadata.from_dict(required_mapping(data, 'lock'), source_field='publish_toml_sha256'),
            message=message,
            service_target=TargetRef.from_dict(required_mapping(data, 'service_target'), resolved_revision=True),
            targets=[PublishTarget.from_dict(item, default_message=message, resolved_revision=True) for item in optional_list(data, 'targets')],
            published=dict(optional_mapping(data, 'published') or {}),
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
