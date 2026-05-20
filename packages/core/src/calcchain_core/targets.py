from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
import re
from typing import Protocol

from calcchain_core.artifacts import published_source
from calcchain_core.errors import PublishError
from calcchain_core.models import SourceRef, SourceType, TargetRef
from calcchain_capabilities import PluginRefMetadata, TargetContext
from calcchain_capabilities import PluginRuntimeSet

_URL_USERINFO_RE = re.compile(r'([A-Za-z][A-Za-z0-9+.-]*://)([^/\s?#@]+@)([^/\s?#]+)')
_SECRET_ASSIGNMENT_RE = re.compile(r'(?i)\b(secret|token|password|passwd|api[_-]?key)=([^\s,;]+)')
_SENSITIVE_EXTRA_KEYS = frozenset({'secret', 'token', 'password', 'passwd', 'api_key', 'apikey', 'api-key'})


@dataclass(frozen=True)
class PublishedRef:
    target: TargetRef
    relative_path: str
    source: SourceRef


class TargetAdapter(Protocol):
    def validate_config(self, target: TargetRef) -> None:
        """Validate an unresolved target config before lock resolution."""

    def validate_lock_ref(self, target: TargetRef) -> None:
        """Validate a locked target ref before writes."""

    def write_file(self, target: TargetRef, relative_path: str, data: bytes) -> PublishedRef:
        """Write data under target-relative path and return a published source ref."""

    def ensure_root(self, target: TargetRef) -> TargetRef:
        """Ensure target root exists and return the normalized target."""

    def resolve_revision(self, target: TargetRef) -> TargetRef:
        """Return the target with concrete revision when the target supports revisions."""


class LocalTargetAdapter:
    def validate_config(self, target: TargetRef) -> None:
        validate_target_ref(target)
        _ensure_target_type(target, SourceType.LOCAL)

    def validate_lock_ref(self, target: TargetRef) -> None:
        validate_target_ref(target)
        _ensure_target_type(target, SourceType.LOCAL)

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


@dataclass(frozen=True)
class RegisteredTargetCapability:
    adapter: TargetAdapter
    plugin_id: str | None = None
    plugin_version: str | None = None


class _RuntimeTargetAdapter:
    def __init__(self, adapter, *, capability_id: str, plugin_id: str | None, auth: object | None) -> None:
        self._adapter = adapter
        self._capability_id = capability_id
        self._plugin_id = plugin_id
        self._auth = auth

    def write_file(self, target: TargetRef, relative_path: str, data: bytes) -> PublishedRef:
        self.validate_lock_ref(target)
        published = self._call_plugin('write_file', target, relative_path, data, self._context('write_file'))
        if isinstance(published, PublishedRef):
            return published
        return PublishedRef(
            target=target,
            relative_path=relative_path,
            source=SourceRef.from_dict(published.ref),
        )

    def ensure_root(self, target: TargetRef) -> TargetRef:
        self.validate_lock_ref(target)
        ensured = self._call_plugin('ensure_root', target, self._context('ensure_root'))
        return TargetRef.from_dict(ensured, resolved_revision=target.revision is not None)

    def resolve_revision(self, target: TargetRef) -> TargetRef:
        resolved = self._call_plugin('resolve_lock_ref', target, self._context('resolve_lock_ref'))
        return TargetRef.from_dict(resolved, resolved_revision=True)

    def validate_config(self, target: TargetRef) -> None:
        self._call_plugin('validate_config', target, self._context('validate_config'))

    def validate_lock_ref(self, target: TargetRef) -> None:
        self._call_plugin('validate_lock_ref', target, self._context('validate_lock_ref'))

    def _context(self, operation: str) -> TargetContext:
        return TargetContext(
            plugin_id=self._plugin_id,
            capability_id=self._capability_id,
            operation=operation,
            auth=self._auth,
        )

    def _call_plugin(self, operation: str, target: TargetRef, *args):
        try:
            return getattr(self._adapter, operation)(target.to_dict(), *args)
        except Exception as err:
            raise PublishError(sanitize_target_error_message(f'plugin target {operation} failed: {err}', target)) from err


class TargetRegistry:
    def __init__(self, adapters: dict[SourceType | str, TargetAdapter] | None = None):
        self._entries: dict[str, RegisteredTargetCapability] = {
            SourceType.LOCAL.value: RegisteredTargetCapability(LocalTargetAdapter()),
        }
        if adapters:
            for target_type, adapter in adapters.items():
                self.register(target_type, adapter)

    @classmethod
    def from_runtime(
        cls,
        runtime: PluginRuntimeSet | None,
        *,
        auth: object | None = None,
    ) -> TargetRegistry:
        registry = cls()
        if runtime is None:
            return registry
        for key, record in runtime.capabilities.items():
            if key.namespace != 'target':
                continue
            if key.id in registry._entries:
                continue
            registry.register(
                key.id,
                _RuntimeTargetAdapter(record.capability, capability_id=key.id, plugin_id=record.owner, auth=auth),
                plugin_id=record.owner,
                plugin_version=getattr(record.capability, 'plugin_version', None),
            )
        return registry

    def register(
        self,
        target_type: SourceType | str,
        adapter: TargetAdapter,
        *,
        plugin_id: str | None = None,
        plugin_version: str | None = None,
    ) -> None:
        self._entries[_type_id(target_type)] = RegisteredTargetCapability(
            adapter,
            plugin_id=plugin_id,
            plugin_version=plugin_version,
        )

    def adapter_for(self, target: TargetRef) -> TargetAdapter:
        return self._entry_for(target).adapter

    def validate_config(self, target: TargetRef) -> None:
        entry = self._entry_for(target)
        _call_optional(entry.adapter, 'validate_config', target)

    def resolve_lock_ref(self, target: TargetRef) -> TargetRef:
        entry = self._entry_for(target)
        resolved = entry.adapter.resolve_revision(target)
        return _with_plugin_metadata(resolved, entry)

    def validate_lock_ref(self, target: TargetRef) -> None:
        entry = self._entry_for(target)
        _call_optional(entry.adapter, 'validate_lock_ref', target)

    def _entry_for(self, target: TargetRef) -> RegisteredTargetCapability:
        validate_target_ref(target)
        try:
            return self._entries[_type_id(target.type)]
        except KeyError as err:
            raise PublishError(f'unsupported target type: {_type_id(target.type)}') from err

    def write_file(self, target: TargetRef, relative_path: str, data: bytes) -> PublishedRef:
        return self.adapter_for(target).write_file(target, relative_path, data)

    def ensure_root(self, target: TargetRef) -> TargetRef:
        return self.adapter_for(target).ensure_root(target)

    def resolve_revision(self, target: TargetRef) -> TargetRef:
        self.validate_config(target)
        return self.resolve_lock_ref(target)


def sanitize_target_error_message(message: str, target: TargetRef | None = None) -> str:
    sanitized = message
    if target is not None and target.location is not None and _URL_USERINFO_RE.search(target.location):
        sanitized = sanitized.replace(target.location, _URL_USERINFO_RE.sub(r'\1[redacted]@\3', target.location))
    if target is not None:
        sanitized = _redact_sensitive_extra_values(sanitized, target)
    sanitized = _URL_USERINFO_RE.sub(r'\1[redacted]@\3', sanitized)
    return _SECRET_ASSIGNMENT_RE.sub(r'\1=[redacted]', sanitized)


def validate_target_ref(target: TargetRef) -> None:
    if _type_id(target.type) == SourceType.LOCAL.value:
        if target.location is not None or target.revision is not None:
            raise PublishError('local target must use only path')
    return None


def _ensure_target_type(target: TargetRef, expected_type: SourceType) -> None:
    if _type_id(target.type) != expected_type.value:
        raise PublishError(f'expected {expected_type.value} target, got {_type_id(target.type)}')


def _redact_sensitive_extra_values(message: str, target: TargetRef) -> str:
    sanitized = message
    for key, value in target.extra.items():
        if _sensitive_key(key) and isinstance(value, str) and value:
            sanitized = sanitized.replace(value, '[redacted]')
    return sanitized


def _sensitive_key(key: str) -> bool:
    normalized = key.lower().replace('-', '_')
    return normalized in _SENSITIVE_EXTRA_KEYS


def _safe_join(root: Path, relative_path: str) -> Path:
    root_resolved = root.resolve()
    path = PurePosixPath(relative_path)
    result = root.joinpath(*path.parts)
    try:
        result.resolve(strict=False).relative_to(root_resolved)
    except ValueError as err:
        raise PublishError(f'target path escapes target root: {relative_path}') from err
    return result


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


def _type_id(value: SourceType | str) -> str:
    if isinstance(value, SourceType):
        return value.value
    return value


def _call_optional(adapter: TargetAdapter, method_name: str, target: TargetRef) -> None:
    method = getattr(adapter, method_name, None)
    if method is not None:
        method(target)


def _with_plugin_metadata(target: TargetRef, entry: RegisteredTargetCapability) -> TargetRef:
    if entry.plugin_id is None:
        return target
    return replace(target, plugin=PluginRefMetadata(id=entry.plugin_id, version=entry.plugin_version or ''))
