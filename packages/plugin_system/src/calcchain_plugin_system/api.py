from dataclasses import dataclass
from typing import Protocol

from calcchain_core.capabilities import (
    CapabilityKey,
    CapabilityOwner,
    CapabilityRecord,
    ReportAdapter,
    RuntimeCapabilities,
    SecretsAdapter,
    SecretsContext,
    SourceAdapter,
    SourceContext,
    TargetAdapter,
    TargetContext,
)
from calcchain_core.io.target import PublishedRef
from calcchain_core.reports import (
    ReportContext,
    ReportDescriptor,
    ReportRequest,
    ReportResult,
)
from calcchain_plugin_system.diagnostics import (
    PLUGIN_DIAGNOSTIC_PHASES,
    PluginDiagnostic,
    PluginDiagnosticPhase,
    redact_secrets,
)
from calcchain_plugin_system.errors import (
    PluginActivationError,
    PluginCapabilityConflictError,
    PluginCompatibilityError,
    PluginDependencyError,
    PluginEntrypointError,
    PluginError,
    PluginMetadataError,
    PluginRegistrationError,
)
from calcchain_plugin_system.registrars import (
    CapabilityRegistrar,
    CapabilityRegistry,
    ReportRegistrar,
    SecretsRegistrar,
    SourceRegistrar,
    TargetRegistrar,
    create_registrar_set,
)

PLUGIN_API_VERSION = '1.0'
PluginRuntimeSet = RuntimeCapabilities


@dataclass(frozen=True)
class PluginContext:
    sources: SourceRegistrar
    targets: TargetRegistrar
    reports: ReportRegistrar
    secrets: SecretsRegistrar


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
    capability_registry, sources, targets, reports, secrets = create_registrar_set(
        owner=owner,
        registry=registry,
    )
    return (
        PluginContext(sources=sources, targets=targets, reports=reports, secrets=secrets),
        capability_registry,
    )


__all__ = [
    'PLUGIN_API_VERSION',
    'PLUGIN_DIAGNOSTIC_PHASES',
    'CalcChainPlugin',
    'CapabilityKey',
    'CapabilityOwner',
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
    'PluginRuntimeSet',
    'PublishedRef',
    'ReportAdapter',
    'ReportContext',
    'ReportDescriptor',
    'ReportRequest',
    'ReportResult',
    'ReportRegistrar',
    'RuntimeCapabilities',
    'SecretsAdapter',
    'SecretsContext',
    'SecretsRegistrar',
    'SourceAdapter',
    'SourceContext',
    'SourceRegistrar',
    'TargetAdapter',
    'TargetContext',
    'TargetRegistrar',
    'create_plugin_context',
    'redact_secrets',
]
