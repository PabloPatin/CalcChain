from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..utils.validation import mapping_value, optional_list, optional_mapping, optional_str, required_mapping
from .config import BuildInfo, CodeConfig, InputConfig, RulesReference
from ..config import BUILD_CONFIG_SCHEMA_VERSION

@dataclass(frozen=True)
class LockMetadata:
    created_at: str
    created_from: str
    source_sha256: str
    source_sha256_field: str = 'build_toml_sha256'

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, source_field: str = 'build_toml_sha256'):
        return cls(
            created_at=optional_str(data, 'created_at') or '',
            created_from=optional_str(data, 'created_from') or '',
            source_sha256=optional_str(data, source_field) or '',
            source_sha256_field=source_field,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            'created_at': self.created_at,
            'created_from': self.created_from,
            self.source_sha256_field: self.source_sha256,
        }


@dataclass(frozen=True)
class BuildLock:
    schema_version: str
    lock: LockMetadata
    build: BuildInfo
    code: CodeConfig
    inputs: list[InputConfig]
    rules: RulesReference | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]):
        inputs_data = optional_list(data, 'inputs')
        return cls(
            schema_version=optional_str(data, 'schema_version') or BUILD_CONFIG_SCHEMA_VERSION,
            lock=LockMetadata.from_dict(required_mapping(data, 'lock')),
            build=BuildInfo.from_dict(optional_mapping(data, 'build')),
            code=CodeConfig.from_dict(required_mapping(data, 'code')),
            inputs=[
                InputConfig.from_dict(mapping_value(item, f'inputs[{index}]'), index=index)
                for index, item in enumerate(inputs_data, start=1)
            ],
            rules=RulesReference.from_dict(optional_mapping(data, 'rules')),
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
