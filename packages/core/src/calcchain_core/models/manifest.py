from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Self

from calcchain_core.models.common import FileMapEntry, RuleUse, list_value, mapping_value, required_mapping, schema_version, string_value
from calcchain_core.models.sources import ArtifactRef, SourceRef, TargetRef


@dataclass(frozen=True)
class Manifest:
    schema_version: str
    data: dict[str, Any]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        version = schema_version(data)
        required_mapping(data, 'job')
        required_mapping(data, 'build')
        _validate_manifest_secret_markers(data)
        _validate_manifest_refs(data)
        manifest_data = deepcopy(dict(data))
        manifest_data['schema_version'] = version
        return cls(schema_version=version, data=manifest_data)

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(self.data)


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
                FileMapEntry.from_dict(mapping_value(entry, 'map entry'))
        for item in value.values():
            _validate_manifest_refs(item)
    elif isinstance(value, list):
        for item in value:
            _validate_manifest_refs(item)


def _validate_manifest_secret_markers(data: Mapping[str, Any]) -> None:
    run = data.get('run')
    if run is None:
        return
    run_mapping = mapping_value(run, 'run')
    env = run_mapping.get('env')
    if env is None:
        return
    env_mapping = mapping_value(env, 'run.env')
    if 'secrets' not in env_mapping:
        return
    for secret in list_value(env_mapping['secrets'], 'run.env.secrets'):
        string_value(secret, 'run.env.secrets item')
