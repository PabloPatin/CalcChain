from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import tempfile
from typing import Protocol
from urllib.parse import urlsplit

from calcchain_core.artifacts import published_source
from calcchain_core.errors import PublishError
from calcchain_core.models import SourceRef, SourceType, TargetRef
from svn.src.client import SvnClient


@dataclass(frozen=True)
class PublishedRef:
    target: TargetRef
    relative_path: str
    source: SourceRef


class TargetAdapter(Protocol):
    def write_file(self, target: TargetRef, relative_path: str, data: bytes) -> PublishedRef:
        """Write data under target-relative path and return a published source ref."""

    def ensure_root(self, target: TargetRef) -> TargetRef:
        """Ensure target root exists and return the normalized target."""

    def resolve_revision(self, target: TargetRef) -> TargetRef:
        """Return the target with concrete revision when the target supports revisions."""


class LocalTargetAdapter:
    def write_file(self, target: TargetRef, relative_path: str, data: bytes) -> PublishedRef:
        validate_target_ref(target)
        _ensure_target_type(target, SourceType.LOCAL)
        safe_path = _normalize_relative_path(relative_path, field='local target file')
        destination = _safe_join(Path(target.path), safe_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        return PublishedRef(target=target, relative_path=safe_path, source=published_source(target, safe_path))

    def ensure_root(self, target: TargetRef) -> TargetRef:
        validate_target_ref(target)
        _ensure_target_type(target, SourceType.LOCAL)
        Path(target.path).mkdir(parents=True, exist_ok=True)
        return target

    def resolve_revision(self, target: TargetRef) -> TargetRef:
        validate_target_ref(target)
        _ensure_target_type(target, SourceType.LOCAL)
        return target


class SvnTargetAdapter:
    def __init__(self, client_factory=None):
        self._client_factory = client_factory or self._default_client_factory

    def write_file(self, target: TargetRef, relative_path: str, data: bytes) -> PublishedRef:
        validate_target_ref(target)
        _ensure_target_type(target, SourceType.SVN)
        safe_path = _normalize_relative_path(relative_path, field='svn target file')
        target_path = _join_target_path(target.path, safe_path)
        try:
            with tempfile.NamedTemporaryFile(delete=False) as file:
                file.write(data)
                tmp_path = Path(file.name)
            try:
                self._client(target).import_(tmp_path, target_path, message='', force=True)
            finally:
                tmp_path.unlink(missing_ok=True)
        except Exception as err:
            raise PublishError(f'svn import failed: {err}') from err
        return PublishedRef(target=target, relative_path=safe_path, source=published_source(target, safe_path))

    def ensure_root(self, target: TargetRef) -> TargetRef:
        validate_target_ref(target)
        _ensure_target_type(target, SourceType.SVN)
        try:
            self._client(target).mkdir(target.path, message='', parents=True, exist_ok=True)
        except Exception as err:
            raise PublishError(f'svn mkdir failed: {err}') from err
        return target

    def resolve_revision(self, target: TargetRef) -> TargetRef:
        validate_target_ref(target)
        _ensure_target_type(target, SourceType.SVN)
        try:
            info = self._client(target).info(target.path, revision=target.revision)
        except Exception as err:
            raise PublishError(f'svn info failed: {err}') from err
        return TargetRef(
            type=target.type,
            location=target.location,
            path=target.path,
            revision=info.commit_revision,
        )

    def _client(self, target: TargetRef):
        if target.location is None:
            raise PublishError('svn target requires location')
        return self._client_factory(target.location)

    @staticmethod
    def _default_client_factory(location: str) -> SvnClient:
        return SvnClient(location, check_exists=False)


class TargetRegistry:
    def __init__(self, adapters: dict[SourceType | str, TargetAdapter] | None = None):
        self._adapters: dict[SourceType, TargetAdapter] = {
            SourceType.LOCAL: LocalTargetAdapter(),
            SourceType.SVN: SvnTargetAdapter(),
        }
        if adapters:
            for target_type, adapter in adapters.items():
                self.register(target_type, adapter)

    def register(self, target_type: SourceType | str, adapter: TargetAdapter) -> None:
        self._adapters[SourceType(target_type)] = adapter

    def adapter_for(self, target: TargetRef) -> TargetAdapter:
        validate_target_ref(target)
        try:
            return self._adapters[target.type]
        except KeyError as err:
            raise PublishError(f'unsupported target type: {target.type}') from err

    def write_file(self, target: TargetRef, relative_path: str, data: bytes) -> PublishedRef:
        return self.adapter_for(target).write_file(target, relative_path, data)

    def ensure_root(self, target: TargetRef) -> TargetRef:
        return self.adapter_for(target).ensure_root(target)

    def resolve_revision(self, target: TargetRef) -> TargetRef:
        return self.adapter_for(target).resolve_revision(target)


def validate_target_ref(target: TargetRef) -> None:
    if target.type is SourceType.LOCAL:
        if target.location is not None or target.revision is not None:
            raise PublishError('local target must use only path')
        return
    _normalize_relative_path(target.path, field='svn target path')
    if target.location is None:
        raise PublishError('svn target requires location')
    if '@' in urlsplit(target.location).netloc:
        raise PublishError('svn target location must not contain userinfo')


def _ensure_target_type(target: TargetRef, expected_type: SourceType) -> None:
    if target.type is not expected_type:
        raise PublishError(f'expected {expected_type.value} target, got {target.type.value}')


def _safe_join(root: Path, relative_path: str) -> Path:
    root_resolved = root.resolve()
    path = PurePosixPath(relative_path)
    result = root.joinpath(*path.parts)
    try:
        result.resolve(strict=False).relative_to(root_resolved)
    except ValueError as err:
        raise PublishError(f'target path escapes target root: {relative_path}') from err
    return result


def _join_target_path(base_path: str, relative_path: str) -> str:
    base = base_path.replace('\\', '/').strip('/')
    if not base:
        return relative_path
    return f'{base}/{relative_path}'


def _normalize_relative_path(value: str, *, field: str) -> str:
    normalized = value.replace('\\', '/')
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
