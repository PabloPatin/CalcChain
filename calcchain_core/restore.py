from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path, PurePosixPath
from typing import Any

from calcchain_core.errors import ConfigFormatError, RestoreError, SourceError
from calcchain_core.hash import sha256_file, tree_sha256
from calcchain_core.layout import JobLayout
from calcchain_core.models import FileMapEntry, Manifest, SourceRef, SourceType, TargetRef
from calcchain_core.artifacts import published_source
from calcchain_core.sources import SourceRegistry, sanitize_source_error_message


@dataclass(frozen=True)
class RestoreRequest:
    manifest_path: Path
    target_job_dir: Path
    dry_run: bool = False


@dataclass(frozen=True)
class RestoreResult:
    restored_files: list[str] = field(default_factory=list)
    verified_hashes: list[str] = field(default_factory=list)
    missing_sources: list[str] = field(default_factory=list)
    status: str = 'restored'


@dataclass(frozen=True)
class _RestoreFile:
    relative_path: str
    sha256: str
    source: SourceRef
    source_path: str
    service_path: Path | None = None
    fallback_sources: tuple[tuple[SourceRef, str], ...] = ()


def restore_from_manifest(request: RestoreRequest, source_registry: SourceRegistry) -> RestoreResult:
    manifest = _read_manifest(Path(request.manifest_path))
    layout = JobLayout.from_job_dir(Path(request.target_job_dir))
    files = _restore_files(manifest)
    files.extend(_service_artifact_files(manifest, layout))

    restored: list[str] = []
    verified: list[str] = []
    missing: list[str] = []
    for file in files:
        try:
            data = _read_restore_file_bytes(file, source_registry)
        except (OSError, SourceError, RestoreError) as err:
            missing.append(file.relative_path)
            if _is_required(file):
                raise RestoreError(sanitize_source_error_message(f'restore source unavailable: {err}', file.source)) from err
            continue
        actual = _sha256_bytes(data)
        if actual != file.sha256:
            raise RestoreError(f'restored source hash mismatch for {file.relative_path}')
        verified.append(file.relative_path)
        if request.dry_run:
            continue
        destination = _safe_service_destination(layout, file.service_path) if file.service_path is not None else _safe_join(layout.work_dir, file.relative_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        restored.append(file.relative_path if file.service_path is None else destination.relative_to(layout.job_dir).as_posix())

    if not request.dry_run:
        _verify_work_tree(layout, manifest)
    return RestoreResult(
        restored_files=restored if not request.dry_run else [file.relative_path for file in files],
        verified_hashes=verified,
        missing_sources=missing,
        status='planned' if request.dry_run else 'restored',
    )


def _read_manifest(path: Path) -> Manifest:
    try:
        with path.open('r', encoding='utf-8') as file:
            return Manifest.from_dict(json.load(file))
    except (OSError, json.JSONDecodeError, ConfigFormatError) as err:
        raise RestoreError(f'failed to read manifest: {path}') from err


def _restore_files(manifest: Manifest) -> list[_RestoreFile]:
    data = manifest.to_dict()
    build = _required_mapping(data, 'build')
    frozen = _frozen_input_set(build)
    published_frozen_sources = _published_service_frozen_sources(data)
    frozen_by_work_path = {
        _required_str(entry, 'work_path'): (frozen, _file_map_entry(entry))
        for entry in _map_entries(frozen)
    } if frozen is not None else {}

    result: list[_RestoreFile] = []
    code = _optional_mapping(build, 'code')
    if code is not None:
        result.extend(_files_from_file_set(code, role='code', frozen_by_work_path={}))
    for input_set in _optional_list(build, 'inputs'):
        item = _mapping_value(input_set, 'build input')
        if item.get('name') == 'frozen_inputs':
            result.extend(_files_from_frozen_set(item))
            continue
        result.extend(
            _files_from_file_set(
                item,
                role='input',
                frozen_by_work_path=frozen_by_work_path,
                published_frozen_sources=published_frozen_sources,
            ),
        )
    result.extend(_files_from_publication(data))
    return _dedupe_restore_files(result)


def _files_from_file_set(
    file_set: dict[str, Any],
    *,
    role: str,
    frozen_by_work_path: dict[str, tuple[dict[str, Any], FileMapEntry]],
    published_frozen_sources: list[SourceRef] | None = None,
) -> list[_RestoreFile]:
    result: list[_RestoreFile] = []
    source = _single_source(file_set)
    used_frozen_overlay = False
    for raw_entry in _map_entries(file_set):
        entry = _file_map_entry(raw_entry)
        work_path = _required_entry_path(entry.work_path, 'work_path')
        if role == 'input' and work_path in frozen_by_work_path:
            used_frozen_overlay = True
            frozen_set, frozen_entry = frozen_by_work_path[work_path]
            frozen_source = _single_source(frozen_set)
            frozen_source_path = _required_entry_path(frozen_entry.target_path or frozen_entry.source_path, 'frozen source_path')
            candidates = _frozen_source_candidates(
                frozen_source_path,
                published_frozen_sources or [],
                frozen_source,
            )
            result.append(
                _RestoreFile(
                    relative_path=work_path,
                    sha256=frozen_entry.sha256,
                    source=candidates[0][0],
                    source_path=candidates[0][1],
                    fallback_sources=tuple(candidates[1:]),
                ),
            )
            continue
        result.append(
            _RestoreFile(
                relative_path=work_path,
                sha256=entry.sha256,
                source=source,
                source_path=_required_entry_path(entry.source_path, 'source_path'),
            ),
        )
    if not used_frozen_overlay:
        _verify_declared_tree(file_set, result)
    return result


def _files_from_frozen_set(file_set: dict[str, Any]) -> list[_RestoreFile]:
    source = _single_source(file_set)
    result = [
        _RestoreFile(
            relative_path=_required_entry_path(entry.work_path, 'work_path'),
            sha256=entry.sha256,
            source=source,
            source_path=_required_entry_path(entry.target_path or entry.source_path, 'frozen source_path'),
        )
        for entry in (_file_map_entry(item) for item in _map_entries(file_set))
    ]
    _verify_declared_tree(file_set, result)
    return result


def _read_restore_file_bytes(file: _RestoreFile, registry: SourceRegistry) -> bytes:
    first_error: Exception | None = None
    for source, source_path in [(file.source, file.source_path), *file.fallback_sources]:
        try:
            return _read_source_bytes(source, source_path, registry)
        except (OSError, SourceError, RestoreError) as err:
            if first_error is None:
                first_error = err
            continue
    if first_error is not None:
        raise first_error
    raise RestoreError(f'restore source unavailable: {file.relative_path}')


def _published_service_frozen_sources(data: dict[str, Any]) -> list[SourceRef]:
    publication = _optional_mapping(data, 'publication')
    if publication is None:
        return []
    lock = _optional_mapping(publication, 'lock')
    if lock is None:
        return []
    result: list[SourceRef] = []
    for source in _source_refs(lock):
        service_root = _service_root_from_published_lock(source)
        if service_root is not None:
            result.append(service_root)
    return result


def _service_root_from_published_lock(source: SourceRef) -> SourceRef | None:
    normalized = source.path.replace('\\', '/')
    parts = PurePosixPath(normalized).parts
    if not parts:
        return None
    if source.type is SourceType.LOCAL:
        return SourceRef(type=SourceType.LOCAL, path=str(Path(source.path).parent))
    return SourceRef(
        type=source.type,
        location=source.location,
        path=PurePosixPath(*parts[:-1]).as_posix() if len(parts) > 1 else '',
        revision=source.revision,
    )


def _frozen_source_candidates(
    frozen_source_path: str,
    published_service_roots: list[SourceRef],
    original_source: SourceRef,
) -> list[tuple[SourceRef, str]]:
    result = [
        (_join_service_frozen_source(root, frozen_source_path), Path(frozen_source_path).name)
        for root in published_service_roots
    ]
    result.append((original_source, frozen_source_path))
    return result


def _join_service_frozen_source(root: SourceRef, frozen_source_path: str) -> SourceRef:
    relative = _join_relative('frozen_inputs', frozen_source_path)
    if root.type is SourceType.LOCAL:
        return SourceRef(type=SourceType.LOCAL, path=str(Path(root.path) / Path(*PurePosixPath(relative).parts)))
    root_path = root.path.replace('\\', '/').strip('/')
    return SourceRef(
        type=root.type,
        location=root.location,
        path=f'{root_path}/{relative}' if root_path else relative,
        revision=root.revision,
    )


def _join_relative(base: str, relative_path: str) -> str:
    base_path = _normalize_relative_path(base, field='service path')
    child_path = _normalize_relative_path(relative_path, field='service path')
    return f'{base_path}/{child_path}'


def _service_artifact_files(manifest: Manifest, layout: JobLayout) -> list[_RestoreFile]:
    data = manifest.to_dict()
    result: list[_RestoreFile] = []
    build_lock = _optional_mapping(_optional_mapping(data, 'build') or {}, 'lock')
    if build_lock is not None:
        result.append(_artifact_restore_file(build_lock, _safe_join(layout.service_dir, 'build/build_lock.json')))
    for name, artifact in (_optional_mapping(data, 'snapshots') or {}).items():
        target = _safe_join(layout.service_dir, f'snapshots/{_safe_service_artifact_name(name)}_snapshot.json')
        result.append(_artifact_restore_file(_mapping_value(artifact, f'snapshot {name}'), target))
    return result


def _files_from_publication(data: dict[str, Any]) -> list[_RestoreFile]:
    publication = _optional_mapping(data, 'publication')
    if publication is None:
        return []
    result: list[_RestoreFile] = []
    for category in ('outputs', 'logs', 'temp'):
        for raw_group in _optional_list(publication, category):
            group = _mapping_value(raw_group, f'publication {category} group')
            target = TargetRef.from_dict(_required_mapping(group, 'target'), resolved_revision=True)
            for raw_entry in _map_entries(group):
                entry = _file_map_entry(raw_entry)
                work_path = _required_entry_path(entry.work_path, 'work_path')
                target_path = _required_entry_path(entry.target_path, 'target_path')
                source = published_source(target, target_path)
                result.append(
                    _RestoreFile(
                        relative_path=work_path,
                        sha256=entry.sha256,
                        source=source,
                        source_path=_artifact_source_path(source),
                    ),
                )
    return result


def _artifact_restore_file(artifact: dict[str, Any], destination: Path) -> _RestoreFile:
    sources = _source_refs(artifact)
    if not sources:
        raise RestoreError('artifact source is required for restore')
    return _RestoreFile(
        relative_path=destination.name,
        sha256=_required_str(artifact, 'sha256').lower(),
        source=sources[0],
        source_path=_artifact_source_path(sources[0]),
        service_path=destination,
    )


def _read_source_bytes(source: SourceRef, source_path: str, registry: SourceRegistry) -> bytes:
    if source.type is SourceType.LOCAL:
        path = Path(source.path)
        if path.is_file():
            return path.read_bytes()
    if source.type is SourceType.SVN:
        normalized = source.path.replace('\\', '/')
        parts = PurePosixPath(normalized).parts
        if len(parts) > 1:
            parent = PurePosixPath(*parts[:-1]).as_posix()
            return registry.read_file(
                SourceRef(
                    type=source.type,
                    location=source.location,
                    path=parent,
                    revision=source.revision,
                ),
                parts[-1],
            )
    return registry.read_file(source, source_path)


def _verify_work_tree(layout: JobLayout, manifest: Manifest) -> None:
    data = manifest.to_dict()
    build = _required_mapping(data, 'build')
    frozen = _frozen_input_set(build)
    frozen_paths = {
        _required_str(_mapping_value(entry, 'frozen map entry'), 'work_path')
        for entry in _map_entries(frozen)
    } if frozen is not None else set()
    for file_set in [_optional_mapping(build, 'code'), *_optional_list(build, 'inputs')]:
        if file_set is None:
            continue
        item = _mapping_value(file_set, 'file set')
        if item.get('name') != 'frozen_inputs' and any(
            _required_str(_mapping_value(entry, 'map entry'), 'work_path') in frozen_paths
            for entry in _map_entries(item)
        ):
            continue
        expected = item.get('tree_sha256')
        if not isinstance(expected, str):
            continue
        entries = []
        for raw_entry in _map_entries(item):
            entry = _file_map_entry(raw_entry)
            work_path = _required_entry_path(entry.work_path, 'work_path')
            restored = _safe_join(layout.work_dir, work_path)
            if not restored.is_file():
                raise RestoreError(f'restored file missing during verification: {work_path}')
            entries.append((work_path, sha256_file(restored)))
        if entries and tree_sha256(entries) != expected.lower():
            if item.get('name') == 'frozen_inputs':
                continue
            raise RestoreError(f'restored tree hash mismatch for file set: {item.get("name", "unknown")}')


def _verify_declared_tree(file_set: dict[str, Any], files: list[_RestoreFile]) -> None:
    expected = file_set.get('tree_sha256')
    if isinstance(expected, str):
        actual = tree_sha256((file.relative_path, file.sha256) for file in files)
        if actual != expected.lower():
            raise RestoreError(f'manifest tree hash mismatch for file set: {file_set.get("name", "unknown")}')


def _single_source(file_set: dict[str, Any]) -> SourceRef:
    source = file_set.get('source')
    if isinstance(source, dict):
        return SourceRef.from_dict(source, reject_userinfo=True)
    sources = _source_refs(file_set)
    if len(sources) == 1:
        return sources[0]
    if not sources:
        raise RestoreError(f'restore source is missing for file set: {file_set.get("name", "unknown")}')
    raise RestoreError(f'restore source is ambiguous for file set: {file_set.get("name", "unknown")}')


def _source_refs(container: dict[str, Any]) -> list[SourceRef]:
    sources = container.get('sources')
    if not isinstance(sources, list):
        return []
    return [SourceRef.from_dict(_mapping_value(item, 'source'), reject_userinfo=True) for item in sources]


def _artifact_source_path(source: SourceRef) -> str:
    path = source.path.replace('\\', '/')
    if source.type is SourceType.LOCAL:
        return Path(path).name
    parts = PurePosixPath(path).parts
    if not parts:
        raise RestoreError('artifact source path is empty')
    return parts[-1]


def _frozen_input_set(build: dict[str, Any]) -> dict[str, Any] | None:
    for item in _optional_list(build, 'inputs'):
        data = _mapping_value(item, 'build input')
        if data.get('name') == 'frozen_inputs':
            return data
    return None


def _map_entries(file_set: dict[str, Any] | None) -> list[Any]:
    if file_set is None:
        return []
    return _optional_list(file_set, 'map')


def _file_map_entry(data: Any) -> FileMapEntry:
    return FileMapEntry.from_dict(_mapping_value(data, 'map entry'))


def _dedupe_restore_files(files: list[_RestoreFile]) -> list[_RestoreFile]:
    result: list[_RestoreFile] = []
    seen: set[tuple[str, Path | None]] = set()
    for file in files:
        key = (file.relative_path, file.service_path)
        if key in seen:
            continue
        seen.add(key)
        result.append(file)
    return result


def _is_required(file: _RestoreFile) -> bool:
    return True


def _safe_join(root: Path, relative_path: str) -> Path:
    path = PurePosixPath(_normalize_relative_path(relative_path, field='restore path'))
    root_resolved = root.resolve(strict=False)
    result = root.joinpath(*path.parts)
    try:
        result.resolve(strict=False).relative_to(root_resolved)
    except ValueError as err:
        raise RestoreError(f'restore path escapes target root: {relative_path}') from err
    return result


def _safe_service_destination(layout: JobLayout, destination: Path) -> Path:
    service_resolved = layout.service_dir.resolve(strict=False)
    job_resolved = layout.job_dir.resolve(strict=False)
    candidate = Path(destination)
    candidate_resolved = candidate.resolve(strict=False)
    try:
        candidate_resolved.relative_to(service_resolved)
        candidate_resolved.relative_to(job_resolved)
    except ValueError as err:
        raise RestoreError(f'service artifact path escapes service dir: {destination}') from err
    if candidate_resolved == service_resolved:
        raise RestoreError('service artifact path must identify a file')
    return candidate


def _safe_service_artifact_name(value: str) -> str:
    if not isinstance(value, str):
        raise RestoreError('service artifact name must be a string')
    normalized = value.replace('\\', '/')
    if '/' in normalized or normalized.startswith('.') or _has_windows_drive(normalized):
        raise RestoreError(f'service artifact name is unsafe: {value}')
    path = PurePosixPath(normalized)
    if '..' in path.parts or path.as_posix() in {'', '.'}:
        raise RestoreError(f'service artifact name is unsafe: {value}')
    return path.as_posix()


def _normalize_relative_path(value: str, *, field: str) -> str:
    normalized = value.replace('\\', '/')
    if normalized.startswith('/') or _has_windows_drive(normalized):
        raise RestoreError(f'{field} must be relative: {value}')
    path = PurePosixPath(normalized)
    if '..' in path.parts or path.as_posix() in {'', '.'}:
        raise RestoreError(f'{field} is unsafe: {value}')
    return path.as_posix()


def _required_mapping(data: dict[str, Any], key: str) -> dict[str, Any]:
    if key not in data or not isinstance(data[key], dict):
        raise RestoreError(f'missing required object: {key}')
    return data[key]


def _optional_mapping(data: dict[str, Any], key: str) -> dict[str, Any] | None:
    if key not in data:
        return None
    return _mapping_value(data[key], key)


def _mapping_value(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RestoreError(f'{field} must be an object')
    return value


def _optional_list(data: dict[str, Any], key: str) -> list[Any]:
    if key not in data:
        return []
    if not isinstance(data[key], list):
        raise RestoreError(f'{key} must be a list')
    return data[key]


def _required_str(data: dict[str, Any], key: str) -> str:
    if key not in data or not isinstance(data[key], str):
        raise RestoreError(f'missing required string: {key}')
    return data[key]


def _required_entry_path(value: str | None, field: str) -> str:
    if value is None:
        raise RestoreError(f'{field} is required for restore')
    return value


def _has_windows_drive(value: str) -> bool:
    return len(value) >= 2 and value[1] == ':' and value[0].isalpha()


def _sha256_bytes(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()
