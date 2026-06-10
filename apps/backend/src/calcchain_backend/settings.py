from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BackendSettings:
    """Runtime settings for the backend application.

    `project_root` stays as the development/repository root for compatibility.
    Installed builds can override the application, state, plugin, static, and
    user project paths independently.
    """

    project_root: Path = Path.cwd()
    app_root: Path | None = None
    state_dir_path: Path | None = None
    state_dir_name: str = ".calcchain_backend"
    plugin_root: Path | None = None
    static_dir: Path | None = None
    user_projects_dir: Path | None = None
    app_name: str = "CalcChain Backend"
    api_version: str = "v1"
    mode: str = "local"
    host: str = "127.0.0.1"
    port: int = 8765
    pairing_ttl_seconds: int = 300
    session_ttl_seconds: int = 12 * 60 * 60
    max_pairing_attempts_per_minute: int = 5

    @property
    def auth_required(self) -> bool:
        return self.mode == "lan"

    @property
    def resolved_app_root(self) -> Path:
        return self.app_root or self.project_root

    @property
    def state_dir(self) -> Path:
        if self.state_dir_path is not None:
            return self.state_dir_path
        return self.project_root / self.state_dir_name

    @property
    def plugins_dir(self) -> Path:
        return self.plugin_root or (self.resolved_app_root / "plugins")

    @property
    def frontend_static_dir(self) -> Path | None:
        return self.static_dir

    @property
    def projects_dir(self) -> Path | None:
        return self.user_projects_dir

    @property
    def projects_path(self) -> Path:
        return self.state_dir / "projects.json"

    @property
    def plugins_state_path(self) -> Path:
        return self.state_dir / "plugins_state.json"

    @property
    def runs_dir(self) -> Path:
        return self.state_dir / "runs"


def create_settings(
    project_root: str | Path | None = None,
    *,
    app_root: str | Path | None = None,
    state_dir: str | Path | None = None,
    state_dir_name: str = ".calcchain_backend",
    plugin_root: str | Path | None = None,
    static_dir: str | Path | None = None,
    user_projects_dir: str | Path | None = None,
    mode: str = "local",
    host: str = "127.0.0.1",
    port: int = 8765,
) -> BackendSettings:
    root = Path(project_root).resolve() if project_root is not None else Path.cwd().resolve()
    return BackendSettings(
        project_root=root,
        app_root=_resolve_optional_path(app_root),
        state_dir_path=_resolve_optional_path(state_dir),
        state_dir_name=state_dir_name,
        plugin_root=_resolve_optional_path(plugin_root),
        static_dir=_resolve_optional_path(static_dir),
        user_projects_dir=_resolve_optional_path(user_projects_dir),
        mode=mode,
        host=host,
        port=port,
    )


def _resolve_optional_path(value: str | Path | None) -> Path | None:
    return Path(value).resolve() if value is not None else None
