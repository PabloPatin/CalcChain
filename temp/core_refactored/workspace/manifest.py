from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..common.hash import sha256_file
from ..common.status import JobStatus
from ..config import MANIFEST_SCHEMA_VERSION
from ..utils.json import write_json
from ..utils.validation import optional_str, required_mapping


@dataclass(frozen=True)
class Manifest:
    schema_version: str
    data: dict[str, Any]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]):
        required_mapping(data, 'job')
        required_mapping(data, 'build')
        manifest_data = deepcopy(dict(data))
        manifest_data['schema_version'] = optional_str(data, 'schema_version') or MANIFEST_SCHEMA_VERSION
        return cls(schema_version=manifest_data['schema_version'], data=manifest_data)

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(self.data)


class ManifestWriter:
    @staticmethod
    def create_after_build(job, build_result, snapshots) -> Manifest:
        data: dict[str, Any] = {
            'schema_version': MANIFEST_SCHEMA_VERSION,
            'job': _job_dict(job, JobStatus.BUILT.value),
            'build': _build_dict(job, build_result),
        }
        rules = _rules_dict(build_result)
        if rules is not None:
            data['rules'] = rules
        snapshot_refs = _snapshot_refs(snapshots)
        if snapshot_refs:
            data['snapshots'] = snapshot_refs
        return Manifest.from_dict(data)

    @staticmethod
    def create_after_run(job, build_result, run_result, file_groups, snapshots) -> Manifest:
        status = _value(run_result, 'status')
        status_value = status.value if hasattr(status, 'value') else str(status)
        data = ManifestWriter.create_after_build(job, build_result, snapshots).to_dict()
        data['job']['status'] = status_value
        data['run'] = {
            'status': status_value,
            'file_groups': _file_groups_dict(file_groups),
        }
        return Manifest.from_dict(data)


def write_manifest(manifest: Manifest, path: Path) -> None:
    write_json(manifest.to_dict(), path)


def _job_dict(job, status: str) -> dict[str, Any]:
    source = _object_to_dict(job)
    result: dict[str, Any] = {}
    for key in ('id', 'created_at', 'job_dir', 'user', 'hostname'):
        value = source.get(key)
        if value is not None:
            result[key] = str(value)
    result['status'] = status
    return result


def _build_dict(job, build_result) -> dict[str, Any]:
    result: dict[str, Any] = {}
    lock = _artifact_from_candidate(_path_candidate(job, 'build_lock_path'))
    if lock is not None:
        result['lock'] = lock
    result['code'] = _file_set_dict(_value(build_result, 'code_set'))
    result['inputs'] = [_file_set_dict(item) for item in _value(build_result, 'input_sets') or []]
    frozen_inputs = _value(build_result, 'frozen_inputs')
    if frozen_inputs is not None:
        result['inputs'].append(_file_set_dict(frozen_inputs))
    return result


def _rules_dict(build_result) -> dict[str, Any] | None:
    artifact = _value(build_result, 'rules_artifact')
    if artifact is None:
        return None
    if hasattr(artifact, 'to_dict'):
        return artifact.to_dict()
    return dict(artifact)


def _snapshot_refs(snapshots) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in _object_to_dict(snapshots).items():
        artifact = _artifact_from_candidate(value)
        if artifact is not None:
            result[str(key)] = artifact
    return result


def _file_groups_dict(file_groups) -> dict[str, list[str]]:
    if file_groups is None:
        return {'code': [], 'inputs': [], 'outputs': [], 'logs': [], 'temp': [], 'ignored': [], 'unknown': []}
    data = file_groups.to_dict() if hasattr(file_groups, 'to_dict') else _object_to_dict(file_groups)
    return {
        'code': list(data.get('code') or []),
        'inputs': list(data.get('inputs') or []),
        'outputs': list(data.get('outputs') or []),
        'logs': list(data.get('logs') or []),
        'temp': list(data.get('temp') or []),
        'ignored': list(data.get('ignored') or []),
        'unknown': list(data.get('unknown') or []),
    }


def _file_set_dict(file_set) -> dict[str, Any]:
    if hasattr(file_set, 'to_dict'):
        return file_set.to_dict()
    return deepcopy(dict(file_set))


def _artifact_from_candidate(candidate) -> dict[str, Any] | None:
    if candidate is None:
        return None
    if isinstance(candidate, dict):
        return deepcopy(candidate)
    path = Path(candidate)
    if not path.is_file():
        return None
    return {
        'path': path.as_posix(),
        'sha256': sha256_file(path),
    }


def _path_candidate(job, key: str):
    data = _object_to_dict(job)
    if key in data:
        return data[key]
    layout = data.get('layout')
    if layout is not None and key == 'build_lock_path':
        build_dir = _value(layout, 'build_artifacts_dir')
        if build_dir is not None:
            return Path(build_dir) / 'build_lock.json'
    return None


def _object_to_dict(value) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, 'to_dict'):
        return value.to_dict()
    if hasattr(value, '__dict__'):
        return dict(value.__dict__)
    return {}


def _value(obj, name: str):
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)
