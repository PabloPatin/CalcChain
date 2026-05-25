from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BackendSettings:
    """Runtime settings for the backend application.

    `project_root` is the CalcChain repository/workspace root. The backend uses it
    to scan `plugins/*/plugin.json` and to place the lightweight backend state.
    """

    project_root: Path = Path.cwd()
    state_dir_name: str = ".calcchain_backend"
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
    def state_dir(self) -> Path:
        return self.project_root / self.state_dir_name

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
    mode: str = "local",
    host: str = "127.0.0.1",
    port: int = 8765,
) -> BackendSettings:
    root = Path(project_root).resolve() if project_root is not None else Path.cwd().resolve()
    return BackendSettings(project_root=root, mode=mode, host=host, port=port)
