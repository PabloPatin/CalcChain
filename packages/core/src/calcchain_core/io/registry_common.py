from collections.abc import Iterable, Mapping
from pathlib import PurePosixPath
import re
from typing import Any, TypeVar

from ..capabilities import CapabilityOwner, ResolvedCredentials
from ..secrets import SecretsResolver
from .ref import ExternalRef


_URL_USERINFO_RE = re.compile(r'([A-Za-z][A-Za-z0-9+.-]*://)([^/\s?#@]+@)([^/\s?#]+)')

_TRef = TypeVar('_TRef', bound=ExternalRef)
_TAdapter = TypeVar('_TAdapter')


def sanitize_io_error_message(
    message: str,
    ref: Mapping[str, Any] | None = None,
    *,
    secret_values: Iterable[str] = (),
) -> str:
    sanitized = message
    if ref is not None:
        location = ref.get('location')
        if isinstance(location, str) and _URL_USERINFO_RE.search(location):
            sanitized = sanitized.replace(location, _URL_USERINFO_RE.sub(r'\1[redacted]@\3', location))
    for value in secret_values:
        if value:
            sanitized = sanitized.replace(value, '[redacted]')
    sanitized = _URL_USERINFO_RE.sub(r'\1[redacted]@\3', sanitized)
    return sanitized


def resolve_ref_credentials(
    ref: ExternalRef,
    secrets_resolver: SecretsResolver,
    *,
    kind: str,
    type_key: str,
    type_id: str,
) -> ResolvedCredentials:
    credentials = ref.credentials
    if credentials is None:
        return ResolvedCredentials()
    secrets = {
        name: secrets_resolver.resolve(
            secret_key,
            context={'kind': kind, type_key: type_id, 'name': name, 'ref': dict(ref.data)},
        )
        for name, secret_key in credentials.secrets.items()
    }
    return ResolvedCredentials(public=credentials.public, secrets=secrets)


def secret_values_from_call_args(args: Iterable[object]) -> tuple[str, ...]:
    values: list[str] = []
    for arg in args:
        credentials = getattr(arg, 'credentials', None)
        secrets = getattr(credentials, 'secrets', None)
        if not isinstance(secrets, Mapping):
            continue
        for value in secrets.values():
            if isinstance(value, str) and value:
                values.append(value)
    return tuple(dict.fromkeys(values))


def preserve_credentials(original: _TRef, resolved: _TRef, ref_cls: type[_TRef]) -> _TRef:
    if resolved.credentials is not None:
        return resolved
    return ref_cls(data=resolved.data, credentials=original.credentials)


def normalize_relative_path(value: str, *, field: str, error_cls: type[Exception]) -> str:
    normalized = value.replace('\\', '/')
    if normalized.startswith('/') or has_windows_drive(normalized):
        raise error_cls(f'{field} must be relative: {value}')
    path = PurePosixPath(normalized)
    if '..' in path.parts:
        raise error_cls(f'{field} must not contain path traversal: {value}')
    result = path.as_posix()
    if result in {'', '.'}:
        raise error_cls(f'{field} must identify a file: {value}')
    return result


def ref_type(ref: Mapping[str, Any], *, label: str, error_cls: type[Exception]) -> str:
    value = ref.get('type')
    if isinstance(value, str) and value:
        return value
    raise error_cls(f'{label} ref must define non-empty type')


def capability_namespace(key) -> str | None:
    namespace = getattr(key, 'namespace', None)
    return getattr(namespace, 'value', namespace)


def capability_id(key, *, label: str, error_cls: type[Exception]) -> str:
    value = getattr(key, 'id', None)
    if not isinstance(value, str) or not value:
        raise error_cls(f'{label} capability key must have a non-empty id')
    return value


def record_adapter(record, *, capability_id: str, label: str, error_cls: type[Exception]) -> object:
    adapter = getattr(record, 'adapter', None)
    if adapter is None:
        adapter = getattr(record, 'capability', None)
    if adapter is None:
        raise error_cls(f"{label} capability {capability_id!r} has no adapter")
    return adapter


def validate_adapter(
    capability_id: str,
    adapter: object,
    *,
    adapter_type: type[_TAdapter],
    protocol_name: str,
    label: str,
    error_cls: type[Exception],
) -> _TAdapter:
    if not isinstance(adapter, adapter_type):
        raise error_cls(f"{label} capability {capability_id!r} must implement {protocol_name}")
    return adapter


def typed_record_adapter(
    record,
    *,
    capability_id: str,
    adapter_type: type[_TAdapter],
    protocol_name: str,
    label: str,
    error_cls: type[Exception],
) -> _TAdapter:
    adapter = record_adapter(record, capability_id=capability_id, label=label, error_cls=error_cls)
    return validate_adapter(
        capability_id,
        adapter,
        adapter_type=adapter_type,
        protocol_name=protocol_name,
        label=label,
        error_cls=error_cls,
    )


def record_owner(record) -> CapabilityOwner | str | None:
    owner = getattr(record, 'owner', None)
    if owner is not None:
        return owner
    owner_id = getattr(record, 'owner_id', None)
    if isinstance(owner_id, str) and owner_id:
        return owner_id
    return None


def runtime_owner(owner: CapabilityOwner | str | None, adapter: object) -> CapabilityOwner | None:
    version = getattr(adapter, 'capability_version', None)
    if owner is None:
        return None
    if isinstance(owner, CapabilityOwner):
        if owner.version is not None or version is None:
            return owner
        return CapabilityOwner(id=owner.id, version=version)
    return CapabilityOwner(id=owner, version=version)


def has_windows_drive(value: str) -> bool:
    return len(value) >= 2 and value[1] == ':' and value[0].isalpha()
