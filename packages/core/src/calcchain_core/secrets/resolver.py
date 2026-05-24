from typing import Any

from ..capabilities.adapters import SecretsAdapter
from ..capabilities.runtime import CapabilityOwner, RuntimeCapabilities, SecretsContext
from ..common.errors import SecretsError
from ..common.hash import sha256_dict
from .store import MemorySecretStore, SecretPersistencePolicy, SecretStore, default_secret_store

AUTO_SECRET_KEY = '@auto'


class SecretsResolver:
    def resolve(self, key: str | None, *, context: dict[str, Any] | None = None) -> str:
        raise NotImplementedError


class NoSecretsResolver(SecretsResolver):
    def resolve(self, key: str | None, *, context: dict[str, Any] | None = None) -> str:
        raise SecretsError(f'secrets resolver is not configured: {key}')


class RuntimeSecretsResolver(SecretsResolver):
    def __init__(
        self,
        entries: list[tuple[str, CapabilityOwner | None, SecretsAdapter]] | None = None,
        *,
        policy: SecretPersistencePolicy | None = None,
        store: SecretStore | None = None,
        memory_store: MemorySecretStore | None = None,
    ) -> None:
        self._entries = tuple(entries or ())
        self._policy = policy or SecretPersistencePolicy()
        self._memory_store = memory_store or MemorySecretStore()
        self._store = store if store is not None else default_secret_store()

    @classmethod
    def from_runtime(
        cls,
        runtime: RuntimeCapabilities | None = None,
        *,
        policy: SecretPersistencePolicy | None = None,
        store: SecretStore | None = None,
        memory_store: MemorySecretStore | None = None,
    ) -> 'RuntimeSecretsResolver':
        if runtime is None:
            return cls(policy=policy, store=store, memory_store=memory_store)
        entries: list[tuple[str, CapabilityOwner | None, SecretsAdapter]] = []
        for key, record in runtime.capabilities.items():
            if key.namespace != 'secrets':
                continue
            adapter = record.adapter
            if not isinstance(adapter, SecretsAdapter):
                raise SecretsError(f"secrets capability {key.id!r} must implement SecretsAdapter")
            entries.append((key.id, record.owner, adapter))
        return cls(entries, policy=policy, store=store, memory_store=memory_store)

    @property
    def configured(self) -> bool:
        return bool(self._entries)

    def resolve(self, key: str | None, *, context: dict[str, Any] | None = None) -> str:
        request_context = dict(context or {})
        storage_key = _storage_key(key, request_context)
        request_context['secret_ref'] = key
        if storage_key is not None:
            request_context['storage_key'] = storage_key
            stored_value = self._get_stored_secret(storage_key)
            if stored_value is not None:
                return stored_value

        resolved_value = self._resolve_from_capability(key, request_context, storage_key=storage_key)
        if storage_key is not None:
            self._set_stored_secret(storage_key, resolved_value)
        return resolved_value

    def _get_stored_secret(self, storage_key: str) -> str | None:
        if self._policy.allow_memory:
            value = self._memory_store.get(storage_key)
            if value is not None:
                return value
        if not self._policy.allow_store:
            return None
        value = self._store.get(storage_key)
        if value is not None and self._policy.allow_memory:
            self._memory_store.set(storage_key, value)
        return value

    def _set_stored_secret(self, storage_key: str, value: str) -> None:
        if self._policy.allow_memory:
            self._memory_store.set(storage_key, value)
        if self._policy.allow_store:
            self._store.set(storage_key, value)

    def _resolve_from_capability(
        self,
        key: str | None,
        request_context: dict[str, Any],
        *,
        storage_key: str | None,
    ) -> str:
        adapter_key = storage_key or key or ''
        errors: list[str] = []
        for capability_id, owner, adapter in self._entries:
            secrets_context = SecretsContext(
                owner=owner,
                capability_id=capability_id,
                request_context=request_context,
            )
            try:
                if not adapter.can_resolve(adapter_key, secrets_context):
                    continue
                value = adapter.resolve(adapter_key, secrets_context)
            except Exception as exc:
                owner_label = owner.id if owner is not None else 'builtin'
                errors.append(f'{capability_id} ({owner_label}): {exc}')
                continue
            if not isinstance(value, str):
                raise SecretsError(f"secrets capability {capability_id!r} returned non-string secret")
            return value
        if errors:
            raise SecretsError(f'secret could not be resolved: {key}; errors: {"; ".join(errors)}')
        raise SecretsError(f'secret could not be resolved: {key}')


def _storage_key(key: str | None, context: dict[str, Any]) -> str | None:
    if key is None or key == '':
        return None
    if key == AUTO_SECRET_KEY:
        return _auto_storage_key(context)
    return key


def _auto_storage_key(context: dict[str, Any]) -> str:
    material = _freeze_for_hash(context)
    return f'calcchain:{sha256_dict(material)}'


def _freeze_for_hash(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _freeze_for_hash(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_freeze_for_hash(item) for item in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return repr(value)


__all__ = [
    'AUTO_SECRET_KEY',
    'NoSecretsResolver',
    'RuntimeSecretsResolver',
    'SecretPersistencePolicy',
    'SecretsResolver',
]
