from contextlib import contextmanager
import importlib
from pathlib import Path
import sys
from typing import Iterator, cast

from calcchain_capabilities import CalcChainPlugin
from calcchain_plugin_system.environment import PluginEnvironment
from calcchain_plugin_system.environment_lock import verify_plugin_env_lock
from calcchain_capabilities.errors import (
    PluginActivationError,
    PluginDependencyError,
    PluginEntrypointError,
)
from calcchain_plugin_system.metadata import PluginPackage


class PluginImporter:
    def import_plugin(
        self,
        package: PluginPackage,
        environment: PluginEnvironment,
    ) -> CalcChainPlugin:
        module_name, class_name = _parse_entrypoint(package)
        _verify_environment_ready(environment)
        with (
            _import_context(package.root, environment.site_packages),
            _entrypoint_module_context(module_name),
        ):
            try:
                module = importlib.import_module(module_name)
            except Exception as exc:
                raise PluginEntrypointError(
                    'Plugin entrypoint module import failed',
                    plugin_id=package.metadata.plugin_id,
                    phase='entrypoint_import',
                    code='plugin_entrypoint_import_failed',
                    safe_details={
                        'plugin_id': package.metadata.plugin_id,
                        'entrypoint': package.metadata.entrypoint,
                        'error': str(exc),
                    },
                ) from exc
            try:
                plugin_type = getattr(module, class_name)
            except AttributeError as exc:
                raise PluginEntrypointError(
                    'Plugin entrypoint class was not found',
                    plugin_id=package.metadata.plugin_id,
                    phase='entrypoint_import',
                    code='plugin_entrypoint_class_missing',
                    safe_details={
                        'plugin_id': package.metadata.plugin_id,
                        'entrypoint': package.metadata.entrypoint,
                    },
                ) from exc
            if not callable(plugin_type):
                raise PluginEntrypointError(
                    'Plugin entrypoint is not callable',
                    plugin_id=package.metadata.plugin_id,
                    phase='entrypoint_import',
                    code='plugin_entrypoint_not_callable',
                    safe_details={
                        'plugin_id': package.metadata.plugin_id,
                        'entrypoint': package.metadata.entrypoint,
                    },
                )
            try:
                plugin = plugin_type()
            except Exception as exc:
                raise PluginActivationError(
                    'Plugin instantiation failed',
                    plugin_id=package.metadata.plugin_id,
                    phase='plugin_instantiate',
                    code='plugin_instantiate_failed',
                    safe_details={
                        'plugin_id': package.metadata.plugin_id,
                        'entrypoint': package.metadata.entrypoint,
                        'error': str(exc),
                    },
                ) from exc

        _validate_plugin_object(plugin, package)
        return cast(CalcChainPlugin, plugin)


def _parse_entrypoint(package: PluginPackage) -> tuple[str, str]:
    module_name, separator, class_name = package.metadata.entrypoint.partition(':')
    if not module_name or separator != ':' or not class_name or ':' in class_name:
        raise PluginEntrypointError(
            'Plugin entrypoint must use module.path:ClassName format',
            plugin_id=package.metadata.plugin_id,
            phase='entrypoint_import',
            code='plugin_entrypoint_invalid',
            safe_details={
                'plugin_id': package.metadata.plugin_id,
                'entrypoint': package.metadata.entrypoint,
            },
        )
    return module_name, class_name


def _validate_plugin_object(plugin: object, package: PluginPackage) -> None:
    plugin_id = getattr(plugin, 'plugin_id', None)
    plugin_version = getattr(plugin, 'plugin_version', None)
    register = getattr(plugin, 'register', None)
    if plugin_id != package.metadata.plugin_id:
        raise PluginActivationError(
            'Plugin object id does not match metadata',
            plugin_id=package.metadata.plugin_id,
            phase='plugin_instantiate',
            code='plugin_id_mismatch',
            safe_details={
                'expected_plugin_id': package.metadata.plugin_id,
                'actual_plugin_id': plugin_id,
            },
        )
    if plugin_version != package.metadata.plugin_version:
        raise PluginActivationError(
            'Plugin object version does not match metadata',
            plugin_id=package.metadata.plugin_id,
            phase='plugin_instantiate',
            code='plugin_version_mismatch',
            safe_details={
                'plugin_id': package.metadata.plugin_id,
                'expected_plugin_version': package.metadata.plugin_version,
                'actual_plugin_version': plugin_version,
            },
        )
    if not callable(register):
        raise PluginActivationError(
            'Plugin object must expose callable register(context)',
            plugin_id=package.metadata.plugin_id,
            phase='plugin_instantiate',
            code='plugin_register_missing',
            safe_details={'plugin_id': package.metadata.plugin_id},
        )


def _verify_environment_ready(environment: PluginEnvironment) -> None:
    if not environment.site_packages.is_dir():
        raise PluginDependencyError(
            'Plugin environment site-packages directory is missing',
            phase='dependency_install',
            code='plugin_environment_not_ready',
            safe_details={
                'env_hash': environment.env_hash,
                'site_packages': str(environment.site_packages),
            },
        )
    try:
        verify_plugin_env_lock(environment.root, environment.env_hash)
    except PluginDependencyError as exc:
        raise PluginDependencyError(
            'Plugin environment lock is not ready',
            phase='dependency_install',
            code=exc.diagnostic.code,
            safe_details=exc.diagnostic.safe_details,
        ) from exc


@contextmanager
def _import_context(package_root: Path, site_packages: Path) -> Iterator[None]:
    original_path = list(sys.path)
    try:
        sys.path = [str(package_root), str(site_packages), *original_path]
        importlib.invalidate_caches()
        yield
    finally:
        sys.path = original_path
        importlib.invalidate_caches()


@contextmanager
def _entrypoint_module_context(module_name: str) -> Iterator[None]:
    root_module = module_name.split('.', maxsplit=1)[0]
    module_names = _module_namespace_entries(root_module)
    previous_modules = {
        name: sys.modules[name]
        for name in module_names
        if name in sys.modules
    }
    _remove_module_namespace(root_module)
    try:
        importlib.invalidate_caches()
        yield
    finally:
        _remove_module_namespace(root_module)
        for name in module_names:
            if name in previous_modules:
                sys.modules[name] = previous_modules[name]
        importlib.invalidate_caches()


def _module_namespace_entries(root_module: str) -> tuple[str, ...]:
    prefix = f'{root_module}.'
    return tuple(
        name
        for name in sys.modules
        if name == root_module or name.startswith(prefix)
    )


def _remove_module_namespace(root_module: str) -> None:
    for name in reversed(_module_namespace_entries(root_module)):
        sys.modules.pop(name, None)


__all__ = ['PluginImporter']
