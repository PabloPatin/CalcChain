from __future__ import annotations

from dataclasses import dataclass
import json
from logging import Logger
import re
from typing import cast

from calcchain_core.common.errors import CalcChainError
from calcchain_core.helpers.protocols import ProtocolCompatibilityError, ensure_protocol_methods
from calcchain_capabilities import AuthAdapter, AuthContext, AuthCredentials, AuthServiceProtocol, AuthRequirement
from calcchain_capabilities import RuntimeCapabilities
from calcchain_capabilities.registrars import CapabilityRecord

_SECRET_ASSIGNMENT_RE = re.compile(r'(?i)\b(secret|token|password|passwd|api[_-]?key)=([^\s,;]+)')


class AuthError(CalcChainError):
    """Raised when runtime credentials cannot be selected or obtained safely."""


class NoAuthService:
    def has_provider(self, requirement: AuthRequirement) -> bool:
        return False

    def get_credentials(self, requirement: AuthRequirement) -> AuthCredentials:
        raise AuthError('auth service is not configured')


@dataclass(frozen=True)
class CredentialPolicy:
    allow_session_cache: bool = True
    allow_persistent_storage: bool = False


AuthProvider = CapabilityRecord[AuthAdapter]


class AuthService:
    def __init__(
        self,
        providers: list[AuthProvider] | None = None,
        *,
        policy: CredentialPolicy | None = None,
        logger: Logger | None = None,
    ) -> None:
        self._providers = list(providers or [])
        self._policy = policy or CredentialPolicy()
        self._logger = logger
        self._session_cache: dict[str, AuthCredentials] = {}

    @classmethod
    def from_runtime(
        cls,
        runtime: RuntimeCapabilities | None,
        *,
        policy: CredentialPolicy | None = None,
        logger: Logger | None = None,
    ) -> AuthService:
        providers: list[AuthProvider] = []
        if runtime is not None:
            for key, record in runtime.capabilities.items():
                if key.namespace != 'auth':
                    continue
                adapter = _auth_adapter_from_capability(record.adapter, capability_id=key.id)
                providers.append(
                    AuthProvider(
                        key=key,
                        adapter=adapter,
                        owner=record.owner,
                    ),
                )
        return cls(providers, policy=policy, logger=logger)

    def has_provider(self, requirement: AuthRequirement) -> bool:
        return self._select_provider(requirement) is not None

    def get_credentials(self, requirement: AuthRequirement) -> AuthCredentials:
        cache_key = self._cache_key(requirement) if self._policy.allow_session_cache else None
        if cache_key is not None and cache_key in self._session_cache:
            return self._session_cache[cache_key]

        provider = self._select_provider(requirement)
        if provider is None:
            raise AuthError(_redact_auth_message(f'auth provider not found for requirement: {requirement}'))
        context = self._context(provider)
        try:
            provider.adapter.validate_requirement(requirement, context)
            credentials = provider.adapter.get_credentials(requirement, context)
        except AuthError:
            raise
        except Exception as err:
            raise AuthError(_redact_auth_message(f'auth provider failed: {err}', requirement)) from err
        if not isinstance(credentials, AuthCredentials):
            raise AuthError('auth provider returned invalid credentials')
        if cache_key is not None:
            self._session_cache[cache_key] = credentials
        return credentials

    def _select_provider(self, requirement: AuthRequirement) -> AuthProvider | None:
        for provider in self._providers:
            context = self._context(provider)
            try:
                if provider.adapter.can_handle(requirement, context):
                    return provider
            except Exception as err:
                raise AuthError(_redact_auth_message(f'auth provider selection failed: {err}', requirement)) from err
        return None

    def _context(self, provider: AuthProvider) -> AuthContext:
        return AuthContext(
            owner=provider.owner,
            capability_id=provider.capability_id,
            logger=self._logger,
        )

    def _cache_key(self, requirement: AuthRequirement) -> str:
        payload = {
            'scheme': requirement.scheme,
            'scope': requirement.scope,
            'fields': [(field.name, field.secret) for field in requirement.fields],
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str)


def _redact_auth_message(message: str, requirement: AuthRequirement | None = None) -> str:
    redacted = message
    if requirement is not None:
        for field in requirement.fields:
            if field.secret:
                redacted = _redact_field_value(redacted, field.name)
    return _SECRET_ASSIGNMENT_RE.sub(r'\1=[redacted]', redacted)


def _auth_adapter_from_capability(capability: object, *, capability_id: str) -> AuthAdapter:
    try:
        ensure_protocol_methods(AuthAdapter, capability)
    except ProtocolCompatibilityError as err:
        missing = ', '.join(err.missing_methods)
        raise AuthError(f"auth capability {capability_id!r} does not implement: {missing}") from err
    return cast(AuthAdapter, capability)


def _redact_field_value(message: str, field_name: str) -> str:
    escaped = re.escape(field_name)
    redacted = re.sub(
        rf'(?i)(\b{escaped}\s*=\s*)([^\s,;]+)',
        rf'\1[redacted]',
        message,
    )
    redacted = re.sub(
        rf"(?i)(['\"]{escaped}['\"]\s*:\s*['\"])([^'\"]+)(['\"])",
        rf'\1[redacted]\3',
        redacted,
    )
    return redacted


__all__ = ['AuthError', 'AuthServiceProtocol', 'AuthService', 'CredentialPolicy', 'NoAuthService']
