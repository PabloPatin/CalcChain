from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, Mapping, cast
import re

PluginDiagnosticPhase = Literal[
    'discovery',
    'metadata_read',
    'metadata_validation',
    'compatibility_check',
    'dependency_plan',
    'dependency_install',
    'entrypoint_import',
    'plugin_instantiate',
    'capability_registration',
    'activation_commit',
]

PLUGIN_DIAGNOSTIC_PHASES: tuple[PluginDiagnosticPhase, ...] = (
    'discovery',
    'metadata_read',
    'metadata_validation',
    'compatibility_check',
    'dependency_plan',
    'dependency_install',
    'entrypoint_import',
    'plugin_instantiate',
    'capability_registration',
    'activation_commit',
)

_MASK = '[secret]'
_URL_USERINFO_PATTERN = re.compile(r'(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*://)[^/@\s]+@')
_AUTH_HEADER_PATTERN = re.compile(
    r'(?i)\b(authorization)(\s*[:=]\s*)(["\']?)(Bearer\s+)?([^,\s;\'"}]+)',
)
_BEARER_PATTERN = re.compile(r'(?i)\b(Bearer)\s+[A-Za-z0-9._~+/=-]+')
_CREDENTIAL_PATTERN = re.compile(
    r'(?i)\b('
    r'password|passwd|secret|token|api[_-]?key|access[_-]?token'
    r')\b(\s*[:=]\s*)(["\']?)([^,\s;\'"}]+)',
)


def redact_secrets(value: object, *, secret_values: tuple[str, ...] | list[str] = ()) -> object:
    """Return a copy of value with known secrets and common credential patterns masked."""
    if isinstance(value, str):
        return _redact_string(value, secret_values=secret_values)
    if isinstance(value, Mapping):
        return {
            str(key): redact_secrets(item, secret_values=secret_values)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return tuple(redact_secrets(item, secret_values=secret_values) for item in value)
    if isinstance(value, set | frozenset):
        return frozenset(redact_secrets(item, secret_values=secret_values) for item in value)
    return value


def _redact_string(message: str, *, secret_values: tuple[str, ...] | list[str]) -> str:
    redacted = message
    for secret in sorted((item for item in secret_values if item), key=len, reverse=True):
        redacted = redacted.replace(secret, _MASK)
    redacted = _URL_USERINFO_PATTERN.sub(r'\g<scheme>[redacted]@', redacted)
    redacted = _AUTH_HEADER_PATTERN.sub(_redact_authorization_header, redacted)
    redacted = _BEARER_PATTERN.sub(r'\1 [secret]', redacted)
    return _CREDENTIAL_PATTERN.sub(r'\1\2\3[secret]', redacted)


def _redact_authorization_header(match: re.Match[str]) -> str:
    bearer = 'Bearer ' if match.group(4) else ''
    return f'{match.group(1)}{match.group(2)}{match.group(3)}{bearer}{_MASK}'


def freeze_diagnostic_details(details: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType({str(key): _freeze_value(value) for key, value in details.items()})


def _freeze_value(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_value(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, set | frozenset):
        return frozenset(_freeze_value(item) for item in value)
    return value


@dataclass(frozen=True)
class PluginDiagnostic:
    plugin_id: str | None
    phase: PluginDiagnosticPhase
    code: str
    message: str
    safe_details: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.phase not in PLUGIN_DIAGNOSTIC_PHASES:
            raise ValueError(f'Unknown plugin diagnostic phase: {self.phase}')
        object.__setattr__(self, 'message', cast(str, redact_secrets(self.message)))
        object.__setattr__(
            self,
            'safe_details',
            freeze_diagnostic_details(cast(Mapping[str, object], redact_secrets(self.safe_details))),
        )

    @classmethod
    def create(
        cls,
        *,
        plugin_id: str | None,
        phase: PluginDiagnosticPhase,
        code: str,
        message: str,
        safe_details: Mapping[str, object] | None = None,
        secret_values: tuple[str, ...] | list[str] = (),
    ) -> PluginDiagnostic:
        return cls(
            plugin_id=plugin_id,
            phase=phase,
            code=code,
            message=cast(str, redact_secrets(message, secret_values=secret_values)),
            safe_details=cast(
                Mapping[str, object],
                redact_secrets(safe_details or {}, secret_values=secret_values),
            ),
        )


__all__ = [
    'PLUGIN_DIAGNOSTIC_PHASES',
    'PluginDiagnostic',
    'PluginDiagnosticPhase',
    'redact_secrets',
]
