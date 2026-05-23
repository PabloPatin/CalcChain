from typing import Any


class SecretsResolver:
    def resolve(self, key: str, *, context: dict[str, Any] | None = None) -> str:
        raise NotImplementedError


class NoSecretsResolver(SecretsResolver):
    def resolve(self, key: str, *, context: dict[str, Any] | None = None) -> str:
        raise RuntimeError(f'secrets resolver is not configured: {key}')
