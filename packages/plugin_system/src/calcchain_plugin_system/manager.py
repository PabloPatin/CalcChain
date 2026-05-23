from typing import Mapping

from calcchain_capabilities import RuntimeCapabilities, create_plugin_context
from calcchain_plugin_system.activation_plan import (
    PlannedCapabilityDeclaration,
    PluginActivationPlan,
)
from calcchain_capabilities.diagnostics import PluginDiagnostic
from calcchain_plugin_system.environment import PluginEnvironment
from calcchain_capabilities.errors import PluginActivationError, PluginError
from calcchain_plugin_system.importer import PluginImporter
from calcchain_plugin_system.metadata import PluginPackage
from calcchain_capabilities.registrars import (
    CapabilityKey,
    CapabilityRecord,
    CapabilityRegistry,
)

_ALLOWED_CAPABILITY_NAMESPACES = frozenset({'source', 'target', 'report', 'auth'})


class PluginManager:
    def __init__(self, *, importer: PluginImporter | None = None) -> None:
        self._importer = importer or PluginImporter()
        self._active_set: RuntimeCapabilities | None = None

    @property
    def active_set(self) -> RuntimeCapabilities | None:
        return self._active_set

    def activate(
        self,
        plan: PluginActivationPlan,
        environment: PluginEnvironment,
    ) -> RuntimeCapabilities:
        if plan.has_errors:
            raise PluginActivationError(
                'Plugin activation plan contains diagnostics',
                phase='activation_commit',
                code='plugin_activation_plan_invalid',
                safe_details={'diagnostic_count': len(plan.diagnostics)},
            )

        draft_registry = CapabilityRegistry()
        for package in plan.enabled_packages:
            plugin = self._importer.import_plugin(package, environment)
            context, _ = create_plugin_context(
                owner=package.metadata.plugin_id,
                registry=draft_registry,
            )
            try:
                plugin.register(context)
            except PluginError:
                raise
            except Exception as exc:
                raise PluginActivationError(
                    'Plugin register(context) failed',
                    plugin_id=package.metadata.plugin_id,
                    phase='capability_registration',
                    code='plugin_register_failed',
                    safe_details={
                        'plugin_id': package.metadata.plugin_id,
                        'error': str(exc),
                    },
                ) from exc

        snapshot = draft_registry.snapshot()
        _validate_capability_snapshot(snapshot, plan)
        runtime_set = RuntimeCapabilities(
            active_plugin_ids=plan.enabled_plugin_ids,
            environment=environment,
            capabilities=snapshot,
            diagnostics=plan.diagnostics,
        )
        self._active_set = runtime_set
        return runtime_set


def _validate_capability_snapshot(
    snapshot: Mapping[CapabilityKey, CapabilityRecord],
    plan: PluginActivationPlan,
) -> None:
    enabled_plugin_ids = set(plan.enabled_plugin_ids)
    actual_by_plugin: dict[str, set[tuple[str, str]]] = {
        plugin_id: set() for plugin_id in enabled_plugin_ids
    }
    for key, record in snapshot.items():
        owner_id = record.owner_id
        if key.namespace not in _ALLOWED_CAPABILITY_NAMESPACES:
            raise PluginActivationError(
                'Registered capability namespace is unsupported',
                plugin_id=owner_id,
                phase='activation_commit',
                code='plugin_capability_namespace_unsupported',
                safe_details={'namespace': key.namespace, 'id': key.id, 'owner': owner_id},
            )
        if not owner_id:
            raise PluginActivationError(
                'Registered capability owner is missing',
                phase='activation_commit',
                code='plugin_capability_owner_missing',
                safe_details={'namespace': key.namespace, 'id': key.id},
            )
        if owner_id not in enabled_plugin_ids:
            raise PluginActivationError(
                'Registered capability owner is not in active plugin set',
                plugin_id=owner_id,
                phase='activation_commit',
                code='plugin_capability_owner_unknown',
                safe_details={'namespace': key.namespace, 'id': key.id, 'owner': owner_id},
            )
        if record.key != key:
            raise PluginActivationError(
                'Registered capability key does not match snapshot key',
                plugin_id=owner_id,
                phase='activation_commit',
                code='plugin_capability_key_mismatch',
                safe_details={'namespace': key.namespace, 'id': key.id, 'owner': owner_id},
            )
        actual_by_plugin[owner_id].add((key.namespace, key.id))

    declared_by_plugin = _declared_capabilities_by_plugin(plan)
    for package in plan.enabled_packages:
        declared = declared_by_plugin.get(package.metadata.plugin_id, set())
        if not package.metadata.declared_capabilities:
            continue
        actual = actual_by_plugin.get(package.metadata.plugin_id, set())
        if actual != declared:
            raise PluginActivationError(
                'Declared plugin capabilities do not match registered capabilities',
                plugin_id=package.metadata.plugin_id,
                phase='activation_commit',
                code='plugin_declared_capabilities_mismatch',
                safe_details={
                    'plugin_id': package.metadata.plugin_id,
                    'declared': _qualified_capabilities(declared),
                    'actual': _qualified_capabilities(actual),
                },
            )


def _declared_capabilities_by_plugin(
    plan: PluginActivationPlan,
) -> dict[str, set[tuple[str, str]]]:
    capabilities: dict[str, set[tuple[str, str]]] = {}
    for declaration in plan.declared_capabilities:
        capabilities.setdefault(declaration.plugin_id, set()).add(
            _declaration_key(declaration),
        )
    return capabilities


def _declaration_key(declaration: PlannedCapabilityDeclaration) -> tuple[str, str]:
    return declaration.namespace, declaration.id


def _qualified_capabilities(capabilities: set[tuple[str, str]]) -> tuple[str, ...]:
    return tuple(f'{namespace}:{id}' for namespace, id in sorted(capabilities))


__all__ = ['PluginManager', 'PluginRuntimeSet']
