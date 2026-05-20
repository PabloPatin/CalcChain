from collections.abc import Sequence
from pathlib import Path
import platform
import subprocess
import sys

from calcchain_plugin_system.activation_plan import PluginActivationPlanner
from calcchain_plugin_system.dependencies import PluginDependencyPlanner
from calcchain_plugin_system.discovery import PluginDiscovery
from calcchain_plugin_system.environment import PipInstaller, PluginEnvironmentManager
from calcchain_capabilities.errors import PluginActivationError, PluginDependencyError
from calcchain_capabilities import PluginRuntimeSet
from calcchain_plugin_system.manager import PluginManager
from calcchain_plugin_system.settings import PluginSettingsStore


def activate_plugins(
    plugin_roots: Sequence[Path],
    settings_path: Path,
    envs_dir: Path,
    *,
    python_executable: str | None = None,
    pip_installer: PipInstaller | None = None,
) -> PluginRuntimeSet:
    repository = PluginDiscovery().discover(tuple(Path(root) for root in plugin_roots))
    settings = PluginSettingsStore(Path(settings_path)).load()
    activation_plan = PluginActivationPlanner(
        python_version=_python_version(python_executable),
    ).plan(repository, settings)
    if activation_plan.has_errors:
        raise PluginActivationError(
            'Plugin activation plan contains diagnostics',
            phase='activation_commit',
            code='plugin_activation_plan_invalid',
            safe_details={'diagnostic_count': len(activation_plan.diagnostics)},
        )
    dependency_plan = PluginDependencyPlanner().plan(
        activation_plan,
        shared_wheelhouse=None,
        installer_backend_version=_pip_version(python_executable),
    )
    environment = PluginEnvironmentManager(
        Path(envs_dir),
        installer=pip_installer,
    ).ensure_environment(dependency_plan, allow_online=False)
    return PluginManager().activate(activation_plan, environment)


def _python_version(python_executable: str | None) -> str:
    if python_executable is None or Path(python_executable) == Path(sys.executable):
        return platform.python_version()
    try:
        result = subprocess.run(
            [python_executable, '--version'],
            capture_output=True,
            text=True,
            shell=False,
            check=False,
        )
    except OSError as exc:
        raise _bootstrap_dependency_error(
            'Cannot query plugin Python version',
            code='plugin_python_version_failed',
            error=str(exc),
        ) from exc
    if result.returncode != 0:
        raise _bootstrap_dependency_error(
            'Cannot query plugin Python version',
            code='plugin_python_version_failed',
            error=result.stderr.strip() or result.stdout.strip(),
        )
    return (result.stdout or result.stderr).strip().removeprefix('Python ').strip()


def _pip_version(python_executable: str | None) -> str:
    executable = python_executable or sys.executable
    try:
        result = subprocess.run(
            [executable, '-m', 'pip', '--version'],
            capture_output=True,
            text=True,
            shell=False,
            check=False,
        )
    except OSError as exc:
        raise _bootstrap_dependency_error(
            'Cannot query plugin dependency installer version',
            code='plugin_installer_version_failed',
            error=str(exc),
        ) from exc
    if result.returncode != 0:
        raise _bootstrap_dependency_error(
            'Cannot query plugin dependency installer version',
            code='plugin_installer_version_failed',
            error=result.stderr.strip() or result.stdout.strip(),
        )
    return result.stdout.strip()


def _bootstrap_dependency_error(message: str, *, code: str, error: str) -> PluginDependencyError:
    return PluginDependencyError(
        message,
        phase='dependency_plan',
        code=code,
        safe_details={'error': error},
    )


__all__ = ['activate_plugins']
