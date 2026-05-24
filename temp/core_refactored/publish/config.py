from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..common.errors import ConfigFormatError
from ..config import PUBLISH_CONFIG_SCHEMA_VERSION
from ..io.target import TargetRef
from ..utils.validation import (
    mapping_value,
    optional_list,
    optional_mapping,
    optional_str,
    required_list,
    required_mapping,
    required_str,
    string_value,
)


@dataclass(frozen=True)
class PublishTarget:
    name: str
    target: TargetRef
    rule_sets: list[str]
    message: str = ''

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, default_message: str = ''):
        target_data = {
            key: value
            for key, value in data.items()
            if key not in {'name', 'rule_sets', 'message'}
        }
        return cls(
            name=required_str(data, 'name'),
            target=TargetRef.from_dict(dict(target_data)),
            rule_sets=[string_value(item, 'rule_sets item') for item in required_list(data, 'rule_sets')],
            message=optional_str(data, 'message') or default_message,
        )

    def to_dict(self) -> dict[str, Any]:
        result = {
            'name': self.name,
            **self.target.to_dict(),
            'rule_sets': list(self.rule_sets),
        }
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
    def from_dict(cls, data: Mapping[str, Any]):
        publish = optional_mapping(data, 'publish') or {}
        _reject_non_config_fields(data, publish)
        message = optional_str(publish, 'message') or ''
        return cls(
            schema_version=optional_str(data, 'schema_version') or PUBLISH_CONFIG_SCHEMA_VERSION,
            message=message,
            service_target=TargetRef.from_dict(dict(required_mapping(data, 'service_target'))),
            targets=[
                PublishTarget.from_dict(mapping_value(item, f'targets[{index}]'), default_message=message)
                for index, item in enumerate(optional_list(data, 'targets'), start=1)
            ],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            'schema_version': self.schema_version,
            'publish': {'message': self.message},
            'service_target': self.service_target.to_dict(),
            'targets': [target.to_dict() for target in self.targets],
        }


def _reject_non_config_fields(data: Mapping[str, Any], publish: Mapping[str, Any]) -> None:
    if 'dry_run' in data or 'dry_run' in publish:
        raise ConfigFormatError('publish.toml must not store dry_run')
    if 'service_layout' in data or 'service_layout' in publish:
        raise ConfigFormatError('publish.toml must not define service_layout')
