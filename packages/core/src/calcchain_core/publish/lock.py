from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from ..build.lock import LockMetadata
from ..config import PUBLISH_CONFIG_SCHEMA_VERSION
from ..io.target import TargetRef
from ..utils.validation import mapping_value, optional_list, optional_mapping, optional_str, required_mapping
from .config import PublishTarget


@dataclass(frozen=True)
class PublishLock:
    schema_version: str
    lock: LockMetadata
    message: str
    service_target: TargetRef
    targets: list[PublishTarget]
    published: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]):
        publish = optional_mapping(data, 'publish') or {}
        message = optional_str(publish, 'message') or ''
        return cls(
            schema_version=optional_str(data, 'schema_version') or PUBLISH_CONFIG_SCHEMA_VERSION,
            lock=LockMetadata.from_dict(required_mapping(data, 'lock'), source_field='publish_toml_sha256'),
            message=message,
            service_target=TargetRef.from_dict(dict(required_mapping(data, 'service_target'))),
            targets=[
                PublishTarget.from_dict(mapping_value(item, f'targets[{index}]'), default_message=message)
                for index, item in enumerate(optional_list(data, 'targets'), start=1)
            ],
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
