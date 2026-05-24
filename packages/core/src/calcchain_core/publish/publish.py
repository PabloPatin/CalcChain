from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any
from collections.abc import Mapping

import tomlkit

from ..build.lock import LockMetadata
from ..common.errors import ConfigFormatError, PublishError, RulesError
from ..common.hash import sha256_dict, sha256_file, tree_sha256
from ..io.source import SourceRef
from ..io.target import PublishedRef, TargetRef, TargetRegistry
from ..rules import RuleSetType, RuleUse, RulesFile, get_rule_set
from ..utils.validation import mapping_value, optional_list, optional_mapping, required_mapping, required_str
from ..workspace.artifacts import ArtifactRef
from ..workspace.file_map import FileMapEntry, apply_rule_set
from ..manifest import Manifest, ManifestWriter
from .config import PublishConfig, PublishTarget
from .lock import PublishLock


@dataclass(frozen=True)
class PublishPlanFile:
    target: TargetRef
    relative_path: str
    data: bytes


@dataclass(frozen=True)
class PublishPlanGroup:
    name: str
    category: str
    target: TargetRef
    rules: RuleUse
    map: list[FileMapEntry]
    tree_sha256: str
    files: list[PublishPlanFile] = field(default_factory=list)
    target_name: str = ''
    published_sources: dict[str, SourceRef] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result = {
            'name': self.name,
            'tree_sha256': self.tree_sha256,
            'target': self.target.to_dict(),
            'rules': self.rules.to_dict(),
            'map': [entry.to_dict() for entry in self.map],
        }
        if self.published_sources:
            result['published_sources'] = {
                path: source.to_dict()
                for path, source in sorted(self.published_sources.items())
            }
        return result


@dataclass(frozen=True)
class PublishPlan:
    manifest: Manifest
    lock: PublishLock
    groups: list[PublishPlanGroup]
    service_artifacts: list[PublishPlanFile]
    manifest_path: str
    target_registry: TargetRegistry


@dataclass(frozen=True)
class PublishResult:
    publish_lock_artifact: ArtifactRef | None
    groups: list[PublishPlanGroup]
    service_artifacts: list[ArtifactRef]
    updated_manifest: Manifest
    service_target: TargetRef
    dry_run: bool = False


def create_publish_lock(config: PublishConfig, target_registry: TargetRegistry) -> PublishLock:
    try:
        service_target = _resolve_target_for_lock(config.service_target, target_registry)
        targets = [
            PublishTarget(
                name=target.name,
                target=_resolve_target_for_lock(target.target, target_registry),
                rule_sets=list(target.rule_sets),
                message=target.message,
            )
            for target in config.targets
        ]
    except (ConfigFormatError, PublishError) as err:
        raise PublishError(str(err)) from err
    return PublishLock(
        schema_version=config.schema_version,
        lock=LockMetadata(
            created_at=datetime.now(timezone.utc).isoformat(),
            created_from='publish.toml',
            source_sha256=sha256_dict(config.to_dict()),
            source_sha256_field='publish_toml_sha256',
        ),
        message=config.message,
        service_target=service_target,
        targets=targets,
    )


def build_publish_plan(
    manifest: Manifest,
    lock: PublishLock,
    rules: RulesFile | None,
    *,
    target_registry: TargetRegistry | None = None,
) -> PublishPlan:
    data = manifest.to_dict()
    job_dir = Path(required_str(required_mapping(data, 'job'), 'job_dir'))
    work_dir = job_dir / 'work'
    groups = _publication_groups(data, work_dir, lock, rules)
    service_artifacts = _service_artifacts(data, lock.service_target, lock)
    return PublishPlan(
        manifest=manifest,
        lock=lock,
        groups=groups,
        service_artifacts=service_artifacts,
        manifest_path='manifest.json',
        target_registry=target_registry or TargetRegistry(),
    )


def execute_publish_plan(plan: PublishPlan, *, dry_run: bool = False) -> PublishResult:
    if dry_run:
        return PublishResult(
            publish_lock_artifact=None,
            groups=list(plan.groups),
            service_artifacts=[],
            updated_manifest=plan.manifest,
            service_target=plan.lock.service_target,
            dry_run=True,
        )

    registry = plan.target_registry
    registry.ensure_root(plan.lock.service_target)
    for target in _unique_targets([group.target for group in plan.groups]):
        registry.ensure_root(target)

    published_group_sources: dict[str, dict[str, SourceRef]] = {}
    for group in plan.groups:
        group_sources: dict[str, SourceRef] = {}
        for file in group.files:
            ref = registry.write_file(file.target, file.relative_path, file.data)
            _validate_published_ref(ref)
            group_sources[file.relative_path] = ref.source
        published_group_sources[group.name] = group_sources
    published_groups = [
        replace(group, published_sources=published_group_sources.get(group.name, {}))
        for group in plan.groups
    ]

    published_service_refs: list[PublishedRef] = []
    for file in plan.service_artifacts:
        published_service_refs.append(registry.write_file(file.target, file.relative_path, file.data))

    publish_lock_ref = _published_artifact_from_write(
        _required_published_ref(published_service_refs, plan.service_artifacts, 'publish.lock.toml'),
        _publish_lock_bytes(plan.lock),
    )
    service_artifacts = [
        _published_artifact_from_write(ref, file.data)
        for ref, file in zip(published_service_refs, plan.service_artifacts, strict=True)
    ]
    interim = PublishResult(
        publish_lock_artifact=publish_lock_ref,
        groups=published_groups,
        service_artifacts=service_artifacts,
        updated_manifest=plan.manifest,
        service_target=plan.lock.service_target,
        dry_run=False,
    )
    updated_manifest = ManifestWriter.create_after_publish(plan.manifest, interim)
    registry.write_file(plan.lock.service_target, plan.manifest_path, _manifest_bytes(updated_manifest))
    return replace(interim, updated_manifest=updated_manifest)


def _resolve_target_for_lock(target: TargetRef, registry: TargetRegistry) -> TargetRef:
    registry.validate_config(target)
    resolved = registry.resolve_lock_ref(target)
    TargetRef.from_dict(resolved.to_dict())
    registry.validate_lock_ref(resolved)
    return resolved


def _publication_groups(
    manifest_data: dict[str, Any],
    work_dir: Path,
    lock: PublishLock,
    rules: RulesFile | None,
) -> list[PublishPlanGroup]:
    if not lock.targets:
        return []
    if rules is None:
        raise PublishError('rules are required when result targets are configured')
    file_groups = required_mapping(required_mapping(manifest_data, 'run'), 'file_groups')
    groups: list[PublishPlanGroup] = []
    for publish_target in lock.targets:
        for rule_set_name in publish_target.rule_sets:
            rule_set = _result_rule_set(rules, rule_set_name)
            category = _category_for_rule_set(rule_set.type)
            files = [_normalize_relative_path(item, field=f'{category} file') for item in file_groups.get(category, [])]
            if not files:
                continue
            try:
                translated = apply_rule_set(files, rule_set)
            except RulesError as err:
                raise PublishError(str(err)) from err
            entries: list[FileMapEntry] = []
            plan_files: list[PublishPlanFile] = []
            for entry in translated:
                if entry.source_path is None or entry.work_path is None:
                    raise PublishError('publication rule produced incomplete map entry')
                work_path = _normalize_relative_path(entry.source_path, field='work path')
                target_path = _normalize_relative_path(entry.work_path, field='target path')
                source_path = _safe_join(work_dir, work_path)
                if not source_path.is_file():
                    raise PublishError(f'publication source file not found: {work_path}')
                digest = sha256_file(source_path)
                entries.append(FileMapEntry(sha256=digest, work_path=work_path, target_path=target_path))
                plan_files.append(PublishPlanFile(target=publish_target.target, relative_path=target_path, data=source_path.read_bytes()))
            groups.append(
                PublishPlanGroup(
                    name=f'{publish_target.name}_{rule_set_name}',
                    category=category,
                    target=publish_target.target,
                    rules=RuleUse(set=rule_set_name, status=rule_set.status),
                    map=entries,
                    tree_sha256=tree_sha256((entry.target_path or '', entry.sha256) for entry in entries),
                    files=plan_files,
                    target_name=publish_target.name,
                ),
            )
    return groups


def _service_artifacts(manifest_data: dict[str, Any], service_target: TargetRef, lock: PublishLock) -> list[PublishPlanFile]:
    result: list[PublishPlanFile] = [
        PublishPlanFile(target=service_target, relative_path='publish.lock.toml', data=_publish_lock_bytes(lock)),
    ]
    build_lock = optional_mapping(optional_mapping(manifest_data, 'build') or {}, 'lock')
    if build_lock is not None:
        result.extend(_artifact_files(build_lock, service_target, 'build/build_lock.json'))

    for relative_path, source_path in _frozen_input_files(manifest_data):
        result.append(
            PublishPlanFile(
                target=service_target,
                relative_path=_join_relative('frozen_inputs', relative_path),
                data=source_path.read_bytes(),
            ),
        )

    for snapshot_name, artifact in (optional_mapping(manifest_data, 'snapshots') or {}).items():
        snapshot_data = mapping_value(artifact, f'snapshot {snapshot_name}')
        snapshot_source = _first_local_source_path(snapshot_data)
        snapshot_file_name = snapshot_source.name if snapshot_source is not None else f'{snapshot_name}.json'
        result.extend(_artifact_files(snapshot_data, service_target, _join_relative('snapshots', snapshot_file_name)))
    return _deduplicate_plan_files(result)


def _artifact_files(artifact: Mapping[str, Any], target: TargetRef, relative_path: str) -> list[PublishPlanFile]:
    source_path = _first_local_source_path(artifact)
    if source_path is None or not source_path.is_file():
        return []
    return [PublishPlanFile(target=target, relative_path=relative_path, data=source_path.read_bytes())]


def _frozen_input_files(manifest_data: dict[str, Any]) -> list[tuple[str, Path]]:
    result: list[tuple[str, Path]] = []
    build = optional_mapping(manifest_data, 'build') or {}
    for item in optional_list(build, 'inputs'):
        item_data = mapping_value(item, 'build input')
        if item_data.get('name') != 'frozen_inputs':
            continue
        root = _first_local_source_path(item_data)
        if root is None or not root.is_dir():
            continue
        for path in sorted(file for file in root.rglob('*') if file.is_file()):
            result.append((path.relative_to(root).as_posix(), path))
    return result


def _first_local_source_path(artifact_or_set: Mapping[str, Any]) -> Path | None:
    path = artifact_or_set.get('path')
    if isinstance(path, str):
        return Path(path)
    sources = artifact_or_set.get('sources')
    if isinstance(sources, list):
        for source in sources:
            source_ref = SourceRef.from_dict(dict(mapping_value(source, 'source')))
            if source_ref.data.get('type') == 'local' and isinstance(source_ref.data.get('path'), str):
                return Path(source_ref.data['path'])
    source = artifact_or_set.get('source')
    if isinstance(source, Mapping):
        source_ref = SourceRef.from_dict(dict(source))
        if source_ref.data.get('type') == 'local' and isinstance(source_ref.data.get('path'), str):
            return Path(source_ref.data['path'])
    return None


def _published_artifact_from_write(ref: PublishedRef, data: bytes) -> ArtifactRef:
    _validate_published_ref(ref)
    return ArtifactRef(sha256=hashlib.sha256(data).hexdigest(), sources=[ref.source])


def _required_published_ref(refs: list[PublishedRef], files: list[PublishPlanFile], relative_path: str) -> PublishedRef:
    for ref, file in zip(refs, files, strict=True):
        if file.relative_path == relative_path:
            return ref
    raise PublishError(f'published service artifact was not written: {relative_path}')


def _validate_published_ref(ref: PublishedRef) -> None:
    SourceRef.from_dict(ref.source.to_dict())


def _publish_lock_bytes(lock: PublishLock) -> bytes:
    return tomlkit.dumps(lock.to_dict()).encode('utf-8')


def _manifest_bytes(manifest: Manifest) -> bytes:
    return (json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def _result_rule_set(rules: RulesFile, name: str):
    for rule_type in (RuleSetType.OUTPUT, RuleSetType.LOGS, RuleSetType.TEMP):
        try:
            return get_rule_set(rules, name, rule_type)
        except RulesError:
            continue
    raise PublishError(f'publication rule set must be output/logs/temp: {name}')


def _category_for_rule_set(rule_type: RuleSetType) -> str:
    return {
        RuleSetType.OUTPUT: 'outputs',
        RuleSetType.LOGS: 'logs',
        RuleSetType.TEMP: 'temp',
    }[rule_type]


def _deduplicate_plan_files(files: list[PublishPlanFile]) -> list[PublishPlanFile]:
    result: list[PublishPlanFile] = []
    seen: set[tuple[str, str]] = set()
    for file in files:
        key = (sha256_dict(file.target.to_dict()), file.relative_path)
        if key in seen:
            continue
        seen.add(key)
        result.append(file)
    return result


def _unique_targets(targets: list[TargetRef]) -> list[TargetRef]:
    result: list[TargetRef] = []
    seen: set[str] = set()
    for target in targets:
        key = sha256_dict(target.to_dict())
        if key not in seen:
            seen.add(key)
            result.append(target)
    return result


def _safe_join(root: Path, relative_path: str) -> Path:
    normalized = _normalize_relative_path(relative_path, field='work path')
    result = root.joinpath(*PurePosixPath(normalized).parts)
    try:
        result.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError as err:
        raise PublishError(f'work path escapes work dir: {relative_path}') from err
    return result


def _join_relative(base: str, relative_path: str) -> str:
    return f'{_normalize_relative_path(base, field="service path")}/{_normalize_relative_path(relative_path, field="service path")}'


def _normalize_relative_path(value: str, *, field: str) -> str:
    normalized = str(value).replace('\\', '/')
    if normalized.startswith('/') or _has_windows_drive(normalized):
        raise PublishError(f'{field} must be relative: {value}')
    path = PurePosixPath(normalized)
    if '..' in path.parts:
        raise PublishError(f'{field} must not contain path traversal: {value}')
    result = path.as_posix()
    if result in {'', '.'}:
        raise PublishError(f'{field} must identify a file: {value}')
    return result


def _has_windows_drive(value: str) -> bool:
    return len(value) >= 2 and value[1] == ':' and value[0].isalpha()
