from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ..common.status import JobStatus
from ..config import MANIFEST_SCHEMA_VERSION
from ..utils.json import write_json
from ..utils.validation import optional_str, required_mapping
from ..workspace.artifacts import ArtifactRef
from ..workspace.maps import FileSetMap


class DictSerializable(Protocol):
    def to_dict(self) -> dict[str, Any]:
        ...


class BuildManifestSource(Protocol):
    code_set: FileSetMap
    input_sets: list[FileSetMap]


class RunManifestSource(Protocol):
    status: Any


class FileGroupsManifestSource(DictSerializable, Protocol):
    pass


class PublishManifestGroupSource(DictSerializable, Protocol):
    category: str


class PublishManifestSource(Protocol):
    publish_lock_artifact: ArtifactRef | None
    groups: list[PublishManifestGroupSource]
    service_artifacts: list[ArtifactRef]
    service_target: DictSerializable


@dataclass(frozen=True)
class JobManifestInfo:
    id: str
    job_dir: Path | None = None
    created_at: str | None = None
    user: str | None = None
    hostname: str | None = None

    def to_dict(self, status: str) -> dict[str, Any]:
        result: dict[str, Any] = {'id': self.id, 'status': status}
        if self.created_at is not None:
            result['created_at'] = self.created_at
        if self.job_dir is not None:
            result['job_dir'] = str(self.job_dir)
        if self.user is not None:
            result['user'] = self.user
        if self.hostname is not None:
            result['hostname'] = self.hostname
        return result


@dataclass(frozen=True)
class BuildManifestArtifacts:
    build_lock: ArtifactRef | None = None
    rules: ArtifactRef | None = None
    snapshots: dict[str, ArtifactRef] = field(default_factory=dict)


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
    def create_after_build(
        job: JobManifestInfo,
        build_result: BuildManifestSource,
        artifacts: BuildManifestArtifacts | None = None,
    ) -> Manifest:
        artifacts = artifacts or BuildManifestArtifacts()
        data: dict[str, Any] = {
            'schema_version': MANIFEST_SCHEMA_VERSION,
            'job': job.to_dict(JobStatus.BUILT.value),
            'build': _build_dict(build_result, artifacts, frozen_inputs=None),
        }
        if artifacts.rules is not None:
            data['rules'] = artifacts.rules.to_dict()
        if artifacts.snapshots:
            data['snapshots'] = _snapshot_refs(artifacts.snapshots)
        return Manifest.from_dict(data)

    @staticmethod
    def create_after_run(
        job: JobManifestInfo,
        build_result: BuildManifestSource,
        run_result: RunManifestSource,
        file_groups: FileGroupsManifestSource,
        artifacts: BuildManifestArtifacts | None = None,
        *,
        frozen_inputs: FileSetMap | None = None,
    ) -> Manifest:
        artifacts = artifacts or BuildManifestArtifacts()
        status_value = _status_value(run_result.status)
        data: dict[str, Any] = {
            'schema_version': MANIFEST_SCHEMA_VERSION,
            'job': job.to_dict(status_value),
            'build': _build_dict(build_result, artifacts, frozen_inputs=frozen_inputs),
            'run': {
                'status': status_value,
                'file_groups': file_groups.to_dict(),
            },
        }
        if artifacts.rules is not None:
            data['rules'] = artifacts.rules.to_dict()
        if artifacts.snapshots:
            data['snapshots'] = _snapshot_refs(artifacts.snapshots)
        return Manifest.from_dict(data)

    @staticmethod
    def create_after_publish(existing_manifest: Manifest, publish_result: PublishManifestSource) -> Manifest:
        data = existing_manifest.to_dict()
        data.setdefault('schema_version', MANIFEST_SCHEMA_VERSION)
        data.setdefault('job', {})['status'] = JobStatus.PUBLISHED.value
        publication = _publication_dict(publish_result)
        if publication:
            data['publication'] = publication
        return Manifest.from_dict(data)


def write_manifest(manifest: Manifest, path: Path) -> None:
    write_json(manifest.to_dict(), path)


def _build_dict(
    build_result: BuildManifestSource,
    artifacts: BuildManifestArtifacts,
    *,
    frozen_inputs: FileSetMap | None,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if artifacts.build_lock is not None:
        result['lock'] = artifacts.build_lock.to_dict()
    result['code'] = build_result.code_set.to_dict()
    result['inputs'] = [item.to_dict() for item in build_result.input_sets]
    if frozen_inputs is not None:
        result['inputs'].append(frozen_inputs.to_dict())
    return result


def _snapshot_refs(snapshots: Mapping[str, ArtifactRef]) -> dict[str, Any]:
    return {
        str(name): artifact.to_dict()
        for name, artifact in snapshots.items()
    }


def _publication_dict(publish_result: PublishManifestSource) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if publish_result.publish_lock_artifact is not None:
        result['lock'] = publish_result.publish_lock_artifact.to_dict()

    for group in publish_result.groups:
        if group.category not in {'outputs', 'logs', 'temp'}:
            continue
        result.setdefault(group.category, []).append(group.to_dict())

    if publish_result.service_artifacts:
        result['service_artifacts'] = [
            artifact.to_dict()
            for artifact in publish_result.service_artifacts
        ]
    result['service_target'] = publish_result.service_target.to_dict()
    return result


def _status_value(status) -> str:
    return status.value if hasattr(status, 'value') else str(status)
