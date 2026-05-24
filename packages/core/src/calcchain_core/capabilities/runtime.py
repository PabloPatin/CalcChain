from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True)
class CapabilityKey:
    namespace: str
    id: str

    def __post_init__(self) -> None:
        if not isinstance(self.namespace, str) or not self.namespace:
            raise ValueError('capability namespace must be a non-empty string')
        if not isinstance(self.id, str) or not self.id:
            raise ValueError('capability id must be a non-empty string')

    @property
    def qualified_id(self) -> str:
        return f'{self.namespace}:{self.id}'


@dataclass(frozen=True)
class CapabilityOwner:
    id: str
    version: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id:
            raise ValueError('capability owner id must be a non-empty string')
        object.__setattr__(self, 'metadata', MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True)
class CapabilityRecord:
    key: CapabilityKey
    adapter: object
    owner: CapabilityOwner | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, 'metadata', MappingProxyType(dict(self.metadata)))

    @property
    def capability(self) -> object:
        return self.adapter

    @property
    def capability_id(self) -> str:
        return self.key.id

    @property
    def owner_id(self) -> str | None:
        return self.owner.id if self.owner is not None else None

    @property
    def owner_version(self) -> str | None:
        return self.owner.version if self.owner is not None else None


@dataclass(frozen=True)
class ResolvedCredentials:
    public: Mapping[str, str] = field(default_factory=dict)
    secrets: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, 'public', MappingProxyType(dict(self.public)))
        object.__setattr__(self, 'secrets', MappingProxyType(dict(self.secrets)))

    def to_dict(self) -> dict[str, dict[str, str]]:
        result: dict[str, dict[str, str]] = {}
        if self.public:
            result['public'] = dict(self.public)
        if self.secrets:
            result['secrets'] = dict(self.secrets)
        return result


@dataclass(frozen=True)
class CapabilityDiagnostic:
    level: str
    message: str
    owner: CapabilityOwner | None = None
    capability: CapabilityKey | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.level not in {'info', 'warning', 'error'}:
            raise ValueError('capability diagnostic level must be info, warning or error')
        if not isinstance(self.message, str) or not self.message:
            raise ValueError('capability diagnostic message must be a non-empty string')
        object.__setattr__(self, 'details', MappingProxyType(dict(self.details)))


@dataclass(frozen=True)
class SourceContext:
    owner: CapabilityOwner | None
    capability_id: str
    credentials: ResolvedCredentials = field(default_factory=ResolvedCredentials)

    @property
    def owner_id(self) -> str | None:
        return self.owner.id if self.owner is not None else None

    @property
    def owner_version(self) -> str | None:
        return self.owner.version if self.owner is not None else None


@dataclass(frozen=True)
class TargetContext:
    owner: CapabilityOwner | None
    capability_id: str
    credentials: ResolvedCredentials = field(default_factory=ResolvedCredentials)

    @property
    def owner_id(self) -> str | None:
        return self.owner.id if self.owner is not None else None

    @property
    def owner_version(self) -> str | None:
        return self.owner.version if self.owner is not None else None


@dataclass(frozen=True)
class SecretsContext:
    owner: CapabilityOwner | None
    capability_id: str
    request_context: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, 'request_context', MappingProxyType(dict(self.request_context)))

    @property
    def owner_id(self) -> str | None:
        return self.owner.id if self.owner is not None else None

    @property
    def owner_version(self) -> str | None:
        return self.owner.version if self.owner is not None else None


@dataclass(frozen=True)
class RuntimeCapabilities:
    capabilities: Mapping[CapabilityKey, CapabilityRecord] = field(default_factory=dict)
    active_owner_ids: tuple[str, ...] = ()
    environment: object | None = None
    diagnostics: tuple[CapabilityDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, 'capabilities', MappingProxyType(dict(self.capabilities)))
        object.__setattr__(self, 'active_owner_ids', tuple(self.active_owner_ids))
        object.__setattr__(self, 'diagnostics', tuple(self.diagnostics))
