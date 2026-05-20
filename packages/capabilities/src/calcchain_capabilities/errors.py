from typing import ClassVar, Mapping

from calcchain_capabilities.diagnostics import PluginDiagnostic, PluginDiagnosticPhase


class PluginError(Exception):
    default_code: ClassVar[str] = 'plugin_error'
    default_phase: ClassVar[PluginDiagnosticPhase] = 'activation_commit'

    def __init__(
        self,
        message: str,
        *,
        plugin_id: str | None = None,
        phase: PluginDiagnosticPhase | None = None,
        code: str | None = None,
        safe_details: Mapping[str, object] | None = None,
        secret_values: tuple[str, ...] | list[str] = (),
    ) -> None:
        self.diagnostic = PluginDiagnostic.create(
            plugin_id=plugin_id,
            phase=phase or self.default_phase,
            code=code or self.default_code,
            message=message,
            safe_details=safe_details,
            secret_values=secret_values,
        )
        super().__init__(self.diagnostic.message)


class PluginMetadataError(PluginError):
    default_code = 'plugin_metadata_error'
    default_phase = 'metadata_validation'


class PluginCompatibilityError(PluginError):
    default_code = 'plugin_compatibility_error'
    default_phase = 'compatibility_check'


class PluginDependencyError(PluginError):
    default_code = 'plugin_dependency_error'
    default_phase = 'dependency_plan'


class PluginEntrypointError(PluginError):
    default_code = 'plugin_entrypoint_error'
    default_phase = 'entrypoint_import'


class PluginActivationError(PluginError):
    default_code = 'plugin_activation_error'
    default_phase = 'activation_commit'


class PluginRegistrationError(PluginError):
    default_code = 'plugin_registration_error'
    default_phase = 'capability_registration'


class PluginCapabilityConflictError(PluginRegistrationError):
    default_code = 'plugin_capability_conflict'


__all__ = [
    'PluginActivationError',
    'PluginCapabilityConflictError',
    'PluginCompatibilityError',
    'PluginDependencyError',
    'PluginEntrypointError',
    'PluginError',
    'PluginMetadataError',
    'PluginRegistrationError',
]
