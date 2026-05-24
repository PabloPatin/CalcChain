from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import re
from typing import Any

from ..capabilities.runtime import (
    CapabilityKey,
    CapabilityOwner,
    CapabilityRecord,
    RuntimeCapabilities,
    SourceAdapter,
    SourceContext,
    ResolvedCredentials,
)
from ..common.errors import SourceError
from ..secrets import NoSecretsResolver, SecretsResolver
from .ref import ExternalRef, RefCredentials


SourceCredentials = RefCredentials
SourceRef = ExternalRef

LOCAL_SOURCE_TYPE = 'local'

_URL_USERINFO_RE = re.compile(r'([A-Za-z][A-Za-z0-9+.-]*://)([^/\s?#@]+@)([^/\s?#]+)')
_SECRET_ASSIGNMENT_RE = re.compile(r'(?i)\b(secret|token|password|passwd|api[_-]?key)=([^\s,;]+)')


class LocalSourceAdapter:
    def validate_config(self, ref: Mapping[str, Any], context: SourceContext) -> None:
        _parse_local_source(ref)

    def resolve_lock_ref(self, ref: Mapping[str, Any], context: SourceContext) -> dict[str, Any]:
        return _parse_local_source(ref)

    def validate_lock_ref(self, ref: Mapping[str, Any], context: SourceContext) -> None:
        _parse_local_source(ref)

    def list_files(self, ref: Mapping[str, Any], context: SourceContext) -> list[str]:
        source = _parse_local_source(ref)
        root = Path(source['path'])
        if not root.is_dir():
            raise SourceError(f'local source is not a directory: {source["path"]}')
        return sorted(
            _normalize_relative_path(file.relative_to(root).as_posix(), field='local source file')
            for file in root.rglob('*')
            if file.is_file()
        )

    def read_file(self, ref: Mapping[str, Any], relative_path: str, context: SourceContext) -> bytes:
        source = _parse_local_source(ref)
        safe_path = _normalize_relative_path(relative_path, field='local source file')
        root = Path(source['path'])
        path = root.joinpath(*PurePosixPath(safe_path).parts)
        try:
            path.resolve(strict=False).relative_to(root.resolve(strict=False))
        except ValueError as err:
            raise SourceError(f'local source path escapes source root: {relative_path}') from err
        if not path.is_file():
            raise SourceError(f'local source file not found: {relative_path}')
        return path.read_bytes()

    def is_versionable(self, ref: Mapping[str, Any], context: SourceContext) -> bool:
        _parse_local_source(ref)
        return False


class _CheckedSourceAdapter:
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

    def _call(self, method: Callable[..., Any], ref: Mapping[str, Any], *args: object):
        try:
            return method(ref, *args)
        except Exception as err:
            operation = getattr(method, '__name__', 'operation')
            message = f'source capability {self._capability_id} {operation} failed: {err}'
            raise SourceError(sanitize_source_error_message(message, ref)) from err


@dataclass(frozen=True)
class SourceCapability:
    key: CapabilityKey
    adapter: SourceAdapter
    owner: CapabilityOwner | None = None

    @property
    def capability_id(self) -> str:
        return self.key.id

    @property
    def owner_id(self) -> str | None:
        return self.owner.id if self.owner is not None else None

    @property
    def owner_version(self) -> str | None:
        return self.owner.version if self.owner is not None else None


class SourceRegistry:
    def __init__(
        self,
        capabilities: Iterable[SourceCapability] | None = None,
        *,
        secrets_resolver: SecretsResolver | None = None,
    ) -> None:
        self._secrets_resolver = secrets_resolver or NoSecretsResolver()
        self._entries: dict[str, SourceCapability] = {}
        self.register(_local_source_capability())
        for capability in capabilities or []:
            self.register(capability)

    @classmethod
    def from_runtime(
        cls,
        runtime: RuntimeCapabilities | None = None,
        *,
        secrets_resolver: SecretsResolver | None = None,
    ) -> 'SourceRegistry':
        registry = cls(secrets_resolver=secrets_resolver)
        if runtime is None:
            return registry
        for key, record in runtime.capabilities.items():
            if _capability_namespace(key) != 'source':
                continue
            capability_id = _capability_id(key)
            adapter = _record_adapter(record, capability_id=capability_id)
            registry.register(
                SourceCapability(
                    key=CapabilityKey('source', capability_id),
                    adapter=adapter,
                    owner=_runtime_owner(_record_owner(record), adapter),
                ),
            )
        return registry

    def register(self, capability: SourceCapability, *, override: bool = False) -> None:
        if capability.key.namespace != 'source':
            raise SourceError(f"source registry cannot register {capability.key.qualified_id!r}")
        adapter = _validate_source_adapter(capability.capability_id, capability.adapter)
        if capability.capability_id in self._entries and not override:
            existing = self._entries[capability.capability_id]
            existing_owner = existing.owner_id or 'builtin'
            new_owner = capability.owner_id or 'builtin'
            raise SourceError(
                f"source type {capability.capability_id!r} is already registered by "
                f'{existing_owner}, cannot register {new_owner}',
            )
        self._entries[capability.capability_id] = SourceCapability(
            key=capability.key,
            owner=capability.owner,
            adapter=_CheckedSourceAdapter(adapter, capability_id=capability.capability_id),
        )

    def capability_for(self, source: SourceRef) -> SourceCapability:
        capability_id = _ref_type(source.data)
        try:
            return self._entries[capability_id]
        except KeyError as err:
            raise SourceError(f'unsupported source type: {capability_id}') from err

    def adapter_for(self, source: SourceRef) -> SourceAdapter:
        return self.capability_for(source).adapter

    def context_for(self, source: SourceRef) -> SourceContext:
        capability = self.capability_for(source)
        return self._context_for_capability(capability, source)

    def validate_config(self, source: SourceRef) -> None:
        self.adapter_for(source).validate_config(source.data, self.context_for(source))

    def resolve_lock_ref(self, source: SourceRef) -> SourceRef:
        capability = self.capability_for(source)
        context = self._context_for_capability(capability, source)
        resolved = capability.adapter.resolve_lock_ref(source.data, context)
        resolved_ref = SourceRef.from_dict(resolved)
        if resolved_ref.credentials is not None:
            return resolved_ref
        return SourceRef(data=resolved_ref.data, credentials=source.credentials)

    def validate_lock_ref(self, source: SourceRef) -> None:
        self.adapter_for(source).validate_lock_ref(source.data, self.context_for(source))

    def list_files(self, source: SourceRef) -> list[str]:
        return self.adapter_for(source).list_files(source.data, self.context_for(source))

    def read_file(self, source: SourceRef, path: str) -> bytes:
        return self.adapter_for(source).read_file(source.data, path, self.context_for(source))

    def is_versionable(self, source: SourceRef) -> bool:
        return self.adapter_for(source).is_versionable(source.data, self.context_for(source))

    def _context_for_capability(self, capability: SourceCapability, source: SourceRef) -> SourceContext:
        return SourceContext(
            owner=capability.owner,
            capability_id=capability.capability_id,
            credentials=_resolve_credentials(source, self._secrets_resolver, capability_id=capability.capability_id),
        )


def sanitize_source_error_message(message: str, ref: Mapping[str, Any] | None = None) -> str:
    sanitized = message
    if ref is not None:
        location = ref.get('location')
        if isinstance(location, str) and _URL_USERINFO_RE.search(location):
            sanitized = sanitized.replace(location, _URL_USERINFO_RE.sub(r'\1[redacted]@\3', location))
    sanitized = _URL_USERINFO_RE.sub(r'\1[redacted]@\3', sanitized)
    return _SECRET_ASSIGNMENT_RE.sub(r'\1=[redacted]', sanitized)


def _resolve_credentials(
    source: SourceRef,
    secrets_resolver: SecretsResolver,
    *,
    capability_id: str,
) -> ResolvedCredentials:
    credentials = source.credentials
    if credentials is None:
        return ResolvedCredentials()
    secrets = {
        name: secrets_resolver.resolve(
            secret_key,
            context={'kind': 'source.credentials', 'source_type': capability_id, 'name': name},
        )
        for name, secret_key in credentials.secrets.items()
    }
    return ResolvedCredentials(public=credentials.public, secrets=secrets)


def _parse_local_source(ref: Mapping[str, Any]) -> dict[str, Any]:
    if _ref_type(ref) != LOCAL_SOURCE_TYPE:
        raise SourceError(f'local source adapter received unsupported source type: {_ref_type(ref)}')
    path = ref.get('path')
    if not isinstance(path, str) or not path:
        raise SourceError('local source must define non-empty path')
    return {'type': LOCAL_SOURCE_TYPE, 'path': path}


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
    if isinstance(value, str) and value:
        return value
    raise SourceError('source ref must define non-empty type')


def _local_source_capability() -> SourceCapability:
    return SourceCapability(
        key=CapabilityKey('source', LOCAL_SOURCE_TYPE),
        adapter=LocalSourceAdapter(),
    )


def _capability_namespace(key) -> str | None:
    namespace = getattr(key, 'namespace', None)
    return getattr(namespace, 'value', namespace)


def _capability_id(key) -> str:
    capability_id = getattr(key, 'id', None)
    if not isinstance(capability_id, str) or not capability_id:
        raise SourceError('source capability key must have a non-empty id')
    return capability_id


def _record_adapter(record, *, capability_id: str) -> SourceAdapter:
    adapter = getattr(record, 'adapter', None)
    if adapter is None:
        adapter = getattr(record, 'capability', None)
    if adapter is None:
        raise SourceError(f"source capability {capability_id!r} has no adapter")
    return _validate_source_adapter(capability_id, adapter)


def _record_owner(record) -> CapabilityOwner | str | None:
    owner = getattr(record, 'owner', None)
    if owner is not None:
        return owner
    owner_id = getattr(record, 'owner_id', None)
    if isinstance(owner_id, str) and owner_id:
        return owner_id
    return None


def _runtime_owner(owner: CapabilityOwner | str | None, adapter: SourceAdapter) -> CapabilityOwner | None:
    version = getattr(adapter, 'capability_version', None)
    if owner is None:
        return None
    if isinstance(owner, CapabilityOwner):
        if owner.version is not None or version is None:
            return owner
        return CapabilityOwner(id=owner.id, version=version)
    return CapabilityOwner(id=owner, version=version)


def _validate_source_adapter(capability_id: str, adapter: object) -> SourceAdapter:
    if not isinstance(adapter, SourceAdapter):
        raise SourceError(f"source capability {capability_id!r} must implement SourceAdapter")
    return adapter


__all__ = [
    'LOCAL_SOURCE_TYPE',
    'LocalSourceAdapter',
    'SourceCapability',
    'SourceCredentials',
    'SourceRef',
    'SourceRegistry',
    'sanitize_source_error_message',
]
