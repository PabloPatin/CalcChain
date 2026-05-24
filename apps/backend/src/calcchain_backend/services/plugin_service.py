from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from calcchain_backend.schemas.plugin import PluginCapability, PluginInfo
from calcchain_backend.settings import BackendSettings


class PluginService:
    """Reads plugin descriptors and stores enable/disable state.

    Runtime hot reload is intentionally not performed here. A PATCH request changes
    backend state and returns `restart_required=True`; the plugin runtime can be
    recreated safely during the next backend restart.
    """

    def __init__(self, settings: BackendSettings) -> None:
        self._settings = settings

    def list_plugins(self) -> list[PluginInfo]:
        state = self._read_state()
        descriptors = self._scan_plugin_descriptors()
        plugins: list[PluginInfo] = []
        for descriptor in descriptors:
            plugin_id = str(descriptor.get("plugin_id") or descriptor.get("id") or "unknown")
            enabled = bool(state.get(plugin_id, {}).get("enabled", True))
            capabilities = [
                PluginCapability(namespace=str(item.get("namespace")), id=str(item.get("id")))
                for item in descriptor.get("declared_capabilities", [])
                if isinstance(item, dict) and item.get("namespace") and item.get("id")
            ]
            pending_restart = bool(state.get(plugin_id, {}).get("restart_required", False))
            plugins.append(
                PluginInfo(
                    id=plugin_id,
                    version=descriptor.get("plugin_version") or descriptor.get("version"),
                    name=descriptor.get("name") or plugin_id,
                    enabled=enabled,
                    loaded=enabled and not pending_restart,
                    status="pending_restart" if pending_restart else ("active" if enabled else "disabled"),
                    restart_required=pending_restart,
                    capabilities=capabilities,
                    metadata={
                        "descriptor_path": descriptor.get("__path__"),
                        "entrypoint": descriptor.get("entrypoint"),
                        "requires_plugin_api": descriptor.get("requires_plugin_api"),
                    },
                ),
            )
        return sorted(plugins, key=lambda plugin: plugin.id)

    def patch_plugin(self, plugin_id: str, *, enabled: bool) -> PluginInfo:
        state = self._read_state()
        state[plugin_id] = {"enabled": enabled, "restart_required": True}
        self._write_state(state)
        matches = [plugin for plugin in self.list_plugins() if plugin.id == plugin_id]
        if matches:
            return matches[0]
        return PluginInfo(
            id=plugin_id,
            enabled=enabled,
            loaded=False,
            status="pending_restart",
            restart_required=True,
        )

    def enabled_plugin_ids(self) -> list[str]:
        return [plugin.id for plugin in self.list_plugins() if plugin.enabled]

    def _scan_plugin_descriptors(self) -> list[dict[str, Any]]:
        root = self._settings.project_root
        descriptors: list[dict[str, Any]] = []

        for path in sorted((root / "plugins").glob("*/plugin.json")):
            descriptor = self._read_json_object(path)
            if descriptor is not None:
                descriptor["__path__"] = str(path)
                descriptors.append(descriptor)

        # Some early CalcChain layouts keep a top-level plugins.json. Support it
        # as an optional list of plugin descriptors or descriptor paths.
        top_level = root / "plugins.json"
        top_level_data = self._read_json_object(top_level)
        if top_level_data is not None:
            items = top_level_data.get("plugins") if isinstance(top_level_data.get("plugins"), list) else []
            for item in items:
                if isinstance(item, dict):
                    item = dict(item)
                    item["__path__"] = str(top_level)
                    descriptors.append(item)

        return descriptors

    def _read_state(self) -> dict[str, dict[str, Any]]:
        path = self._settings.plugins_state_path
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def _write_state(self, state: dict[str, dict[str, Any]]) -> None:
        path = self._settings.plugins_state_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _read_json_object(path: Path) -> dict[str, Any] | None:
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None
