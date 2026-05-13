from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import ClassVar, Mapping, Protocol

from calcchain_core.plugins.errors import PluginCapabilityConflictError, PluginRegistrationError


@dataclass(frozen=True)
class CapabilityKey:
    namespace: str
    id: str

    def __post_init__(self) -> None:
        if not self.namespace:
            raise PluginRegistrationError('Capability namespace is required')
        if not self.id:
            raise PluginRegistrationError('Capability id is required')

    @property
    def qualified_id(self) -> str:
        return f'{self.namespace}:{self.id}'


@dataclass(frozen=True)
class CapabilityRecord:
    key: CapabilityKey
    capability: object
    owner: str


class CapabilityRegistrar(Protocol):
    def register(self, id: str, capability: object, *, owner: str) -> None:
        """Register one capability owned by a plugin."""


class CapabilityRegistry:
    def __init__(self) -> None:
        self._records: dict[CapabilityKey, CapabilityRecord] = {}

    def register(self, namespace: str, id: str, capability: object, *, owner: str) -> None:
        if not owner:
            raise PluginRegistrationError(
                'Capability owner is required',
                safe_details={'namespace': namespace, 'id': id},
            )
        key = CapabilityKey(namespace=namespace, id=id)
        if key in self._records:
            existing = self._records[key]
            raise PluginCapabilityConflictError(
                f'Capability {key.qualified_id} is already registered',
                safe_details={
                    'namespace': namespace,
                    'id': id,
                    'owner': owner,
                    'existing_owner': existing.owner,
                },
            )
        self._records[key] = CapabilityRecord(key=key, capability=capability, owner=owner)

    def snapshot(self) -> Mapping[CapabilityKey, CapabilityRecord]:
        return MappingProxyType(dict(self._records))


class BaseRegistrar:
    namespace: ClassVar[str]

    def __init__(self, registry: CapabilityRegistry, *, owner: str | None = None) -> None:
        self._registry = registry
        self._owner = owner

    def register(self, id: str, capability: object, *, owner: str) -> None:
        if self._owner is not None and owner != self._owner:
            raise PluginRegistrationError(
                'Capability owner does not match registrar owner',
                safe_details={
                    'namespace': self.namespace,
                    'id': id,
                    'owner': owner,
                    'expected_owner': self._owner,
                },
            )
        self._registry.register(self.namespace, id, capability, owner=owner)


class SourceRegistrar(BaseRegistrar):
    namespace = 'source'


class TargetRegistrar(BaseRegistrar):
    namespace = 'target'


class ReportRegistrar(BaseRegistrar):
    namespace = 'report'


class AuthRegistrar(BaseRegistrar):
    namespace = 'auth'


def create_registrar_set(
    *,
    owner: str | None = None,
    registry: CapabilityRegistry | None = None,
) -> tuple[
    CapabilityRegistry,
    SourceRegistrar,
    TargetRegistrar,
    ReportRegistrar,
    AuthRegistrar,
]:
    capability_registry = registry or CapabilityRegistry()
    return (
        capability_registry,
        SourceRegistrar(capability_registry, owner=owner),
        TargetRegistrar(capability_registry, owner=owner),
        ReportRegistrar(capability_registry, owner=owner),
        AuthRegistrar(capability_registry, owner=owner),
    )


__all__ = [
    'AuthRegistrar',
    'BaseRegistrar',
    'CapabilityKey',
    'CapabilityRecord',
    'CapabilityRegistrar',
    'CapabilityRegistry',
    'ReportRegistrar',
    'SourceRegistrar',
    'TargetRegistrar',
    'create_registrar_set',
]
