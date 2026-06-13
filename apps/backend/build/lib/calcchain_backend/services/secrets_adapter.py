from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from calcchain_core.capabilities import (
    CapabilityKey,
    CapabilityOwner,
    CapabilityRecord,
    RuntimeCapabilities,
    SecretsContext,
)

from calcchain_backend.services.secret_service import (
    SecretExpiredError,
    SecretFieldNotFoundError,
    SecretNotFoundError,
    SecretService,
)


BACKEND_SECRETS_CAPABILITY_ID = "backend-session"


class BackendSecretsAdapter:
    """Core SecretsAdapter backed by backend session secrets.

    Core passes a secret key plus request context. For source/target
    credentials, the field name is stored in `context.request_context["name"]`.
    `SecretService` stores grouped secret values by `secret_ref`, so this adapter
    resolves a single field from that group.
    """

    def __init__(self, secret_service: SecretService, session_key: str) -> None:
        self._secret_service = secret_service
        self._session_key = session_key

    def can_resolve(self, key: str, context: SecretsContext) -> bool:
        secret_ref = _secret_ref(key, context.request_context)
        field_name = _field_name(context.request_context)
        if not secret_ref or not field_name:
            return False
        if self._secret_service.has_secret(self._session_key, secret_ref, field_name):
            return True
        return self._secret_service.has_secret(self._session_key, secret_ref, "value")

    def resolve(self, key: str, context: SecretsContext) -> str:
        secret_ref = _required_secret_ref(key, context.request_context)
        field_name = _required_field_name(context.request_context)
        try:
            return self._secret_service.resolve_value(self._session_key, secret_ref, field_name)
        except SecretFieldNotFoundError:
            return self._secret_service.resolve_value(self._session_key, secret_ref, "value")
        except (SecretExpiredError, SecretNotFoundError):
            raise


def runtime_with_backend_secrets(
    secret_service: SecretService,
    session_key: str,
    *,
    base_runtime: RuntimeCapabilities | None = None,
) -> RuntimeCapabilities:
    capabilities = dict(base_runtime.capabilities) if base_runtime is not None else {}
    key = CapabilityKey("secrets", BACKEND_SECRETS_CAPABILITY_ID)
    capabilities[key] = CapabilityRecord(
        key=key,
        adapter=BackendSecretsAdapter(secret_service, session_key),
        owner=CapabilityOwner("calcchain-backend"),
    )
    return RuntimeCapabilities(
        capabilities=capabilities,
        active_owner_ids=base_runtime.active_owner_ids if base_runtime is not None else (),
        environment=base_runtime.environment if base_runtime is not None else None,
        diagnostics=base_runtime.diagnostics if base_runtime is not None else (),
    )


def _secret_ref(key: str, context: Mapping[str, Any]) -> str | None:
    explicit = context.get("secret_ref")
    if isinstance(explicit, str) and explicit and explicit != "@auto":
        return explicit
    storage_key = context.get("storage_key")
    if isinstance(storage_key, str) and storage_key:
        return storage_key
    return key or None


def _required_secret_ref(key: str, context: Mapping[str, Any]) -> str:
    secret_ref = _secret_ref(key, context)
    if not secret_ref:
        raise SecretNotFoundError("missing secret reference")
    return secret_ref


def _field_name(context: Mapping[str, Any]) -> str | None:
    value = context.get("name")
    return value if isinstance(value, str) and value else None


def _required_field_name(context: Mapping[str, Any]) -> str:
    field_name = _field_name(context)
    if field_name is None:
        raise SecretFieldNotFoundError("missing secret field name")
    return field_name
