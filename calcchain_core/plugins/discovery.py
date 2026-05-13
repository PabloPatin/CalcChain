from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from calcchain_core.plugins.metadata import PluginMetadataReader, PluginPackage, PluginValidator
from calcchain_core.plugins.repository import PluginRepository


class PluginDiscovery:
    def __init__(
        self,
        *,
        reader: PluginMetadataReader | None = None,
        validator: PluginValidator | None = None,
    ) -> None:
        self._reader = reader or PluginMetadataReader()
        self._validator = validator or PluginValidator()

    def discover(self, plugin_roots: Iterable[Path]) -> PluginRepository:
        repository = PluginRepository()
        for plugin_root in plugin_roots:
            for metadata_path in self._metadata_paths(plugin_root):
                metadata = self._reader.read(metadata_path)
                package = PluginPackage(
                    root=metadata_path.parent,
                    metadata_path=metadata_path,
                    metadata=metadata,
                )
                self._validator.validate_package(package.root, metadata)
                repository.add(package)
        return repository

    def _metadata_paths(self, plugin_root: Path) -> tuple[Path, ...]:
        direct_metadata = plugin_root / 'plugin.json'
        paths: list[Path] = []
        if direct_metadata.is_file():
            paths.append(direct_metadata)
        if plugin_root.is_dir():
            for child in sorted(plugin_root.iterdir(), key=lambda path: path.name):
                child_metadata = child / 'plugin.json'
                if child.is_dir() and child_metadata.is_file():
                    paths.append(child_metadata)
        return tuple(dict.fromkeys(paths))


__all__ = ['PluginDiscovery']
