from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from calcchain_core.plugins.diagnostics import (
    PLUGIN_DIAGNOSTIC_PHASES,
    PluginDiagnostic,
    PluginDiagnosticPhase,
    redact_secrets,
)
from calcchain_core.plugins.errors import (
    PluginActivationError,
    PluginCapabilityConflictError,
    PluginCompatibilityError,
    PluginDependencyError,
    PluginEntrypointError,
    PluginError,
    PluginMetadataError,
    PluginRegistrationError,
)
from calcchain_core.plugins.registrars import (
    AuthRegistrar,
    CapabilityKey,
    CapabilityRecord,
    CapabilityRegistrar,
    CapabilityRegistry,
    ReportRegistrar,
    SourceRegistrar,
    TargetRegistrar,
    create_registrar_set,
)

PLUGIN_API_VERSION = '1.0'


@dataclass(frozen=True)
class PluginContext:
    sources: SourceRegistrar
    targets: TargetRegistrar
    reports: ReportRegistrar
    auth: AuthRegistrar


class CalcChainPlugin(Protocol):
    plugin_id: str
    plugin_version: str

    def register(self, context: PluginContext) -> None:
        """Register plugin capabilities through the provided limited context."""


def create_plugin_context(
    *,
    owner: str | None = None,
    registry: CapabilityRegistry | None = None,
) -> tuple[PluginContext, CapabilityRegistry]:
    capability_registry, sources, targets, reports, auth = create_registrar_set(
        owner=owner,
        registry=registry,
    )
    return (
        PluginContext(sources=sources, targets=targets, reports=reports, auth=auth),
        capability_registry,
    )


__all__ = [
    'PLUGIN_API_VERSION',
    'PLUGIN_DIAGNOSTIC_PHASES',
    'AuthRegistrar',
    'CalcChainPlugin',
    'CapabilityKey',
    'CapabilityRecord',
    'CapabilityRegistrar',
    'CapabilityRegistry',
    'PluginActivationError',
    'PluginCapabilityConflictError',
    'PluginCompatibilityError',
    'PluginContext',
    'PluginDependencyError',
    'PluginDiagnostic',
    'PluginDiagnosticPhase',
    'PluginEntrypointError',
    'PluginError',
    'PluginMetadataError',
    'PluginRegistrationError',
    'ReportRegistrar',
    'SourceRegistrar',
    'TargetRegistrar',
    'create_plugin_context',
    'redact_secrets',
]
