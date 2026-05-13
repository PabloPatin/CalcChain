from __future__ import annotations

from collections.abc import Iterator
from types import MappingProxyType
from typing import Mapping

from calcchain_core.plugins.errors import PluginMetadataError
from calcchain_core.plugins.metadata import PluginPackage


class PluginRepository:
    def __init__(self) -> None:
        self._packages: dict[str, PluginPackage] = {}

    def add(self, package: PluginPackage) -> None:
        plugin_id = package.metadata.plugin_id
        if plugin_id in self._packages:
            existing = self._packages[plugin_id]
            raise PluginMetadataError(
                'Duplicate plugin id discovered',
                plugin_id=plugin_id,
                phase='metadata_validation',
                code='plugin_id_duplicate',
                safe_details={
                    'plugin_id': plugin_id,
                    'metadata_path': str(package.metadata_path),
                    'existing_metadata_path': str(existing.metadata_path),
                },
            )
        self._packages[plugin_id] = package

    def get(self, plugin_id: str) -> PluginPackage | None:
        return self._packages.get(plugin_id)

    def require(self, plugin_id: str) -> PluginPackage:
        package = self.get(plugin_id)
        if package is None:
            raise PluginMetadataError(
                'Plugin id is not installed',
                plugin_id=plugin_id,
                phase='metadata_validation',
                code='plugin_id_missing',
                safe_details={'plugin_id': plugin_id},
            )
        return package

    def snapshot(self) -> Mapping[str, PluginPackage]:
        return MappingProxyType(dict(self._packages))

    def __iter__(self) -> Iterator[PluginPackage]:
        return iter(self._packages.values())

    def __len__(self) -> int:
        return len(self._packages)


__all__ = ['PluginRepository']
