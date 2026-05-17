from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
import re
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

from calcchain_core.errors import SourceError
from calcchain_core.models import SourceRef, SourceType
from calcchain_core.plugin_runtime import PluginRefMetadata, SourceContext
from calcchain_core.plugins.manager import PluginRuntimeSet
from svn.client import SvnClient

_URL_USERINFO_RE = re.compile(r'([A-Za-z][A-Za-z0-9+.-]*://)([^/\s?#@]+@)([^/\s?#]+)')
_SECRET_ASSIGNMENT_RE = re.compile(r'(?i)\b(secret|token|password|passwd|api[_-]?key)=([^\s,;]+)')


class SourceAdapter(Protocol):
    def validate_config(self, source: SourceRef) -> None:
        """Валидирует конфиг, созданный пользователем."""

    def validate_lock_ref(self, source: SourceRef) -> None:
        """Валидирует lock файл"""

    def list_files(self, source: SourceRef) -> list[str]:
        """Возвращает список относительных путей файлов источника в формате POSIX."""

    def read_file(self, source: SourceRef, relative_path: str) -> bytes:
        """Читает файл источника по относительному пути."""

    def resolve_lock_ref(self, source: SourceRef) -> SourceRef:
        """Преобразует пользовательский конфиг в lock, убирая неоднозначности."""

    def is_versionable(self, source: SourceRef) -> bool:
        """Возвращает Turue, если источник версионируемый."""


class LocalSourceAdapter:
    def validate_config(self, source: SourceRef) -> None:
        validate_source_ref(source)
        _ensure_source_type(source, SourceType.LOCAL)

    def validate_lock_ref(self, source: SourceRef) -> None:
        validate_source_ref(source)
        _ensure_source_type(source, SourceType.LOCAL)

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

    def validate_config(self, source: SourceRef) -> None:
        validate_source_ref(source)
        _ensure_source_type(source, SourceType.SVN)

    def validate_lock_ref(self, source: SourceRef) -> None:
        validate_source_ref(source)
        _ensure_source_type(source, SourceType.SVN)

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

    def resolve_lock_ref(self, source: SourceRef) -> SourceRef:
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


@dataclass(frozen=True)
class RegisteredSourceCapability:
    adapter: SourceAdapter
    plugin_id: str | None = None
    plugin_version: str | None = None


class _RuntimeSourceAdapter:
    def __init__(self, adapter, *, capability_id: str, plugin_id: str | None, auth: object | None) -> None:
        self._adapter = adapter
        self._capability_id = capability_id
        self._plugin_id = plugin_id
        self._auth = auth

    def validate_config(self, source: SourceRef) -> None:
        self._call_plugin('validate_config', source, self._context('validate_config'))

    def validate_lock_ref(self, source: SourceRef) -> None:
        self._call_plugin('validate_lock_ref', source, self._context('validate_lock_ref'))

    def list_files(self, source: SourceRef) -> list[str]:
        self.validate_lock_ref(source)
        return self._call_plugin('list_files', source, self._context('list_files'))

    def read_file(self, source: SourceRef, relative_path: str) -> bytes:
        self.validate_lock_ref(source)
        return self._call_plugin('read_file', source, relative_path, self._context('read_file'))

    def resolve_lock_ref(self, source: SourceRef) -> SourceRef:
        resolved = self._call_plugin('resolve_lock_ref', source, self._context('resolve_lock_ref'))
        return SourceRef.from_dict(resolved, resolved_revision=True)

    def is_versionable(self, source: SourceRef) -> bool:
        self.validate_lock_ref(source)
        return self._call_plugin('is_versionable', source, self._context('is_versionable'))

    def _context(self, operation: str) -> SourceContext:
        return SourceContext(
            plugin_id=self._plugin_id,
            capability_id=self._capability_id,
            operation=operation,
            auth=self._auth,
        )

    def _call_plugin(self, operation: str, source: SourceRef, *args):
        try:
            return getattr(self._adapter, operation)(source.to_dict(), *args)
        except Exception as err:
            raise SourceError(_sanitize_plugin_error(f'plugin source {operation} failed: {err}', source)) from err


class SourceRegistry:
    '''Регистратор для SourceAdapters'''
    def __init__(self, adapters: dict[SourceType | str, SourceAdapter] | None = None):
        # По умолчанию зарегистрирвовать только local
        self.register(
            source_type=SourceType.LOCAL.value,
            adapter=LocalSourceAdapter,            
        )
        # Можно зарегистрировать готовые адаптеры
        if adapters:
            for source_type, adapter in adapters.items():
                self.register(source_type, adapter)

    @classmethod
    def from_runtime(
        cls,
        runtime: PluginRuntimeSet | None,
        *,
        auth: object | None = None,
    ) -> SourceRegistry:
        registry = cls()
        if runtime is None:
            return registry
        for key, record in runtime.capabilities.items():
            if key.namespace != 'source':
                continue
            registry.register(
                key.id,
                _RuntimeSourceAdapter(record.capability, capability_id=key.id, plugin_id=record.owner, auth=auth),
                plugin_id=record.owner,
                plugin_version=getattr(record.capability, 'plugin_version', None),
            )
        return registry

    def register(
        self,
        source_type: SourceType | str,
        adapter: SourceAdapter,
        *,
        plugin_id: str | None = None,
        plugin_version: str | None = None,
        override: bool = False,
    ) -> None:
        type_id = _type_id(source_type)

        # Если override запрещён и встретился повторный type_id поднять исключение
        if type_id in self._entries and not override:
            existing = self._entries[type_id]
            existing_owner = existing.plugin_id or 'builtin'
            new_owner = plugin_id or 'builtin'
            raise SourceError(
                f"source type {type_id!r} is already registered by "
                f"{existing_owner}, cannot register {new_owner}"
            )

        # Регистрация
        self._entries[_type_id(source_type)] = RegisteredSourceCapability(
            adapter,
            plugin_id=plugin_id,
            plugin_version=plugin_version,
        )

    def adapter_for(self, source: SourceRef) -> SourceAdapter:
        return self._entry_for(source).adapter

    def validate_config(self, source: SourceRef) -> None:
        entry = self._entry_for(source)
        entry.adapter.validate_config(source)

    def resolve_lock_ref(self, source: SourceRef) -> SourceRef:
        entry = self._entry_for(source)
        resolved = entry.adapter.resolve_lock_ref(source)
        return _with_plugin_metadata(resolved, entry)

    def validate_lock_ref(self, source: SourceRef) -> None:
        entry = self._entry_for(source)
        entry.adapter.validate_lock_ref(source)

    def _entry_for(self, source: SourceRef) -> RegisteredSourceCapability:
        validate_source_ref(source)
        try:
            return self._entries[_type_id(source.type)]
        except KeyError as err:
            raise SourceError(f'unsupported source type: {_type_id(source.type)}') from err

    def list_files(self, source: SourceRef) -> list[str]:
        return self.adapter_for(source).list_files(source)

    def read_file(self, source: SourceRef, relative_path: str) -> bytes:
        return self.adapter_for(source).read_file(source, relative_path)

    def is_versionable(self, source: SourceRef) -> bool:
        return self.adapter_for(source).is_versionable(source)


def _ensure_source_type(source: SourceRef, expected_type: SourceType) -> None:
    if _type_id(source.type) != expected_type.value:
        raise SourceError(f'expected {expected_type.value} source, got {_type_id(source.type)}')


def validate_source_ref(source: SourceRef) -> None:
    if _type_id(source.type) != SourceType.SVN.value:
        return
    _normalize_relative_path(source.path, field='svn source path')
    _validate_svn_location(source.location)


def sanitize_source_error_message(message: str, source: SourceRef | None = None) -> str:
    sanitized = message
    if source is not None and source.location is not None:
        sanitized = sanitized.replace(source.location, _redact_location(source.location))
    sanitized = _URL_USERINFO_RE.sub(r'\1[redacted]@\3', sanitized)
    return _SECRET_ASSIGNMENT_RE.sub(r'\1=[redacted]', sanitized)


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


def _sanitize_plugin_error(message: str, source: SourceRef) -> str:
    return sanitize_source_error_message(message, source)


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


def _type_id(value: SourceType | str) -> str:
    if isinstance(value, SourceType):
        return value.value
    return value


def _with_plugin_metadata(source: SourceRef, entry: RegisteredSourceCapability) -> SourceRef:
    if entry.plugin_id is None:
        return source
    return replace(source, plugin=PluginRefMetadata(id=entry.plugin_id, version=entry.plugin_version or ''))
