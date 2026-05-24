from typing import Any

from ..common.errors import SecretsError


class SecretsResolver:
    def resolve(self, key: str, *, context: dict[str, Any] | None = None) -> str:
        raise NotImplementedError


class NoSecretsResolver(SecretsResolver):
    def resolve(self, key: str, *, context: dict[str, Any] | None = None) -> str:
        raise SecretsError(f'secrets resolver is not configured: {key}')
