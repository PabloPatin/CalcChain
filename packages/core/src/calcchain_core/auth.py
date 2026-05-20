from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

from calcchain_core.errors import CalcChainError
from calcchain_capabilities import AuthContext, AuthCredentials, AuthRequirement
from calcchain_capabilities import PluginRuntimeSet

_SECRET_ASSIGNMENT_RE = re.compile(r'(?i)\b(secret|token|password|passwd|api[_-]?key)=([^\s,;]+)')
_SENSITIVE_KEYS = frozenset({'secret', 'token', 'password', 'passwd', 'api_key', 'apikey', 'api-key'})


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


@dataclass(frozen=True)
class _AuthProvider:
    capability_id: str
    plugin_id: str
    adapter: object


class AuthService:
    def __init__(
        self,
        providers: list[_AuthProvider] | None = None,
        *,
        policy: CredentialPolicy | None = None,
        logger: object | None = None,
    ) -> None:
        self._providers = list(providers or [])
        self._policy = policy or CredentialPolicy()
        self._logger = logger
        self._session_cache: dict[str, AuthCredentials] = {}

    @classmethod
    def from_runtime(
        cls,
        runtime: PluginRuntimeSet | None,
        *,
        policy: CredentialPolicy | None = None,
        logger: object | None = None,
    ) -> AuthService:
        providers: list[_AuthProvider] = []
        if runtime is not None:
            for key, record in runtime.capabilities.items():
                if key.namespace != 'auth':
                    continue
                providers.append(
                    _AuthProvider(
                        capability_id=key.id,
                        plugin_id=record.owner,
                        adapter=record.capability,
                    ),
                )
        return cls(providers, policy=policy, logger=logger)

    def has_provider(self, requirement: AuthRequirement) -> bool:
        self._validate_requirement_shape(requirement)
        return self._select_provider(requirement) is not None

    def get_credentials(self, requirement: AuthRequirement) -> AuthCredentials:
        self._validate_requirement_shape(requirement)
        cache_key = self._cache_key(requirement) if self._policy.allow_session_cache else None
        if cache_key is not None and cache_key in self._session_cache:
            return self._session_cache[cache_key]

        provider = self._select_provider(requirement)
        if provider is None:
            raise AuthError(_redact_auth_message(f'auth provider not found for requirement: {requirement}'))
        context = self._context(provider, 'get_credentials')
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

    def _select_provider(self, requirement: AuthRequirement) -> _AuthProvider | None:
        for provider in self._providers:
            context = self._context(provider, 'can_handle')
            try:
                if provider.adapter.can_handle(requirement, context):
                    return provider
            except Exception as err:
                raise AuthError(_redact_auth_message(f'auth provider selection failed: {err}', requirement)) from err
        return None

    def _context(self, provider: _AuthProvider, operation: str) -> AuthContext:
        return AuthContext(
            plugin_id=provider.plugin_id,
            capability_id=provider.capability_id,
            operation=operation,
            logger=self._logger,
        )

    def _validate_requirement_shape(self, requirement: AuthRequirement) -> None:
        if not isinstance(requirement.scheme, str) or not requirement.scheme:
            raise AuthError('auth requirement scheme is required')
        if requirement.persistence not in {'forbidden', 'allowed'}:
            raise AuthError('auth requirement persistence must be forbidden or allowed')

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


def _sensitive_key(key: Any) -> bool:
    if not isinstance(key, str):
        return False
    normalized = key.lower().replace('-', '_')
    return normalized in _SENSITIVE_KEYS


__all__ = ['AuthError', 'AuthService', 'CredentialPolicy', 'NoAuthService']
