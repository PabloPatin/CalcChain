from dataclasses import dataclass
from typing import Protocol

from ..common.errors import SecretsError


@dataclass(frozen=True)
class SecretPersistencePolicy:
    allow_memory: bool = True
    allow_store: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.allow_memory, bool):
            raise TypeError('allow_memory must be a boolean')
        if not isinstance(self.allow_store, bool):
            raise TypeError('allow_store must be a boolean')


class SecretStore(Protocol):
    def get(self, key: str) -> str | None:
        ...

    def set(self, key: str, value: str) -> None:
        ...


class MemorySecretStore:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self._values = dict(values or {})

    def get(self, key: str) -> str | None:
        return self._values.get(key)

    def set(self, key: str, value: str) -> None:
        self._values[key] = value


class KeyringSecretStore:
    def __init__(self, *, service_name: str = 'calcchain', strict: bool = False) -> None:
        self.service_name = service_name
        self.strict = strict

    def get(self, key: str) -> str | None:
        keyring = self._keyring()
        if keyring is None:
            return None
        try:
            return keyring.get_password(self.service_name, key)
        except Exception as exc:
            if self.strict:
                raise SecretsError(f'failed to read secret from keyring: {key}') from exc
            return None

    def set(self, key: str, value: str) -> None:
        keyring = self._keyring()
        if keyring is None:
            return
        try:
            keyring.set_password(self.service_name, key, value)
        except Exception as exc:
            if self.strict:
                raise SecretsError(f'failed to write secret to keyring: {key}') from exc

    def _keyring(self):
        try:
            import keyring
        except ImportError as exc:
            if self.strict:
                raise SecretsError('keyring package is not installed') from exc
            return None
        return keyring


def default_secret_store() -> SecretStore:
    return KeyringSecretStore()


__all__ = [
    'KeyringSecretStore',
    'MemorySecretStore',
    'SecretPersistencePolicy',
    'SecretStore',
    'default_secret_store',
]
