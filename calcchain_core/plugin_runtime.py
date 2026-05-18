from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class SourceContext:
    plugin_id: str | None
    capability_id: str
    operation: str
    auth: object | None = None
    logger: object | None = None


@dataclass(frozen=True)
class TargetContext:
    plugin_id: str | None
    capability_id: str
    operation: str
    auth: object | None = None
    logger: object | None = None


@dataclass(frozen=True)
class AuthContext:
    plugin_id: str | None
    capability_id: str
    operation: str
    logger: object | None = None


@dataclass(frozen=True)
class ReportContext:
    plugin_id: str | None
    capability_id: str
    manifest: Mapping[str, Any]
    logger: object | None = None


@dataclass(frozen=True)
class PluginRefMetadata:
    id: str
    version: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> PluginRefMetadata:
        plugin_id = data.get('id')
        version = data.get('version')
        if not isinstance(plugin_id, str):
            raise ValueError('plugin.id must be a string')
        if not isinstance(version, str):
            raise ValueError('plugin.version must be a string')
        return cls(id=plugin_id, version=version)

    def to_dict(self) -> dict[str, str]:
        return {'id': self.id, 'version': self.version}


@dataclass(frozen=True)
class AuthField:
    name: str
    secret: bool

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError('auth field name must be a non-empty string')
        if not isinstance(self.secret, bool):
            raise ValueError('auth field secret must be a boolean')


@dataclass(frozen=True)
class AuthRequirement:
    scheme: str
    scope: Mapping[str, Any] = field(default_factory=dict)
    fields: tuple[AuthField, ...] = ()
    persistence: str = 'forbidden'
    optional: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.scheme, str) or not self.scheme:
            raise ValueError('auth requirement scheme must be a non-empty string')
        object.__setattr__(self, 'scope', dict(self.scope))
        object.__setattr__(
            self,
            'fields',
            tuple(field if isinstance(field, AuthField) else AuthField(**field) for field in self.fields),
        )
        if self.persistence not in {'forbidden', 'allowed'}:
            raise ValueError('auth requirement persistence must be forbidden or allowed')
        if not isinstance(self.optional, bool):
            raise ValueError('auth requirement optional must be a boolean')


@dataclass(frozen=True, repr=False)
class AuthCredentials:
    values: Mapping[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        return 'AuthCredentials([redacted])'

    def __str__(self) -> str:
        return repr(self)


@dataclass(frozen=True)
class PublishedRef:
    ref: Mapping[str, Any]
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReportDescriptor:
    id: str
    title: str
    content_type: str | None = None
    file_extension: str | None = None


@dataclass(frozen=True)
class ReportRequest:
    report_id: str
    manifest_path: Any | None = None
    parameters: Mapping[str, Any] = field(default_factory=dict)
    output: str = 'return'

    def __post_init__(self) -> None:
        if not isinstance(self.report_id, str) or not self.report_id:
            raise ValueError('report_id must be a non-empty string')
        object.__setattr__(self, 'parameters', dict(self.parameters))
        if self.output not in {'return', 'file'}:
            raise ValueError('report output must be return or file')


@dataclass(frozen=True)
class ReportResult:
    report_id: str
    content: bytes | str | None
    content_type: str
    path: Any | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, 'metadata', dict(self.metadata))


class SourceAdapter(Protocol):
    def validate_config(self, ref: Mapping[str, Any], context: SourceContext) -> None:
        ...

    def resolve_lock_ref(self, ref: Mapping[str, Any], context: SourceContext) -> dict[str, Any]:
        ...

    def validate_lock_ref(self, lock_ref: Mapping[str, Any], context: SourceContext) -> None:
        ...

    def list_files(self, ref: Mapping[str, Any], context: SourceContext) -> list[str]:
        ...

    def read_file(self, ref: Mapping[str, Any], relative_path: str, context: SourceContext) -> bytes:
        ...

    def is_versionable(self, ref: Mapping[str, Any], context: SourceContext) -> bool:
        ...


class TargetAdapter(Protocol):
    def validate_config(self, ref: Mapping[str, Any], context: TargetContext) -> None:
        ...

    def resolve_lock_ref(self, ref: Mapping[str, Any], context: TargetContext) -> dict[str, Any]:
        ...

    def validate_lock_ref(self, lock_ref: Mapping[str, Any], context: TargetContext) -> None:
        ...

    def ensure_root(self, ref: Mapping[str, Any], context: TargetContext) -> dict[str, Any]:
        ...

    def write_file(
        self,
        ref: Mapping[str, Any],
        relative_path: str,
        data: bytes,
        context: TargetContext,
    ) -> PublishedRef:
        ...

    def is_versionable(self, ref: Mapping[str, Any], context: TargetContext) -> bool:
        ...


class AuthAdapter(Protocol):
    def can_handle(self, requirement: AuthRequirement, context: AuthContext) -> bool:
        ...

    def validate_requirement(self, requirement: AuthRequirement, context: AuthContext) -> None:
        ...

    def get_credentials(self, requirement: AuthRequirement, context: AuthContext) -> AuthCredentials:
        ...


class ReportAdapter(Protocol):
    def describe(self, context: ReportContext) -> ReportDescriptor:
        ...

    def render(self, request: ReportRequest, context: ReportContext) -> ReportResult:
        ...


__all__ = [
    'AuthAdapter',
    'AuthContext',
    'AuthCredentials',
    'AuthField',
    'AuthRequirement',
    'PluginRefMetadata',
    'PublishedRef',
    'ReportAdapter',
    'ReportContext',
    'ReportDescriptor',
    'ReportRequest',
    'ReportResult',
    'SourceAdapter',
    'SourceContext',
    'TargetAdapter',
    'TargetContext',
]
