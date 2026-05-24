from __future__ import annotations

from dataclasses import dataclass
import platform

from calcchain_plugin_system.api import PLUGIN_API_VERSION
from calcchain_plugin_system.diagnostics import PluginDiagnostic
from calcchain_plugin_system.errors import PluginError
from calcchain_plugin_system.metadata import DeclaredCapability, PluginPackage, PluginValidator
from calcchain_plugin_system.repository import PluginRepository
from calcchain_plugin_system.settings import PluginSettings


@dataclass(frozen=True)
class PlannedCapabilityDeclaration:
    plugin_id: str
    namespace: str
    id: str

    @classmethod
    def from_declared(
        cls,
        plugin_id: str,
        capability: DeclaredCapability,
    ) -> PlannedCapabilityDeclaration:
        return cls(plugin_id=plugin_id, namespace=capability.namespace, id=capability.id)

    @property
    def qualified_id(self) -> str:
        return f'{self.namespace}:{self.id}'


@dataclass(frozen=True)
class PluginActivationPlan:
    enabled_packages: tuple[PluginPackage, ...]
    diagnostics: tuple[PluginDiagnostic, ...]
    plugin_api_version: str
    python_version: str
    declared_capabilities: tuple[PlannedCapabilityDeclaration, ...]

    @property
    def enabled_plugin_ids(self) -> tuple[str, ...]:
        return tuple(package.metadata.plugin_id for package in self.enabled_packages)

    @property
    def has_errors(self) -> bool:
        return bool(self.diagnostics)


class PluginActivationPlanner:
    def __init__(
        self,
        *,
        plugin_api_version: str = PLUGIN_API_VERSION,
        python_version: str | None = None,
        validator: PluginValidator | None = None,
    ) -> None:
        self._plugin_api_version = plugin_api_version
        self._python_version = python_version or platform.python_version()
        self._validator = validator or PluginValidator()

    def plan(self, repository: PluginRepository, settings: PluginSettings) -> PluginActivationPlan:
        diagnostics: list[PluginDiagnostic] = []
        enabled_packages: list[PluginPackage] = []
        declared_capabilities: list[PlannedCapabilityDeclaration] = []
        seen_enabled: set[str] = set()

        for plugin_id in settings.enabled_plugins:
            if plugin_id in seen_enabled:
                diagnostics.append(_diagnostic_duplicate_enabled(plugin_id))
                continue
            seen_enabled.add(plugin_id)

            package = repository.get(plugin_id)
            if package is None:
                diagnostics.append(_diagnostic_missing_plugin(plugin_id))
                continue

            try:
                self._validator.validate_compatibility(
                    package.metadata,
                    plugin_api_version=self._plugin_api_version,
                    python_version=self._python_version,
                )
            except PluginError as exc:
                diagnostics.append(exc.diagnostic)

            enabled_packages.append(package)
            for capability in package.metadata.declared_capabilities:
                declared_capabilities.append(
                    PlannedCapabilityDeclaration.from_declared(plugin_id, capability),
                )

        diagnostics.extend(_diagnose_declared_capability_conflicts(declared_capabilities))
        return PluginActivationPlan(
            enabled_packages=tuple(enabled_packages),
            diagnostics=tuple(diagnostics),
            plugin_api_version=self._plugin_api_version,
            python_version=self._python_version,
            declared_capabilities=tuple(declared_capabilities),
        )


def _diagnostic_missing_plugin(plugin_id: str) -> PluginDiagnostic:
    return PluginDiagnostic.create(
        plugin_id=plugin_id,
        phase='dependency_plan',
        code='plugin_enabled_id_missing',
        message='Enabled plugin is not installed',
        safe_details={'plugin_id': plugin_id},
    )


def _diagnostic_duplicate_enabled(plugin_id: str) -> PluginDiagnostic:
    return PluginDiagnostic.create(
        plugin_id=plugin_id,
        phase='dependency_plan',
        code='plugin_enabled_id_duplicate',
        message='Enabled plugin id is duplicated',
        safe_details={'plugin_id': plugin_id},
    )


def _diagnose_declared_capability_conflicts(
    declared_capabilities: list[PlannedCapabilityDeclaration],
) -> tuple[PluginDiagnostic, ...]:
    diagnostics: list[PluginDiagnostic] = []
    owners_by_capability: dict[tuple[str, str], PlannedCapabilityDeclaration] = {}
    for capability in declared_capabilities:
        key = (capability.namespace, capability.id)
        existing = owners_by_capability.get(key)
        if existing is None:
            owners_by_capability[key] = capability
            continue
        diagnostics.append(
            PluginDiagnostic.create(
                plugin_id=capability.plugin_id,
                phase='dependency_plan',
                code='plugin_declared_capability_conflict',
                message='Declared plugin capability conflicts with another enabled plugin',
                safe_details={
                    'namespace': capability.namespace,
                    'id': capability.id,
                    'plugin_id': capability.plugin_id,
                    'existing_plugin_id': existing.plugin_id,
                },
            ),
        )
    return tuple(diagnostics)


__all__ = [
    'PlannedCapabilityDeclaration',
    'PluginActivationPlan',
    'PluginActivationPlanner',
]
