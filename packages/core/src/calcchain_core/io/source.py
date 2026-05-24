from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from ..capabilities.adapters import SourceAdapter
from ..capabilities.runtime import (
    CapabilityKey,
    CapabilityOwner,
    RuntimeCapabilities,
    SourceContext,
)
from ..common.errors import SourceError
from ..secrets import NoSecretsResolver, SecretsResolver
from .registry_common import (
    capability_id,
    capability_namespace,
    normalize_relative_path,
    preserve_credentials,
    record_owner,
    ref_type,
    resolve_ref_credentials,
    runtime_owner,
    sanitize_io_error_message,
    secret_values_from_call_args,
    typed_record_adapter,
    validate_adapter,
)
from .ref import ExternalRef, RefCredentials


SourceCredentials = RefCredentials
SourceRef = ExternalRef

LOCAL_SOURCE_TYPE = 'local'


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
            normalize_relative_path(
                file.relative_to(root).as_posix(),
                field='local source file',
                error_cls=SourceError,
            )
            for file in root.rglob('*')
            if file.is_file()
        )

    def read_file(self, ref: Mapping[str, Any], relative_path: str, context: SourceContext) -> bytes:
        source = _parse_local_source(ref)
        safe_path = normalize_relative_path(relative_path, field='local source file', error_cls=SourceError)
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
            raise SourceError(
                sanitize_source_error_message(message, ref, secret_values=secret_values_from_call_args(args)),
            ) from err


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
            if capability_namespace(key) != 'source':
                continue
            source_type = capability_id(key, label='source', error_cls=SourceError)
            adapter = typed_record_adapter(
                record,
                capability_id=source_type,
                adapter_type=SourceAdapter,
                protocol_name='SourceAdapter',
                label='source',
                error_cls=SourceError,
            )
            registry.register(
                SourceCapability(
                    key=CapabilityKey('source', source_type),
                    adapter=adapter,
                    owner=runtime_owner(record_owner(record), adapter),
                ),
            )
        return registry

    def register(self, capability: SourceCapability, *, override: bool = False) -> None:
        if capability.key.namespace != 'source':
            raise SourceError(f"source registry cannot register {capability.key.qualified_id!r}")
        adapter = validate_adapter(
            capability.capability_id,
            capability.adapter,
            adapter_type=SourceAdapter,
            protocol_name='SourceAdapter',
            label='source',
            error_cls=SourceError,
        )
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
        capability_id = ref_type(source.data, label='source', error_cls=SourceError)
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
        return preserve_credentials(source, resolved_ref, SourceRef)

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
            credentials=resolve_ref_credentials(
                source,
                self._secrets_resolver,
                kind='source.credentials',
                type_key='source_type',
                type_id=capability.capability_id,
            ),
        )


def sanitize_source_error_message(
    message: str,
    ref: Mapping[str, Any] | None = None,
    *,
    secret_values: Iterable[str] = (),
) -> str:
    return sanitize_io_error_message(message, ref, secret_values=secret_values)


def _parse_local_source(ref: Mapping[str, Any]) -> dict[str, Any]:
    current_type = ref_type(ref, label='source', error_cls=SourceError)
    if current_type != LOCAL_SOURCE_TYPE:
        raise SourceError(f'local source adapter received unsupported source type: {current_type}')
    path = ref.get('path')
    if not isinstance(path, str) or not path:
        raise SourceError('local source must define non-empty path')
    return {'type': LOCAL_SOURCE_TYPE, 'path': path}


def _local_source_capability() -> SourceCapability:
    return SourceCapability(
        key=CapabilityKey('source', LOCAL_SOURCE_TYPE),
        adapter=LocalSourceAdapter(),
    )


__all__ = [
    'LOCAL_SOURCE_TYPE',
    'LocalSourceAdapter',
    'SourceCapability',
    'SourceCredentials',
    'SourceRef',
    'SourceRegistry',
    'sanitize_source_error_message',
]
