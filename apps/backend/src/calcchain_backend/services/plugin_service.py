from __future__ import annotations

import json
from pathlib import Path
import platform
import subprocess
import sys
from typing import Any

from calcchain_core.capabilities import RuntimeCapabilities

from calcchain_backend.schemas.plugin import (
    PluginCapability,
    PluginInfo,
    PluginRuntimeDiagnostic,
    PluginRuntimeStatusResponse,
)
from calcchain_backend.settings import BackendSettings


class PluginService:
    """Reads plugin descriptors and stores enable/disable state.

    Runtime hot reload is intentionally not performed here. A PATCH request changes
    backend state and returns `restart_required=True`; the plugin runtime can be
    recreated safely during the next backend restart.
    """

    def __init__(self, settings: BackendSettings) -> None:
        self._settings = settings
        self._runtime: RuntimeCapabilities | None = None
        self._runtime_error: str | None = None
        self._runtime_diagnostics: list[PluginRuntimeDiagnostic] = []

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
            loaded = self._runtime is not None and plugin_id in self._runtime.active_owner_ids and not pending_restart
            plugins.append(
                PluginInfo(
                    id=plugin_id,
                    version=descriptor.get("plugin_version") or descriptor.get("version"),
                    name=descriptor.get("name") or plugin_id,
                    enabled=enabled,
                    loaded=loaded,
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
        self._runtime = None
        self._runtime_error = "Plugin runtime requires reload"
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

    def runtime(self, *, reload: bool = False) -> RuntimeCapabilities:
        if self._runtime is not None and not reload:
            return self._runtime
        runtime = self._activate_runtime()
        self._runtime = runtime
        self._runtime_error = None
        self._runtime_diagnostics = [_runtime_diagnostic(item) for item in runtime.diagnostics]
        self._clear_restart_flags(runtime.active_owner_ids)
        return runtime

    def runtime_or_empty(self) -> RuntimeCapabilities:
        try:
            return self.runtime()
        except Exception:
            return RuntimeCapabilities()

    def runtime_status(self) -> PluginRuntimeStatusResponse:
        return _runtime_status(self._runtime, error=self._runtime_error, diagnostics=self._runtime_diagnostics)

    def reload_runtime(self) -> PluginRuntimeStatusResponse:
        try:
            runtime = self.runtime(reload=True)
            return _runtime_status(runtime, error=None, diagnostics=self._runtime_diagnostics)
        except Exception as exc:
            self._runtime = None
            self._runtime_error = str(exc)
            if not self._runtime_diagnostics:
                self._runtime_diagnostics = [_diagnostic_from_error(exc)]
            return self.runtime_status()

    def _activate_runtime(self) -> RuntimeCapabilities:
        enabled_ids = tuple(plugin.id for plugin in self.list_plugins() if plugin.enabled)
        if not enabled_ids:
            return RuntimeCapabilities()

        from calcchain_plugin_system.activation_plan import PluginActivationPlanner
        from calcchain_plugin_system.dependencies import PluginDependencyPlanner
        from calcchain_plugin_system.discovery import PluginDiscovery
        from calcchain_plugin_system.environment import PluginEnvironmentManager
        from calcchain_plugin_system.manager import PluginManager
        from calcchain_plugin_system.settings import PluginSettings

        repository = PluginDiscovery().discover((self._settings.plugins_dir,))
        activation_plan = PluginActivationPlanner(
            python_version=platform.python_version(),
        ).plan(repository, PluginSettings(enabled_plugins=enabled_ids))
        if activation_plan.has_errors:
            from calcchain_plugin_system.errors import PluginActivationError

            self._runtime_diagnostics = [_runtime_diagnostic(item) for item in activation_plan.diagnostics]
            raise PluginActivationError(
                "Plugin activation plan contains diagnostics",
                phase="activation_commit",
                code="plugin_activation_plan_invalid",
                safe_details={"diagnostic_count": len(activation_plan.diagnostics)},
            )

        dependency_plan = PluginDependencyPlanner().plan(
            activation_plan,
            shared_wheelhouse=None,
            installer_backend_version=_pip_version(),
        )
        environment = PluginEnvironmentManager(
            self._settings.state_dir / "plugin_envs",
        ).ensure_environment(dependency_plan, allow_online=False)
        return PluginManager().activate(activation_plan, environment)

    def _scan_plugin_descriptors(self) -> list[dict[str, Any]]:
        descriptors: list[dict[str, Any]] = []

        for path in sorted(self._settings.plugins_dir.glob("*/plugin.json")):
            descriptor = self._read_json_object(path)
            if descriptor is not None:
                descriptor["__path__"] = str(path)
                descriptors.append(descriptor)

        # Some early CalcChain layouts keep a top-level plugins.json. Support it
        # as an optional list of plugin descriptors or descriptor paths.
        top_level = self._settings.resolved_app_root / "plugins.json"
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

    def _clear_restart_flags(self, active_plugin_ids: tuple[str, ...]) -> None:
        state = self._read_state()
        changed = False
        for plugin_id in active_plugin_ids:
            item = state.get(plugin_id)
            if item and item.get("restart_required"):
                item["restart_required"] = False
                changed = True
        if changed:
            self._write_state(state)

    @staticmethod
    def _read_json_object(path: Path) -> dict[str, Any] | None:
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None


def _runtime_status(
    runtime: RuntimeCapabilities | None,
    *,
    error: str | None,
    diagnostics: list[PluginRuntimeDiagnostic],
) -> PluginRuntimeStatusResponse:
    if runtime is None:
        return PluginRuntimeStatusResponse(active=False, diagnostics=diagnostics, error=error)
    return PluginRuntimeStatusResponse(
        active=True,
        plugin_ids=list(runtime.active_owner_ids),
        capabilities=[
            PluginCapability(namespace=key.namespace, id=key.id)
            for key in sorted(runtime.capabilities, key=lambda item: (item.namespace, item.id))
        ],
        diagnostics=diagnostics,
        error=error,
    )


def _runtime_diagnostic(diagnostic) -> PluginRuntimeDiagnostic:
    return PluginRuntimeDiagnostic(
        plugin_id=diagnostic.plugin_id,
        phase=diagnostic.phase,
        code=diagnostic.code,
        message=diagnostic.message,
        details=dict(diagnostic.safe_details),
    )


def _diagnostic_from_error(exc: Exception) -> PluginRuntimeDiagnostic:
    diagnostic = getattr(exc, "diagnostic", None)
    if diagnostic is not None:
        return _runtime_diagnostic(diagnostic)
    return PluginRuntimeDiagnostic(
        plugin_id=None,
        phase="activation_commit",
        code="plugin_runtime_error",
        message=str(exc),
        details={},
    )


def _pip_version() -> str:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "--version"],
            capture_output=True,
            text=True,
            shell=False,
            check=False,
        )
    except OSError:
        return "unknown"
    if result.returncode != 0:
        return "unknown"
    return result.stdout.strip() or "unknown"
