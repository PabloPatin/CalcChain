from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import re
from typing import Any

from ..capabilities.runtime import (
    CapabilityKey,
    CapabilityOwner,
    RuntimeCapabilities,
    TargetAdapter,
    TargetContext,
    ResolvedCredentials,
)
from ..common.errors import PublishError
from ..io.source import LOCAL_SOURCE_TYPE, SourceRef
from ..secrets import NoSecretsResolver, SecretsResolver
from .ref import ExternalRef, RefCredentials


TargetCredentials = RefCredentials
TargetRef = ExternalRef

LOCAL_TARGET_TYPE = 'local'

_URL_USERINFO_RE = re.compile(r'([A-Za-z][A-Za-z0-9+.-]*://)([^/\s?#@]+@)([^/\s?#]+)')
_SECRET_ASSIGNMENT_RE = re.compile(r'(?i)\b(secret|token|password|passwd|api[_-]?key)=([^\s,;]+)')


@dataclass(frozen=True)
class PublishedRef:
    source: SourceRef
    target: TargetRef | None = None
    relative_path: str = ''


class LocalTargetAdapter:
    def validate_config(self, ref: Mapping[str, Any], context: TargetContext) -> None:
        _parse_local_target(ref)

    def resolve_lock_ref(self, ref: Mapping[str, Any], context: TargetContext) -> dict[str, Any]:
        return _parse_local_target(ref)

    def validate_lock_ref(self, ref: Mapping[str, Any], context: TargetContext) -> None:
        _parse_local_target(ref)

    def ensure_root(self, ref: Mapping[str, Any], context: TargetContext) -> dict[str, Any]:
        target = _parse_local_target(ref)
        Path(target['path']).mkdir(parents=True, exist_ok=True)
        return target

    def write_file(
        self,
        ref: Mapping[str, Any],
        relative_path: str,
        data: bytes,
        context: TargetContext,
    ) -> Mapping[str, Any]:
        target = _parse_local_target(ref)
        safe_path = _normalize_relative_path(relative_path, field='local target file')
        destination = _safe_join(Path(target['path']), safe_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        return {
            'source': {
                'type': LOCAL_SOURCE_TYPE,
                'path': str(destination),
            },
            'relative_path': safe_path,
        }

    def is_versionable(self, ref: Mapping[str, Any], context: TargetContext) -> bool:
        _parse_local_target(ref)
        return False


class _CheckedTargetAdapter:
    def __init__(self, adapter: TargetAdapter, *, capability_id: str) -> None:
        self._adapter = adapter
        self._capability_id = capability_id

    def validate_config(self, ref: Mapping[str, Any], context: TargetContext) -> None:
        self._call(self._adapter.validate_config, ref, context)

    def resolve_lock_ref(self, ref: Mapping[str, Any], context: TargetContext) -> dict[str, Any]:
        return self._call(self._adapter.resolve_lock_ref, ref, context)

    def validate_lock_ref(self, ref: Mapping[str, Any], context: TargetContext) -> None:
        self._call(self._adapter.validate_lock_ref, ref, context)

    def ensure_root(self, ref: Mapping[str, Any], context: TargetContext) -> dict[str, Any]:
        self.validate_lock_ref(ref, context)
        return self._call(self._adapter.ensure_root, ref, context)

    def write_file(
        self,
        ref: Mapping[str, Any],
        relative_path: str,
        data: bytes,
        context: TargetContext,
    ) -> Mapping[str, Any]:
        self.validate_lock_ref(ref, context)
        return self._call(self._adapter.write_file, ref, relative_path, data, context)

    def is_versionable(self, ref: Mapping[str, Any], context: TargetContext) -> bool:
        self.validate_lock_ref(ref, context)
        return self._call(self._adapter.is_versionable, ref, context)

    def _call(self, method: Callable[..., Any], ref: Mapping[str, Any], *args: object):
        try:
            return method(ref, *args)
        except Exception as err:
            operation = getattr(method, '__name__', 'operation')
            message = f'target capability {self._capability_id} {operation} failed: {err}'
            raise PublishError(sanitize_target_error_message(message, ref)) from err


@dataclass(frozen=True)
class TargetCapability:
    key: CapabilityKey
    adapter: TargetAdapter
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


class TargetRegistry:
    def __init__(
        self,
        capabilities: Iterable[TargetCapability] | None = None,
        *,
        secrets_resolver: SecretsResolver | None = None,
    ) -> None:
        self._secrets_resolver = secrets_resolver or NoSecretsResolver()
        self._entries: dict[str, TargetCapability] = {}
        self.register(_local_target_capability())
        for capability in capabilities or []:
            self.register(capability)

    @classmethod
    def from_runtime(
        cls,
        runtime: RuntimeCapabilities | None = None,
        *,
        secrets_resolver: SecretsResolver | None = None,
    ) -> 'TargetRegistry':
        registry = cls(secrets_resolver=secrets_resolver)
        if runtime is None:
            return registry
        for key, record in runtime.capabilities.items():
            if _capability_namespace(key) != 'target':
                continue
            capability_id = _capability_id(key)
            adapter = _record_adapter(record, capability_id=capability_id)
            registry.register(
                TargetCapability(
                    key=CapabilityKey('target', capability_id),
                    adapter=adapter,
                    owner=_runtime_owner(_record_owner(record), adapter),
                ),
            )
        return registry

    def register(self, capability: TargetCapability, *, override: bool = False) -> None:
        if capability.key.namespace != 'target':
            raise PublishError(f"target registry cannot register {capability.key.qualified_id!r}")
        adapter = _validate_target_adapter(capability.capability_id, capability.adapter)
        if capability.capability_id in self._entries and not override:
            existing = self._entries[capability.capability_id]
            existing_owner = existing.owner_id or 'builtin'
            new_owner = capability.owner_id or 'builtin'
            raise PublishError(
                f"target type {capability.capability_id!r} is already registered by "
                f'{existing_owner}, cannot register {new_owner}',
            )
        self._entries[capability.capability_id] = TargetCapability(
            key=capability.key,
            owner=capability.owner,
            adapter=_CheckedTargetAdapter(adapter, capability_id=capability.capability_id),
        )

    def capability_for(self, target: TargetRef) -> TargetCapability:
        capability_id = _ref_type(target.data)
        try:
            return self._entries[capability_id]
        except KeyError as err:
            raise PublishError(f'unsupported target type: {capability_id}') from err

    def adapter_for(self, target: TargetRef) -> TargetAdapter:
        return self.capability_for(target).adapter

    def context_for(self, target: TargetRef) -> TargetContext:
        capability = self.capability_for(target)
        return self._context_for_capability(capability, target)

    def validate_config(self, target: TargetRef) -> None:
        self.adapter_for(target).validate_config(target.data, self.context_for(target))

    def resolve_lock_ref(self, target: TargetRef) -> TargetRef:
        capability = self.capability_for(target)
        context = self._context_for_capability(capability, target)
        resolved = capability.adapter.resolve_lock_ref(target.data, context)
        resolved_ref = TargetRef.from_dict(resolved)
        if resolved_ref.credentials is not None:
            return resolved_ref
        return TargetRef(data=resolved_ref.data, credentials=target.credentials)

    def validate_lock_ref(self, target: TargetRef) -> None:
        self.adapter_for(target).validate_lock_ref(target.data, self.context_for(target))

    def ensure_root(self, target: TargetRef) -> TargetRef:
        resolved = self.adapter_for(target).ensure_root(target.data, self.context_for(target))
        resolved_ref = TargetRef.from_dict(resolved)
        if resolved_ref.credentials is not None:
            return resolved_ref
        return TargetRef(data=resolved_ref.data, credentials=target.credentials)

    def write_file(self, target: TargetRef, path: str, data: bytes) -> PublishedRef:
        published = self.adapter_for(target).write_file(target.data, path, data, self.context_for(target))
        return _published_ref_from_result(target, path, published)

    def is_versionable(self, target: TargetRef) -> bool:
        return self.adapter_for(target).is_versionable(target.data, self.context_for(target))

    def _context_for_capability(self, capability: TargetCapability, target: TargetRef) -> TargetContext:
        return TargetContext(
            owner=capability.owner,
            capability_id=capability.capability_id,
            credentials=_resolve_credentials(target, self._secrets_resolver, capability_id=capability.capability_id),
        )


def sanitize_target_error_message(message: str, ref: Mapping[str, Any] | None = None) -> str:
    sanitized = message
    if ref is not None:
        location = ref.get('location')
        if isinstance(location, str) and _URL_USERINFO_RE.search(location):
            sanitized = sanitized.replace(location, _URL_USERINFO_RE.sub(r'\1[redacted]@\3', location))
        for key, value in ref.items():
            if _sensitive_key(str(key)) and isinstance(value, str) and value:
                sanitized = sanitized.replace(value, '[redacted]')
    sanitized = _URL_USERINFO_RE.sub(r'\1[redacted]@\3', sanitized)
    return _SECRET_ASSIGNMENT_RE.sub(r'\1=[redacted]', sanitized)


def _published_ref_from_result(target: TargetRef, path: str, value: object) -> PublishedRef:
    if isinstance(value, PublishedRef):
        return value
    if not isinstance(value, Mapping):
        raise PublishError('target write_file must return PublishedRef or mapping')
    source_data = value.get('source')
    if source_data is None:
        source_data = value.get('ref')
    if not isinstance(source_data, Mapping):
        raise PublishError('target write_file result must define source')
    relative_path = value.get('relative_path')
    if relative_path is not None and not isinstance(relative_path, str):
        raise PublishError('target write_file relative_path must be a string')
    return PublishedRef(
        source=SourceRef.from_dict(dict(source_data)),
        target=target,
        relative_path=relative_path or path,
    )


def _resolve_credentials(
    target: TargetRef,
    secrets_resolver: SecretsResolver,
    *,
    capability_id: str,
) -> ResolvedCredentials:
    credentials = target.credentials
    if credentials is None:
        return ResolvedCredentials()
    secrets = {
        name: secrets_resolver.resolve(
            secret_key,
            context={'kind': 'target.credentials', 'target_type': capability_id, 'name': name},
        )
        for name, secret_key in credentials.secrets.items()
    }
    return ResolvedCredentials(public=credentials.public, secrets=secrets)


def _parse_local_target(ref: Mapping[str, Any]) -> dict[str, Any]:
    if _ref_type(ref) != LOCAL_TARGET_TYPE:
        raise PublishError(f'local target adapter received unsupported target type: {_ref_type(ref)}')
    path = ref.get('path')
    if not isinstance(path, str) or not path:
        raise PublishError('local target must define non-empty path')
    return {'type': LOCAL_TARGET_TYPE, 'path': path}


def _safe_join(root: Path, relative_path: str) -> Path:
    root_resolved = root.resolve(strict=False)
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


def _ref_type(ref: Mapping[str, Any]) -> str:
    value = ref.get('type')
    if isinstance(value, str) and value:
        return value
    raise PublishError('target ref must define non-empty type')


def _local_target_capability() -> TargetCapability:
    return TargetCapability(
        key=CapabilityKey('target', LOCAL_TARGET_TYPE),
        adapter=LocalTargetAdapter(),
    )


def _capability_namespace(key) -> str | None:
    namespace = getattr(key, 'namespace', None)
    return getattr(namespace, 'value', namespace)


def _capability_id(key) -> str:
    capability_id = getattr(key, 'id', None)
    if not isinstance(capability_id, str) or not capability_id:
        raise PublishError('target capability key must have a non-empty id')
    return capability_id


def _record_adapter(record, *, capability_id: str) -> TargetAdapter:
    adapter = getattr(record, 'adapter', None)
    if adapter is None:
        adapter = getattr(record, 'capability', None)
    if adapter is None:
        raise PublishError(f"target capability {capability_id!r} has no adapter")
    return _validate_target_adapter(capability_id, adapter)


def _record_owner(record) -> CapabilityOwner | str | None:
    owner = getattr(record, 'owner', None)
    if owner is not None:
        return owner
    owner_id = getattr(record, 'owner_id', None)
    if isinstance(owner_id, str) and owner_id:
        return owner_id
    return None


def _runtime_owner(owner: CapabilityOwner | str | None, adapter: TargetAdapter) -> CapabilityOwner | None:
    version = getattr(adapter, 'capability_version', None)
    if owner is None:
        return None
    if isinstance(owner, CapabilityOwner):
        if owner.version is not None or version is None:
            return owner
        return CapabilityOwner(id=owner.id, version=version)
    return CapabilityOwner(id=owner, version=version)


def _validate_target_adapter(capability_id: str, adapter: object) -> TargetAdapter:
    if not isinstance(adapter, TargetAdapter):
        raise PublishError(f"target capability {capability_id!r} must implement TargetAdapter")
    return adapter


def _sensitive_key(key: str) -> bool:
    normalized = key.lower().replace('-', '_')
    return normalized in {'secret', 'token', 'password', 'passwd', 'api_key', 'apikey'}


__all__ = [
    'LOCAL_TARGET_TYPE',
    'LocalTargetAdapter',
    'PublishedRef',
    'TargetCapability',
    'TargetCredentials',
    'TargetRef',
    'TargetRegistry',
    'sanitize_target_error_message',
]
