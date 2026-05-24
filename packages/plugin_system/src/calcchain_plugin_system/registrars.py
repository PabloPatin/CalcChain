from dataclasses import dataclass
from types import MappingProxyType
from typing import ClassVar, Mapping, Protocol

from calcchain_core.capabilities import CapabilityKey, CapabilityOwner, CapabilityRecord
from calcchain_plugin_system.errors import PluginCapabilityConflictError, PluginRegistrationError
from calcchain_plugin_system.types import CapabilityType


class CapabilityRegistrar(Protocol):
    def register(self, id: str, capability: object, *, owner: str) -> None:
        """Register one capability owned by a plugin."""


@dataclass(frozen=True)
class RegisteredCapability:
    key: CapabilityKey
    adapter: object
    owner: CapabilityOwner

    def to_record(self) -> CapabilityRecord:
        return CapabilityRecord(key=self.key, adapter=self.adapter, owner=self.owner)


class CapabilityRegistry:
    def __init__(self) -> None:
        self._records: dict[CapabilityKey, CapabilityRecord] = {}

    def register(self, namespace: CapabilityType | str, id: str, adapter: object, *, owner: str) -> None:
        if not owner:
            raise PluginRegistrationError(
                'Capability owner is required',
                safe_details={'namespace': namespace, 'id': id},
            )
        try:
            normalized_namespace = CapabilityType(namespace).value
        except ValueError as err:
            raise PluginRegistrationError(
                'Unknown capability namespace',
                safe_details={'namespace': namespace, 'id': id},
            ) from err
        if not isinstance(id, str) or not id:
            raise PluginRegistrationError('Capability id is required')
        key = CapabilityKey(namespace=normalized_namespace, id=id)
        if key in self._records:
            existing = self._records[key]
            raise PluginCapabilityConflictError(
                f'Capability {key.qualified_id} is already registered',
                safe_details={
                    'namespace': normalized_namespace,
                    'id': id,
                    'owner': owner,
                    'existing_owner': existing.owner,
                },
            )
        self._records[key] = CapabilityRecord(key=key, adapter=adapter, owner=CapabilityOwner(owner))

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


class SecretsRegistrar(BaseRegistrar):
    namespace = 'secrets'


def create_registrar_set(
    *,
    owner: str | None = None,
    registry: CapabilityRegistry | None = None,
) -> tuple[
    CapabilityRegistry,
    SourceRegistrar,
    TargetRegistrar,
    ReportRegistrar,
    SecretsRegistrar,
]:
    capability_registry = registry or CapabilityRegistry()
    return (
        capability_registry,
        SourceRegistrar(capability_registry, owner=owner),
        TargetRegistrar(capability_registry, owner=owner),
        ReportRegistrar(capability_registry, owner=owner),
        SecretsRegistrar(capability_registry, owner=owner),
    )


__all__ = [
    'BaseRegistrar',
    'CapabilityKey',
    'CapabilityOwner',
    'CapabilityRecord',
    'CapabilityRegistrar',
    'CapabilityRegistry',
    'ReportRegistrar',
    'SecretsRegistrar',
    'SourceRegistrar',
    'TargetRegistrar',
    'create_registrar_set',
]
