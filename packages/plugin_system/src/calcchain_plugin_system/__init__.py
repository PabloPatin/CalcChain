from importlib import import_module

_EXPORT_MODULES = {
    'DeclaredCapability': 'calcchain_plugin_system.metadata',
    'PLUGIN_ENV_LOCK_NAME': 'calcchain_plugin_system.environment_lock',
    'PipInstaller': 'calcchain_plugin_system.environment',
    'PlannedCapabilityDeclaration': 'calcchain_plugin_system.activation_plan',
    'PluginActivationError': 'calcchain_capabilities.errors',
    'PluginActivationPlan': 'calcchain_plugin_system.activation_plan',
    'PluginActivationPlanner': 'calcchain_plugin_system.activation_plan',
    'PluginCapabilityConflictError': 'calcchain_capabilities.errors',
    'PluginCompatibilityError': 'calcchain_capabilities.errors',
    'PluginDependencies': 'calcchain_plugin_system.metadata',
    'PluginDependencyError': 'calcchain_capabilities.errors',
    'PluginDependencyPlan': 'calcchain_plugin_system.dependencies',
    'PluginDependencyPlanner': 'calcchain_plugin_system.dependencies',
    'PluginDiagnostic': 'calcchain_capabilities.diagnostics',
    'PluginDiscovery': 'calcchain_plugin_system.discovery',
    'PluginEnvLock': 'calcchain_plugin_system.environment_lock',
    'PluginEnvironment': 'calcchain_plugin_system.environment',
    'PluginEnvironmentManager': 'calcchain_plugin_system.environment',
    'PluginEntrypointError': 'calcchain_capabilities.errors',
    'PluginError': 'calcchain_capabilities.errors',
    'PluginImporter': 'calcchain_plugin_system.importer',
    'PluginManager': 'calcchain_plugin_system.manager',
    'PluginMetadata': 'calcchain_plugin_system.metadata',
    'PluginMetadataError': 'calcchain_capabilities.errors',
    'PluginMetadataReader': 'calcchain_plugin_system.metadata',
    'PluginPackage': 'calcchain_plugin_system.metadata',
    'PluginRegistrationError': 'calcchain_capabilities.errors',
    'PluginRepository': 'calcchain_plugin_system.repository',
    'PluginRuntimeSet': 'calcchain_capabilities',
    'PluginSettings': 'calcchain_plugin_system.settings',
    'PluginSettingsStore': 'calcchain_plugin_system.settings',
    'PluginValidator': 'calcchain_plugin_system.metadata',
    'RequirementRecord': 'calcchain_plugin_system.dependencies',
    'ResolvedDependencies': 'calcchain_plugin_system.environment',
    'WheelLock': 'calcchain_plugin_system.dependencies',
    'WheelLockEntry': 'calcchain_plugin_system.dependencies',
    'WheelLockReader': 'calcchain_plugin_system.dependencies',
    'WheelRecord': 'calcchain_plugin_system.dependencies',
    'activate_plugins': 'calcchain_plugin_system.bootstrap',
    'compute_env_hash': 'calcchain_plugin_system.dependencies',
    'read_plugin_env_lock': 'calcchain_plugin_system.environment_lock',
    'redact_secrets': 'calcchain_capabilities.diagnostics',
    'verify_plugin_env_lock': 'calcchain_plugin_system.environment_lock',
    'verify_wheel_hashes': 'calcchain_plugin_system.dependencies',
    'write_plugin_env_lock': 'calcchain_plugin_system.environment_lock',
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
