from __future__ import annotations

from importlib import import_module

_EXPORT_MODULES = {
    'DeclaredCapability': 'calcchain_core.plugins.metadata',
    'PLUGIN_ENV_LOCK_NAME': 'calcchain_core.plugins.environment_lock',
    'PipInstaller': 'calcchain_core.plugins.environment',
    'PlannedCapabilityDeclaration': 'calcchain_core.plugins.activation_plan',
    'PluginActivationError': 'calcchain_core.plugins.errors',
    'PluginActivationPlan': 'calcchain_core.plugins.activation_plan',
    'PluginActivationPlanner': 'calcchain_core.plugins.activation_plan',
    'PluginCapabilityConflictError': 'calcchain_core.plugins.errors',
    'PluginCompatibilityError': 'calcchain_core.plugins.errors',
    'PluginDependencies': 'calcchain_core.plugins.metadata',
    'PluginDependencyError': 'calcchain_core.plugins.errors',
    'PluginDependencyPlan': 'calcchain_core.plugins.dependencies',
    'PluginDependencyPlanner': 'calcchain_core.plugins.dependencies',
    'PluginDiagnostic': 'calcchain_core.plugins.diagnostics',
    'PluginDiscovery': 'calcchain_core.plugins.discovery',
    'PluginEnvLock': 'calcchain_core.plugins.environment_lock',
    'PluginEnvironment': 'calcchain_core.plugins.environment',
    'PluginEnvironmentManager': 'calcchain_core.plugins.environment',
    'PluginEntrypointError': 'calcchain_core.plugins.errors',
    'PluginError': 'calcchain_core.plugins.errors',
    'PluginImporter': 'calcchain_core.plugins.importer',
    'PluginManager': 'calcchain_core.plugins.manager',
    'PluginMetadata': 'calcchain_core.plugins.metadata',
    'PluginMetadataError': 'calcchain_core.plugins.errors',
    'PluginMetadataReader': 'calcchain_core.plugins.metadata',
    'PluginPackage': 'calcchain_core.plugins.metadata',
    'PluginRegistrationError': 'calcchain_core.plugins.errors',
    'PluginRepository': 'calcchain_core.plugins.repository',
    'PluginRuntimeSet': 'calcchain_core.plugins.manager',
    'PluginSettings': 'calcchain_core.plugins.settings',
    'PluginSettingsStore': 'calcchain_core.plugins.settings',
    'PluginValidator': 'calcchain_core.plugins.metadata',
    'RequirementRecord': 'calcchain_core.plugins.dependencies',
    'ResolvedDependencies': 'calcchain_core.plugins.environment',
    'WheelLock': 'calcchain_core.plugins.dependencies',
    'WheelLockEntry': 'calcchain_core.plugins.dependencies',
    'WheelLockReader': 'calcchain_core.plugins.dependencies',
    'WheelRecord': 'calcchain_core.plugins.dependencies',
    'activate_plugins': 'calcchain_core.plugins.bootstrap',
    'compute_env_hash': 'calcchain_core.plugins.dependencies',
    'read_plugin_env_lock': 'calcchain_core.plugins.environment_lock',
    'redact_secrets': 'calcchain_core.plugins.diagnostics',
    'verify_plugin_env_lock': 'calcchain_core.plugins.environment_lock',
    'verify_wheel_hashes': 'calcchain_core.plugins.dependencies',
    'write_plugin_env_lock': 'calcchain_core.plugins.environment_lock',
}

__all__ = sorted(_EXPORT_MODULES)


def __getattr__(name: str) -> object:
    try:
        module_name = _EXPORT_MODULES[name]
    except KeyError as exc:
        raise AttributeError(f'module {__name__!r} has no attribute {name!r}') from exc
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value
