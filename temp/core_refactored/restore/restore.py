from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from ..common.errors import ConfigFormatError, RestoreError, SourceError
from ..common.hash import tree_sha256
from ..io.source import SourceRef, SourceRegistry
from ..utils.json import read_json
from ..utils.validation import mapping_value, optional_list, optional_mapping, required_mapping, required_str
from ..workspace.file_map import FileMapEntry
from ..workspace.layout import JobLayout
from ..workspace.manifest import Manifest


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
    fallback_sources: tuple[tuple[SourceRef, str], ...] = ()


def restore_from_manifest(request: RestoreRequest, source_registry: SourceRegistry) -> RestoreResult:
    manifest = _read_manifest(Path(request.manifest_path))
    layout = JobLayout.from_job_dir(Path(request.target_job_dir))
    files = _restore_files(manifest)

    restored: list[str] = []
    verified: list[str] = []
    missing: list[str] = []
    for file in files:
        try:
            data = _read_restore_file_bytes(file, source_registry)
        except (OSError, RestoreError, SourceError) as err:
            missing.append(file.relative_path)
            raise RestoreError(f'restore source unavailable for {file.relative_path}: {err}') from err

        actual = _sha256_bytes(data)
        if actual != file.sha256:
            raise RestoreError(f'restored source hash mismatch for {file.relative_path}')
        verified.append(file.relative_path)

        if request.dry_run:
            continue
        destination = _safe_join(layout.work_dir, file.relative_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        restored.append(file.relative_path)

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
        return Manifest.from_dict(read_json(path))
    except (OSError, ConfigFormatError) as err:
        raise RestoreError(f'failed to read manifest: {path}') from err


def _restore_files(manifest: Manifest) -> list[_RestoreFile]:
    data = manifest.to_dict()
    build = required_mapping(data, 'build')
    result: list[_RestoreFile] = []
    frozen_set = _frozen_input_set(build)
    published_frozen_roots = _published_service_roots(data)
    frozen_by_work_path = _frozen_restore_files(
        frozen_set,
        published_frozen_roots=published_frozen_roots,
    ) if frozen_set is not None else {}
    result.extend(_files_from_file_set(required_mapping(build, 'code')))
    restored_input_paths: set[str] = set()
    for raw_input in optional_list(build, 'inputs'):
        input_set = mapping_value(raw_input, 'build input')
        if input_set.get('name') == 'frozen_inputs':
            continue
        input_files = _files_from_file_set(input_set, frozen_by_work_path=frozen_by_work_path)
        restored_input_paths.update(file.relative_path for file in input_files)
        result.extend(input_files)
    unused_frozen_paths = set(frozen_by_work_path) - restored_input_paths
    if unused_frozen_paths:
        raise RestoreError(f'frozen inputs do not match declared inputs: {", ".join(sorted(unused_frozen_paths))}')
    return _dedupe_restore_files(result)


def _files_from_file_set(
    file_set: Mapping[str, Any],
    *,
    frozen_by_work_path: dict[str, _RestoreFile] | None = None,
) -> list[_RestoreFile]:
    sources = _source_refs(file_set)
    if not sources:
        raise RestoreError(f'restore source is missing for file set: {file_set.get("name", "unknown")}')
    source = sources[0]
    files = []
    used_frozen_overlay = False
    for raw_entry in optional_list(file_set, 'map'):
        entry_data = mapping_value(raw_entry, 'map entry')
        work_path = required_str(entry_data, 'work_path')
        frozen_file = (frozen_by_work_path or {}).get(work_path)
        if frozen_file is not None:
            files.append(frozen_file)
            used_frozen_overlay = True
            continue
        files.append(_restore_file_from_entry(source, entry_data))
    if not used_frozen_overlay:
        _verify_declared_tree(file_set, files)
    return files


def _restore_file_from_entry(source: SourceRef, raw_entry: Mapping[str, Any]) -> _RestoreFile:
    entry = FileMapEntry.from_dict(raw_entry)
    return _RestoreFile(
        relative_path=_required_entry_path(entry.work_path, 'work_path'),
        sha256=entry.sha256.lower(),
        source=source,
        source_path=_required_entry_path(entry.source_path, 'source_path'),
    )


def _frozen_restore_files(
    frozen_set: Mapping[str, Any],
    *,
    published_frozen_roots: list[SourceRef],
) -> dict[str, _RestoreFile]:
    sources = _source_refs(frozen_set)
    if not sources:
        raise RestoreError('restore source is missing for frozen inputs')
    result: dict[str, _RestoreFile] = {}
    for raw_entry in optional_list(frozen_set, 'map'):
        entry = FileMapEntry.from_dict(mapping_value(raw_entry, 'frozen map entry'))
        work_path = _required_entry_path(entry.work_path, 'frozen work_path')
        if work_path in result:
            raise RestoreError(f'duplicate frozen input path: {work_path}')
        source_path = _required_entry_path(entry.target_path or entry.source_path, 'frozen source_path')
        candidates = _frozen_source_candidates(
            source_path,
            published_frozen_roots,
            sources[0],
        )
        result[work_path] = _RestoreFile(
            relative_path=work_path,
            sha256=entry.sha256.lower(),
            source=candidates[0][0],
            source_path=candidates[0][1],
            fallback_sources=tuple(candidates[1:]),
        )
    _verify_declared_tree(frozen_set, list(result.values()))
    return result


def _read_restore_file_bytes(file: _RestoreFile, registry: SourceRegistry) -> bytes:
    first_error: Exception | None = None
    for source, source_path in [(file.source, file.source_path), *file.fallback_sources]:
        try:
            return registry.read_file(source, source_path)
        except (OSError, SourceError) as err:
            if first_error is None:
                first_error = err
            continue
    if first_error is not None:
        raise first_error
    raise RestoreError(f'restore source unavailable for {file.relative_path}')


def _source_refs(container: Mapping[str, Any]) -> list[SourceRef]:
    return [
        SourceRef.from_dict(dict(mapping_value(item, 'source')))
        for item in optional_list(container, 'sources')
    ]


def _published_service_roots(data: Mapping[str, Any]) -> list[SourceRef]:
    publication = optional_mapping(data, 'publication')
    if publication is None:
        return []
    lock = optional_mapping(publication, 'lock')
    if lock is None:
        return []
    result: list[SourceRef] = []
    for source in _source_refs(lock):
        service_root = _service_root_from_published_lock(source)
        if service_root is not None:
            result.append(service_root)
    return result


def _service_root_from_published_lock(source: SourceRef) -> SourceRef | None:
    path = _source_path(source)
    if path is None:
        return None
    normalized = path.replace('\\', '/')
    parts = PurePosixPath(normalized).parts
    if not parts:
        return None
    data = dict(source.data)
    data['path'] = str(Path(path).parent) if _source_type(source) == 'local' else PurePosixPath(*parts[:-1]).as_posix()
    return SourceRef(data=data, credentials=source.credentials)


def _frozen_source_candidates(
    frozen_source_path: str,
    published_service_roots: list[SourceRef],
    original_source: SourceRef,
) -> list[tuple[SourceRef, str]]:
    result = [(root, _join_relative('frozen_inputs', frozen_source_path)) for root in published_service_roots]
    result.append((original_source, frozen_source_path))
    return result


def _join_relative(base: str, relative_path: str) -> str:
    base_path = _normalize_relative_path(base, field='service path')
    child_path = _normalize_relative_path(relative_path, field='service path')
    return f'{base_path}/{child_path}'


def _source_type(source: SourceRef) -> str | None:
    value = source.data.get('type')
    return value if isinstance(value, str) else None


def _source_path(source: SourceRef) -> str | None:
    value = source.data.get('path')
    return value if isinstance(value, str) else None


def _verify_work_tree(layout: JobLayout, manifest: Manifest) -> None:
    data = manifest.to_dict()
    build = required_mapping(data, 'build')
    frozen_set = _frozen_input_set(build)
    frozen_paths = {
        required_str(mapping_value(entry, 'frozen map entry'), 'work_path')
        for entry in optional_list(frozen_set, 'map')
    } if frozen_set is not None else set()

    for file in _restore_files(manifest):
        restored = _safe_join(layout.work_dir, file.relative_path)
        if not restored.is_file():
            raise RestoreError(f'restored file missing during verification: {file.relative_path}')
        if _sha256_bytes(restored.read_bytes()) != file.sha256:
            raise RestoreError(f'restored file hash mismatch during verification: {file.relative_path}')

    for file_set in [required_mapping(build, 'code'), *[mapping_value(item, 'build input') for item in optional_list(build, 'inputs')]]:
        if file_set.get('name') != 'frozen_inputs' and any(
            required_str(mapping_value(entry, 'map entry'), 'work_path') in frozen_paths
            for entry in optional_list(file_set, 'map')
        ):
            continue
        expected = file_set.get('tree_sha256')
        if not isinstance(expected, str):
            continue
        entries = []
        for raw_entry in optional_list(file_set, 'map'):
            entry = FileMapEntry.from_dict(mapping_value(raw_entry, 'map entry'))
            work_path = _required_entry_path(entry.work_path, 'work_path')
            restored = _safe_join(layout.work_dir, work_path)
            if not restored.is_file():
                raise RestoreError(f'restored file missing during verification: {work_path}')
            entries.append((work_path, _sha256_bytes(restored.read_bytes())))
        if entries and tree_sha256(entries) != expected.lower():
            raise RestoreError(f'restored tree hash mismatch for file set: {file_set.get("name", "unknown")}')


def _frozen_input_set(build: Mapping[str, Any]) -> Mapping[str, Any] | None:
    for item in optional_list(build, 'inputs'):
        data = mapping_value(item, 'build input')
        if data.get('name') == 'frozen_inputs':
            return data
    return None


def _verify_declared_tree(file_set: Mapping[str, Any], files: list[_RestoreFile]) -> None:
    expected = file_set.get('tree_sha256')
    if isinstance(expected, str):
        actual = tree_sha256((file.relative_path, file.sha256) for file in files)
        if actual != expected.lower():
            raise RestoreError(f'manifest tree hash mismatch for file set: {file_set.get("name", "unknown")}')


def _dedupe_restore_files(files: list[_RestoreFile]) -> list[_RestoreFile]:
    result: list[_RestoreFile] = []
    seen: dict[str, _RestoreFile] = {}
    for file in files:
        previous = seen.get(file.relative_path)
        if previous is not None:
            if previous.sha256 == file.sha256 and previous.source == file.source and previous.source_path == file.source_path:
                continue
            raise RestoreError(f'duplicate restore path: {file.relative_path}')
        seen[file.relative_path] = file
        result.append(file)
    return result


def _safe_join(root: Path, relative_path: str) -> Path:
    path = PurePosixPath(_normalize_relative_path(relative_path, field='restore path'))
    root_resolved = root.resolve(strict=False)
    result = root.joinpath(*path.parts)
    try:
        result.resolve(strict=False).relative_to(root_resolved)
    except ValueError as err:
        raise RestoreError(f'restore path escapes target root: {relative_path}') from err
    return result


def _normalize_relative_path(value: str, *, field: str) -> str:
    normalized = value.replace('\\', '/')
    if normalized.startswith('/') or _has_windows_drive(normalized):
        raise RestoreError(f'{field} must be relative: {value}')
    path = PurePosixPath(normalized)
    if '..' in path.parts or path.as_posix() in {'', '.'}:
        raise RestoreError(f'{field} is unsafe: {value}')
    return path.as_posix()


def _required_entry_path(value: str | None, field: str) -> str:
    if value is None:
        raise RestoreError(f'{field} is required for restore')
    return value


def _has_windows_drive(value: str) -> bool:
    return len(value) >= 2 and value[1] == ':' and value[0].isalpha()


def _sha256_bytes(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()
