from __future__ import annotations

from pathlib import Path, PurePosixPath
import re
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

from calcchain_core.errors import SourceError
from calcchain_core.models import SourceRef, SourceType
from svn.src.client import SvnClient

_URL_USERINFO_RE = re.compile(r'([A-Za-z][A-Za-z0-9+.-]*://)([^/\s?#@]+@)([^/\s?#]+)')


class SourceAdapter(Protocol):
    def list_files(self, source: SourceRef) -> list[str]:
        """Return source-relative file paths using POSIX separators."""

    def read_file(self, source: SourceRef, relative_path: str) -> bytes:
        """Read one source-relative file."""

    def resolve_revision(self, source: SourceRef) -> SourceRef:
        """Return the source with a concrete revision when the source supports revisions."""

    def is_versionable(self, source: SourceRef) -> bool:
        """Return whether the source has stable version identity."""


class LocalSourceAdapter:
    def list_files(self, source: SourceRef) -> list[str]:
        validate_source_ref(source)
        _ensure_source_type(source, SourceType.LOCAL)
        root = Path(source.path)
        if not root.is_dir():
            raise SourceError(f'local source is not a directory: {source.path}')
        return sorted(
            _normalize_relative_path(file.relative_to(root).as_posix(), field='local source file')
            for file in root.rglob('*')
            if file.is_file()
        )

    def read_file(self, source: SourceRef, relative_path: str) -> bytes:
        validate_source_ref(source)
        _ensure_source_type(source, SourceType.LOCAL)
        safe_path = _normalize_relative_path(relative_path, field='local source file')
        root = Path(source.path)
        path = root.joinpath(*PurePosixPath(safe_path).parts)
        try:
            path.resolve().relative_to(root.resolve())
        except ValueError as err:
            raise SourceError(f'local source path escapes source root: {relative_path}') from err
        if not path.is_file():
            raise SourceError(f'local source file not found: {relative_path}')
        return path.read_bytes()

    def resolve_revision(self, source: SourceRef) -> SourceRef:
        validate_source_ref(source)
        _ensure_source_type(source, SourceType.LOCAL)
        return source

    def is_versionable(self, source: SourceRef) -> bool:
        validate_source_ref(source)
        _ensure_source_type(source, SourceType.LOCAL)
        return False


class SvnSourceAdapter:
    def __init__(self, client_factory=None):
        self._client_factory = client_factory or self._default_client_factory

    def list_files(self, source: SourceRef) -> list[str]:
        validate_source_ref(source)
        _ensure_source_type(source, SourceType.SVN)
        try:
            client = self._client(source)
            tree = client.list(source.path, recursive=True, revision=source.revision)
        except Exception as err:
            raise _sanitized_source_error('svn list failed', source, err) from err
        return sorted(
            _normalize_relative_path(node.rel_path, field='svn source file')
            for node in tree.nodes
            if node.kind == 'file'
        )

    def read_file(self, source: SourceRef, relative_path: str) -> bytes:
        validate_source_ref(source)
        _ensure_source_type(source, SourceType.SVN)
        safe_path = _normalize_relative_path(relative_path, field='svn source file')
        source_path = _join_source_path(source.path, safe_path)
        try:
            data = self._client(source).cat(source_path, revision=source.revision, return_binary=True)
        except Exception as err:
            raise _sanitized_source_error('svn cat failed', source, err) from err
        if not isinstance(data, bytes):
            raise SourceError(f'svn cat returned text for file: {relative_path}')
        return data

    def resolve_revision(self, source: SourceRef) -> SourceRef:
        validate_source_ref(source)
        _ensure_source_type(source, SourceType.SVN)
        revision = source.revision
        try:
            client = self._client(source)
            info = client.info(source.path, revision=revision)
        except Exception as err:
            raise _sanitized_source_error('svn info failed', source, err) from err
        if revision == 'HEAD' or revision is None:
            revision = info.commit_revision
        elif isinstance(revision, str):
            revision = int(revision)
        return SourceRef(
            type=source.type,
            location=source.location,
            path=source.path,
            revision=revision,
        )

    def is_versionable(self, source: SourceRef) -> bool:
        validate_source_ref(source)
        _ensure_source_type(source, SourceType.SVN)
        return True

    def _client(self, source: SourceRef):
        if source.location is None:
            raise SourceError('svn source requires location')
        return self._client_factory(source.location)

    @staticmethod
    def _default_client_factory(location: str) -> SvnClient:
        return SvnClient(location, check_exists=False)


class SourceRegistry:
    def __init__(self, adapters: dict[SourceType | str, SourceAdapter] | None = None):
        self._adapters: dict[SourceType, SourceAdapter] = {
            SourceType.LOCAL: LocalSourceAdapter(),
            SourceType.SVN: SvnSourceAdapter(),
        }
        if adapters:
            for source_type, adapter in adapters.items():
                self.register(source_type, adapter)

    def register(self, source_type: SourceType | str, adapter: SourceAdapter) -> None:
        self._adapters[SourceType(source_type)] = adapter

    def adapter_for(self, source: SourceRef) -> SourceAdapter:
        validate_source_ref(source)
        try:
            return self._adapters[source.type]
        except KeyError as err:
            raise SourceError(f'unsupported source type: {source.type}') from err

    def list_files(self, source: SourceRef) -> list[str]:
        return self.adapter_for(source).list_files(source)

    def read_file(self, source: SourceRef, relative_path: str) -> bytes:
        return self.adapter_for(source).read_file(source, relative_path)

    def resolve_revision(self, source: SourceRef) -> SourceRef:
        return self.adapter_for(source).resolve_revision(source)

    def is_versionable(self, source: SourceRef) -> bool:
        return self.adapter_for(source).is_versionable(source)


def _ensure_source_type(source: SourceRef, expected_type: SourceType) -> None:
    if source.type is not expected_type:
        raise SourceError(f'expected {expected_type.value} source, got {source.type.value}')


def validate_source_ref(source: SourceRef) -> None:
    if source.type is not SourceType.SVN:
        return
    _normalize_relative_path(source.path, field='svn source path')
    _validate_svn_location(source.location)


def sanitize_source_error_message(message: str, source: SourceRef | None = None) -> str:
    sanitized = message
    if source is not None and source.location is not None:
        sanitized = sanitized.replace(source.location, _redact_location(source.location))
    return _URL_USERINFO_RE.sub(r'\1[redacted]@\3', sanitized)


def _validate_svn_location(location: str | None) -> None:
    if location is None:
        raise SourceError('svn source requires location')
    if '@' in urlsplit(location).netloc:
        raise SourceError('svn source location must not contain userinfo')


def _redact_location(location: str) -> str:
    parsed = urlsplit(location)
    if '@' not in parsed.netloc:
        return location
    host = parsed.netloc.rsplit('@', maxsplit=1)[-1]
    return urlunsplit((parsed.scheme, f'[redacted]@{host}', parsed.path, parsed.query, parsed.fragment))


def _sanitized_source_error(action: str, source: SourceRef, err: Exception) -> SourceError:
    return SourceError(sanitize_source_error_message(f'{action}: {err}', source))


def _join_source_path(base_path: str, relative_path: str) -> str:
    base = base_path.replace('\\', '/').strip('/')
    if not base:
        return relative_path
    return f'{base}/{relative_path}'


def _normalize_relative_path(value: str, *, field: str) -> str:
    normalized = value.replace('\\', '/')
    if normalized.startswith('/') or _has_windows_drive(normalized):
        raise SourceError(f'{field} must be relative: {value}')
    path = PurePosixPath(normalized)
    if '..' in path.parts:
        raise SourceError(f'{field} must not contain path traversal: {value}')
    result = path.as_posix()
    if result in {'', '.'}:
        raise SourceError(f'{field} must identify a file: {value}')
    return result


def _has_windows_drive(value: str) -> bool:
    return len(value) >= 2 and value[1] == ':' and value[0].isalpha()
