from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from pathlib import Path, PurePosixPath
import re
from typing import Any

from calcchain_capabilities import AuthServiceProtocol, RuntimeCapabilities, SourceAdapter, SourceContext
from calcchain_capabilities.registrars import CapabilityKey, CapabilityOwner, CapabilityRecord
from calcchain_core.common.errors import SourceError
from calcchain_core.models import LocalSourceRef
from calcchain_core.models.common import LOCAL_SOURCE_TYPE, SourceType


_URL_USERINFO_RE = re.compile(r'([A-Za-z][A-Za-z0-9+.-]*://)([^/\s?#@]+@)([^/\s?#]+)')
_SECRET_ASSIGNMENT_RE = re.compile(r'(?i)\b(secret|token|password|passwd|api[_-]?key)=([^\s,;]+)')


class LocalSourceAdapter:
    def validate_config(self, ref: Mapping[str, Any], context: SourceContext) -> None:
        self._parse(ref)

    def validate_lock_ref(self, ref: Mapping[str, Any], context: SourceContext) -> None:
        self._parse(ref)

    def list_files(self, ref: Mapping[str, Any], context: SourceContext) -> list[str]:
        source = self._parse(ref)
        root = Path(source.path)
        if not root.is_dir():
            raise SourceError(f'local source is not a directory: {source.path}')
        return sorted(
            _normalize_relative_path(file.relative_to(root).as_posix(), field='local source file')
            for file in root.rglob('*')
            if file.is_file()
        )

    def read_file(self, ref: Mapping[str, Any], relative_path: str, context: SourceContext) -> bytes:
        source = self._parse(ref)
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

    def resolve_lock_ref(self, ref: Mapping[str, Any], context: SourceContext) -> dict[str, Any]:
        return self._parse(ref).to_dict()

    def is_versionable(self, ref: Mapping[str, Any], context: SourceContext) -> bool:
        self._parse(ref)
        return False

    def _parse(self, ref: Mapping[str, Any]) -> LocalSourceRef:
        try:
            return LocalSourceRef.from_dict(ref)
        except Exception as err:
            raise SourceError(str(err)) from err


class _RuntimeSourceAdapter:
    """Sanitizing decorator for source adapters."""

    def __init__(self, adapter: SourceAdapter, *, capability_id: str) -> None:
        self._adapter = adapter
        self._capability_id = capability_id

    def validate_config(self, ref: Mapping[str, Any], context: SourceContext) -> None:
        self._call(self._adapter.validate_config, ref, context)

    def resolve_lock_ref(self, ref: Mapping[str, Any], context: SourceContext) -> dict[str, Any]:
        return self._call(self._adapter.resolve_lock_ref, ref, context)

    def validate_lock_ref(self, ref: Mapping[str, Any], context: SourceContext) -> None:
        self._call(self._adapter.validate_lock_ref, ref, context)

    def list_files(self, ref: Mapping[str, Any], context: SourceContext) -> list[str]:
        self.validate_lock_ref(ref, context)
        return self._call(self._adapter.list_files, ref, context)

    def read_file(self, ref: Mapping[str, Any], relative_path: str, context: SourceContext) -> bytes:
        self.validate_lock_ref(ref, context)
        return self._call(self._adapter.read_file, ref, relative_path, context)

    def is_versionable(self, ref: Mapping[str, Any], context: SourceContext) -> bool:
        self.validate_lock_ref(ref, context)
        return self._call(self._adapter.is_versionable, ref, context)

    def _call[_T](self, method: Callable[..., _T], ref: Mapping[str, Any], *args: object) -> _T:
        try:
            return method(ref, *args)
        except Exception as err:
            operation = getattr(method, '__name__', 'operation')
            message = f'source capability {self._capability_id} {operation} failed: {err}'
            raise SourceError(sanitize_source_error_message(message, ref)) from err


SourceCapability = CapabilityRecord[SourceAdapter]


class SourceRegistry:
    """Registry for source capabilities."""

    def __init__(
        self,
        capabilities: Iterable[SourceCapability] | None = None,
        *,
        auth: AuthServiceProtocol | None = None,
    ) -> None:
        self._auth = auth
        self._entries: dict[str, SourceCapability] = {}
        self.register(_local_source_capability())
        if capabilities:
            for capability in capabilities:
                self.register(capability)

    @classmethod
    def from_runtime(
        cls,
        runtime: RuntimeCapabilities | None,
        *,
        auth: AuthServiceProtocol | None = None,
    ) -> SourceRegistry:
        registry = cls(auth=auth)
        if runtime is None:
            return registry
        for key, record in runtime.capabilities.items():
            if key.namespace != 'source':
                continue
            adapter = _record_adapter(record)
            registry.register(
                SourceCapability(
                    key=key,
                    adapter=adapter,
                    owner=_runtime_owner(record.owner, adapter),
                ),
            )
        return registry

    def register(
        self,
        capability: SourceCapability,
        *,
        override: bool = False,
    ) -> None:
        if capability.key.namespace != 'source':
            raise SourceError(f"source registry cannot register {capability.key.qualified_id!r}")

        capability_id = capability.capability_id
        if capability_id in self._entries and not override:
            existing = self._entries[capability_id]
            existing_owner = existing.owner_id or 'builtin'
            new_owner = capability.owner_id or 'builtin'
            raise SourceError(
                f"source type {capability_id!r} is already registered by "
                f"{existing_owner}, cannot register {new_owner}"
            )

        self._entries[capability_id] = SourceCapability(
            key=capability.key,
            owner=capability.owner,
            adapter=_RuntimeSourceAdapter(capability.adapter, capability_id=capability_id),
        )

    def capability_for(self, ref: Mapping[str, Any]) -> SourceCapability:
        capability_id = _ref_type(ref)
        try:
            return self._entries[capability_id]
        except KeyError as err:
            raise SourceError(f'unsupported source type: {capability_id}') from err

    def adapter_for(self, ref: Mapping[str, Any]) -> SourceAdapter:
        return self.capability_for(ref).adapter

    def context_for(self, ref: Mapping[str, Any]) -> SourceContext:
        capability = self.capability_for(ref)
        return SourceContext(
            owner=capability.owner,
            capability_id=capability.capability_id,
            auth=self._auth,
        )

    def validate_config(self, ref: Mapping[str, Any]) -> None:
        self.adapter_for(ref).validate_config(ref, self.context_for(ref))

    def resolve_lock_ref(self, ref: Mapping[str, Any]) -> dict[str, Any]:
        capability = self.capability_for(ref)
        context = self._context_for_capability(capability)
        resolved = capability.adapter.resolve_lock_ref(ref, context)
        return _with_owner_metadata(resolved, capability)

    def validate_lock_ref(self, ref: Mapping[str, Any]) -> None:
        self.adapter_for(ref).validate_lock_ref(ref, self.context_for(ref))

    def list_files(self, ref: Mapping[str, Any]) -> list[str]:
        return self.adapter_for(ref).list_files(ref, self.context_for(ref))

    def read_file(self, ref: Mapping[str, Any], relative_path: str) -> bytes:
        return self.adapter_for(ref).read_file(ref, relative_path, self.context_for(ref))

    def is_versionable(self, ref: Mapping[str, Any]) -> bool:
        return self.adapter_for(ref).is_versionable(ref, self.context_for(ref))

    def _context_for_capability(self, capability: SourceCapability) -> SourceContext:
        return SourceContext(
            owner=capability.owner,
            capability_id=capability.capability_id,
            auth=self._auth,
        )


def sanitize_source_error_message(message: str, ref: Mapping[str, Any] | None = None) -> str:
    sanitized = message
    if ref is not None:
        location = ref.get('location')
        if isinstance(location, str) and _URL_USERINFO_RE.search(location):
            sanitized = sanitized.replace(location, _URL_USERINFO_RE.sub(r'\1[redacted]@\3', location))
    sanitized = _URL_USERINFO_RE.sub(r'\1[redacted]@\3', sanitized)
    return _SECRET_ASSIGNMENT_RE.sub(r'\1=[redacted]', sanitized)


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


def _ref_type(ref: Mapping[str, Any]) -> str:
    value = ref.get('type')
    if isinstance(value, SourceType):
        return value.value
    if isinstance(value, str) and value:
        return value
    raise SourceError('source ref must define non-empty type')


def _local_source_capability() -> SourceCapability:
    return SourceCapability(
        key=CapabilityKey('source', LOCAL_SOURCE_TYPE),
        adapter=LocalSourceAdapter(),
    )


def _record_adapter(record: CapabilityRecord) -> SourceAdapter:
    adapter = getattr(record, 'adapter', None)
    if adapter is None:
        adapter = getattr(record, 'capability', None)
    if adapter is None:
        raise SourceError(f"source capability {record.key.id!r} has no adapter")
    return adapter


def _runtime_owner(owner: CapabilityOwner | str | None, adapter: SourceAdapter) -> CapabilityOwner | None:
    version = getattr(adapter, 'plugin_version', None)
    if owner is None:
        return None
    if isinstance(owner, CapabilityOwner):
        if owner.version is not None or version is None:
            return owner
        return CapabilityOwner(id=owner.id, version=version)
    return CapabilityOwner(id=owner, version=version)


def _with_owner_metadata(ref: Mapping[str, Any], capability: SourceCapability) -> dict[str, Any]:
    result = dict(ref)
    if capability.owner_id is not None:
        result['plugin'] = {'id': capability.owner_id, 'version': capability.owner_version or ''}
    return result


__all__ = [
    'LocalSourceAdapter',
    'SourceCapability',
    'SourceRegistry',
    'sanitize_source_error_message',
]
