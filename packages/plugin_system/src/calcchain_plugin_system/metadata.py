from __future__ import annotations

from dataclasses import dataclass, field
import json
from json import JSONDecodeError
from pathlib import Path, PurePosixPath
import platform
from typing import Any, Mapping

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from calcchain_capabilities import PLUGIN_API_VERSION
from calcchain_capabilities.errors import PluginCompatibilityError, PluginMetadataError

_ALLOWED_CAPABILITY_NAMESPACES = frozenset({'source', 'target', 'report', 'auth'})
_SUPPORTED_DEPENDENCY_MODE = 'wheels'


@dataclass(frozen=True)
class PluginDependencies:
    mode: str
    wheels_path: str
    requirements: str

    @classmethod
    def from_dict(cls, data: object) -> PluginDependencies:
        if not isinstance(data, Mapping):
            raise _metadata_error('dependencies must be an object', field='dependencies')
        return cls(
            mode=_required_str(data, 'mode', parent='dependencies'),
            wheels_path=_required_str(data, 'wheels_path', parent='dependencies'),
            requirements=_required_str(data, 'requirements', parent='dependencies'),
        )


@dataclass(frozen=True)
class DeclaredCapability:
    namespace: str
    id: str

    @classmethod
    def from_dict(cls, data: object) -> DeclaredCapability:
        if not isinstance(data, Mapping):
            raise _metadata_error('declared_capabilities entries must be objects')
        return cls(
            namespace=_required_str(data, 'namespace', parent='declared_capabilities'),
            id=_required_str(data, 'id', parent='declared_capabilities'),
        )


@dataclass(frozen=True)
class PluginMetadata:
    schema_version: str
    plugin_id: str
    plugin_version: str
    requires_plugin_api: str
    python_requires: str
    entrypoint: str
    dependencies: PluginDependencies
    declared_capabilities: tuple[DeclaredCapability, ...] = field(default_factory=tuple)

    @classmethod
    def from_dict(cls, data: object) -> PluginMetadata:
        if not isinstance(data, Mapping):
            raise _metadata_error('plugin metadata must be a JSON object')
        declared = data.get('declared_capabilities', ())
        if declared is None:
            declared = ()
        if not isinstance(declared, list | tuple):
            raise _metadata_error(
                'declared_capabilities must be a list',
                field='declared_capabilities',
            )
        return cls(
            schema_version=_required_str(data, 'schema_version'),
            plugin_id=_required_str(data, 'plugin_id'),
            plugin_version=_required_str(data, 'plugin_version'),
            requires_plugin_api=_required_str(data, 'requires_plugin_api'),
            python_requires=_required_str(data, 'python_requires'),
            entrypoint=_required_str(data, 'entrypoint'),
            dependencies=PluginDependencies.from_dict(data.get('dependencies')),
            declared_capabilities=tuple(
                DeclaredCapability.from_dict(item) for item in declared
            ),
        )


@dataclass(frozen=True)
class PluginPackage:
    root: Path
    metadata_path: Path
    metadata: PluginMetadata


class PluginMetadataReader:
    def read(self, metadata_path: Path) -> PluginMetadata:
        try:
            with metadata_path.open('r', encoding='utf-8') as file:
                data = json.load(file)
        except OSError as exc:
            raise PluginMetadataError(
                'Cannot read plugin metadata',
                phase='metadata_read',
                code='plugin_metadata_read_failed',
                safe_details={'metadata_path': str(metadata_path)},
            ) from exc
        except JSONDecodeError as exc:
            raise PluginMetadataError(
                'Plugin metadata is not valid JSON',
                phase='metadata_read',
                code='plugin_metadata_invalid_json',
                safe_details={'metadata_path': str(metadata_path)},
            ) from exc
        return PluginMetadata.from_dict(data)


class PluginValidator:
    def validate_package(
        self,
        package_root: Path,
        metadata: PluginMetadata,
        *,
        plugin_api_version: str = PLUGIN_API_VERSION,
        python_version: str | None = None,
    ) -> None:
        _validate_version('plugin_version', metadata.plugin_version)
        api_specifier = _validate_specifier('requires_plugin_api', metadata.requires_plugin_api)
        python_specifier = _validate_specifier('python_requires', metadata.python_requires)
        self.validate_compatibility(
            metadata,
            plugin_api_version=plugin_api_version,
            python_version=python_version or platform.python_version(),
            api_specifier=api_specifier,
            python_specifier=python_specifier,
        )
        _validate_dependencies(metadata.dependencies, plugin_id=metadata.plugin_id)
        _validate_declared_capabilities(
            metadata.declared_capabilities,
            plugin_id=metadata.plugin_id,
        )
        _validate_entrypoint(package_root, metadata)

    def validate_compatibility(
        self,
        metadata: PluginMetadata,
        *,
        plugin_api_version: str,
        python_version: str | None = None,
        api_specifier: SpecifierSet | None = None,
        python_specifier: SpecifierSet | None = None,
    ) -> None:
        api_specifier = api_specifier or _validate_specifier(
            'requires_plugin_api',
            metadata.requires_plugin_api,
        )
        python_specifier = python_specifier or _validate_specifier(
            'python_requires',
            metadata.python_requires,
        )
        python_version = python_version or platform.python_version()
        try:
            api_version = Version(plugin_api_version)
            runtime_python = Version(python_version)
        except InvalidVersion as exc:
            raise PluginCompatibilityError(
                'Runtime compatibility version is invalid',
                plugin_id=metadata.plugin_id,
                code='plugin_runtime_version_invalid',
                safe_details={
                    'plugin_api_version': plugin_api_version,
                    'python_version': python_version,
                },
            ) from exc
        if api_version not in api_specifier:
            raise PluginCompatibilityError(
                'Plugin requires an unsupported plugin API version',
                plugin_id=metadata.plugin_id,
                code='plugin_api_incompatible',
                safe_details={
                    'requires_plugin_api': metadata.requires_plugin_api,
                    'plugin_api_version': plugin_api_version,
                },
            )
        if runtime_python not in python_specifier:
            raise PluginCompatibilityError(
                'Plugin requires an unsupported Python version',
                plugin_id=metadata.plugin_id,
                code='plugin_python_incompatible',
                safe_details={
                    'python_requires': metadata.python_requires,
                    'python_version': python_version,
                },
            )


def _required_str(data: Mapping[str, Any], field: str, *, parent: str | None = None) -> str:
    if field not in data:
        qualified = f'{parent}.{field}' if parent else field
        raise _metadata_error('Required plugin metadata field is missing', field=qualified)
    value = data[field]
    if not isinstance(value, str) or not value:
        qualified = f'{parent}.{field}' if parent else field
        raise _metadata_error('Plugin metadata field must be a non-empty string', field=qualified)
    return value


def _validate_version(field: str, value: str) -> None:
    try:
        Version(value)
    except InvalidVersion as exc:
        raise _metadata_error('Plugin metadata version is invalid', field=field) from exc


def _validate_specifier(field: str, value: str) -> SpecifierSet:
    try:
        return SpecifierSet(value)
    except InvalidSpecifier as exc:
        raise _metadata_error('Plugin metadata version specifier is invalid', field=field) from exc


def _validate_dependencies(dependencies: PluginDependencies, *, plugin_id: str) -> None:
    if dependencies.mode != _SUPPORTED_DEPENDENCY_MODE:
        raise PluginMetadataError(
            'Unsupported plugin dependency mode',
            plugin_id=plugin_id,
            phase='metadata_validation',
            code='plugin_dependency_mode_unsupported',
            safe_details={'mode': dependencies.mode},
        )
    _validate_relative_metadata_path(
        dependencies.wheels_path,
        field='dependencies.wheels_path',
        plugin_id=plugin_id,
    )


def _validate_declared_capabilities(
    declared_capabilities: tuple[DeclaredCapability, ...],
    *,
    plugin_id: str,
) -> None:
    for capability in declared_capabilities:
        if capability.namespace not in _ALLOWED_CAPABILITY_NAMESPACES:
            raise PluginMetadataError(
                'Declared capability namespace is unsupported',
                plugin_id=plugin_id,
                phase='metadata_validation',
                code='plugin_declared_capability_namespace_unsupported',
                safe_details={'namespace': capability.namespace, 'id': capability.id},
            )


def _validate_entrypoint(package_root: Path, metadata: PluginMetadata) -> None:
    module_path, _, class_name = metadata.entrypoint.partition(':')
    if not module_path or not class_name or ':' in class_name:
        raise _metadata_error(
            'Plugin entrypoint must use module.path:ClassName format',
            plugin_id=metadata.plugin_id,
            field='entrypoint',
        )
    if any(separator in module_path or separator in class_name for separator in ('/', '\\')):
        raise _metadata_error(
            'Plugin entrypoint must not contain path separators',
            plugin_id=metadata.plugin_id,
            field='entrypoint',
        )
    if '..' in module_path.split('.'):
        raise _metadata_error(
            'Plugin entrypoint must not contain traversal segments',
            plugin_id=metadata.plugin_id,
            field='entrypoint',
        )
    module_parts = module_path.split('.')
    if not all(part.isidentifier() for part in module_parts) or not class_name.isidentifier():
        raise _metadata_error(
            'Plugin entrypoint contains invalid identifiers',
            plugin_id=metadata.plugin_id,
            field='entrypoint',
        )

    module_file = package_root.joinpath(*module_parts).with_suffix('.py')
    package_init = package_root.joinpath(*module_parts, '__init__.py')
    if not _is_contained(package_root, module_file) or not _is_contained(
        package_root,
        package_init,
    ):
        raise _metadata_error(
            'Plugin entrypoint must resolve inside package root',
            plugin_id=metadata.plugin_id,
            field='entrypoint',
        )
    if not module_file.is_file() and not package_init.is_file():
        raise _metadata_error(
            'Plugin entrypoint module was not found inside package root',
            plugin_id=metadata.plugin_id,
            field='entrypoint',
        )


def _validate_relative_metadata_path(path_value: str, *, field: str, plugin_id: str) -> None:
    path = PurePosixPath(path_value.replace('\\', '/'))
    if path.is_absolute() or '..' in path.parts:
        raise PluginMetadataError(
            'Plugin metadata path must be relative and contained',
            plugin_id=plugin_id,
            phase='metadata_validation',
            code='plugin_metadata_path_invalid',
            safe_details={'field': field},
        )


def _is_contained(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _metadata_error(
    message: str,
    *,
    plugin_id: str | None = None,
    field: str | None = None,
) -> PluginMetadataError:
    details: dict[str, object] = {}
    if field is not None:
        details['field'] = field
    return PluginMetadataError(
        message,
        plugin_id=plugin_id,
        phase='metadata_validation',
        code='plugin_metadata_invalid',
        safe_details=details,
    )


__all__ = [
    'DeclaredCapability',
    'PluginDependencies',
    'PluginMetadata',
    'PluginMetadataReader',
    'PluginPackage',
    'PluginValidator',
]
