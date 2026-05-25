from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
import shutil
import subprocess
import sys
import tempfile

from calcchain_plugin_system.dependencies import (
    PluginDependencyPlan,
    WheelRecord,
    compute_env_hash,
    verify_wheel_hashes,
)
from calcchain_plugin_system.environment_lock import (
    PLUGIN_ENV_LOCK_NAME,
    PluginEnvLock,
    verify_plugin_env_lock,
    write_plugin_env_lock,
)
from calcchain_plugin_system.errors import PluginDependencyError


@dataclass(frozen=True)
class PluginEnvironment:
    root: Path
    env_hash: str
    site_packages: Path
    lock_path: Path


@dataclass(frozen=True)
class ResolvedDependencies:
    packages: tuple[str, ...] = ()


class PipInstaller:
    def install(
        self,
        plan: PluginDependencyPlan,
        target_site_packages: Path,
        *,
        allow_online: bool,
    ) -> ResolvedDependencies:
        target_site_packages.mkdir(parents=True, exist_ok=True)
        result = _run_installer(_pip_install_args(plan, target_site_packages, allow_online=allow_online))
        if _pip_module_missing(result):
            uv_executable = shutil.which('uv')
            if uv_executable is not None:
                result = _run_installer(
                    _uv_pip_install_args(
                        plan,
                        target_site_packages,
                        allow_online=allow_online,
                        uv_executable=uv_executable,
                    ),
                )
        if result.returncode != 0:
            raise _install_error(
                'Plugin dependency installer failed',
                code='plugin_installer_failed',
                safe_details={
                    'returncode': result.returncode,
                    'stdout': _trim_output(result.stdout),
                    'stderr': _trim_output(result.stderr),
                },
            )
        return ResolvedDependencies()


class PluginEnvironmentManager:
    def __init__(
        self,
        plugin_envs_dir: Path,
        *,
        installer: PipInstaller | None = None,
    ) -> None:
        self._plugin_envs_dir = plugin_envs_dir
        self._installer = installer or PipInstaller()

    def ensure_environment(
        self,
        plan: PluginDependencyPlan,
        *,
        allow_online: bool = False,
    ) -> PluginEnvironment:
        env_hash = compute_env_hash(plan)
        final_root = self._plugin_envs_dir / env_hash
        final_site_packages = final_root / 'site-packages'
        final_lock_path = final_root / PLUGIN_ENV_LOCK_NAME

        if _can_reuse_environment(final_root, final_site_packages, env_hash):
            return PluginEnvironment(
                root=final_root,
                env_hash=env_hash,
                site_packages=final_site_packages,
                lock_path=final_lock_path,
            )

        self._plugin_envs_dir.mkdir(parents=True, exist_ok=True)
        temp_root = Path(
            tempfile.mkdtemp(prefix=f'.tmp-{env_hash}-', dir=self._plugin_envs_dir),
        )
        try:
            temp_site_packages = temp_root / 'site-packages'
            temp_site_packages.mkdir(parents=True, exist_ok=True)
            used_wheels = _verify_wheels_for_install(plan)
            resolved = self._installer.install(
                plan,
                temp_site_packages,
                allow_online=allow_online,
            )
            lock = PluginEnvLock.from_plan(
                plan,
                used_wheels=used_wheels,
                resolved_dependencies=resolved.packages,
            )
            write_plugin_env_lock(lock, temp_root / PLUGIN_ENV_LOCK_NAME)
            verify_plugin_env_lock(temp_root, env_hash)
            _publish_environment(temp_root, final_root)
            temp_root = None
        finally:
            if temp_root is not None and temp_root.exists():
                shutil.rmtree(temp_root, ignore_errors=True)

        return PluginEnvironment(
            root=final_root,
            env_hash=env_hash,
            site_packages=final_site_packages,
            lock_path=final_lock_path,
        )


def _pip_install_args(
    plan: PluginDependencyPlan,
    target_site_packages: Path,
    *,
    allow_online: bool,
) -> list[str]:
    args = [
        sys.executable,
        '-m',
        'pip',
        'install',
        '--target',
        str(target_site_packages),
        '--disable-pip-version-check',
    ]
    if not allow_online:
        args.append('--no-index')
    for requirement in plan.requirements:
        args.extend(('-r', str(requirement.path)))
    for wheel_lock in plan.plugin_wheel_locks:
        args.extend(('--find-links', str(wheel_lock.wheel_dir)))
    if plan.shared_wheelhouse is not None:
        args.extend(('--find-links', str(plan.shared_wheelhouse)))
    return args


def _uv_pip_install_args(
    plan: PluginDependencyPlan,
    target_site_packages: Path,
    *,
    allow_online: bool,
    uv_executable: str,
) -> list[str]:
    args = [
        uv_executable,
        'pip',
        'install',
        '--python',
        sys.executable,
        '--target',
        str(target_site_packages),
    ]
    if not allow_online:
        args.append('--no-index')
    for requirement in plan.requirements:
        args.extend(('-r', str(requirement.path)))
    for wheel_lock in plan.plugin_wheel_locks:
        args.extend(('--find-links', str(wheel_lock.wheel_dir)))
    if plan.shared_wheelhouse is not None:
        args.extend(('--find-links', str(plan.shared_wheelhouse)))
    return args


def _run_installer(args: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            shell=False,
            check=False,
        )
    except OSError as exc:
        raise _install_error(
            'Cannot run plugin dependency installer',
            code='plugin_installer_run_failed',
            safe_details={'error': str(exc)},
        ) from exc


def _pip_module_missing(result: subprocess.CompletedProcess[str]) -> bool:
    return result.returncode != 0 and 'No module named pip' in f'{result.stdout}\n{result.stderr}'


def _can_reuse_environment(root: Path, site_packages: Path, env_hash: str) -> bool:
    if not site_packages.is_dir():
        return False
    try:
        verify_plugin_env_lock(root, env_hash)
    except PluginDependencyError:
        return False
    return True


def _verify_wheels_for_install(plan: PluginDependencyPlan) -> tuple[WheelRecord, ...]:
    try:
        return verify_wheel_hashes(plan)
    except PluginDependencyError as exc:
        raise _install_error(
            'Plugin wheel verification failed before dependency install',
            plugin_id=exc.diagnostic.plugin_id,
            code=exc.diagnostic.code,
            safe_details=exc.diagnostic.safe_details,
        ) from exc


def _publish_environment(temp_root: Path, final_root: Path) -> None:
    try:
        if final_root.exists():
            shutil.rmtree(final_root)
        temp_root.rename(final_root)
    except OSError as exc:
        raise _install_error(
            'Cannot publish plugin dependency environment',
            code='plugin_environment_publish_failed',
            safe_details={'env_path': str(final_root), 'error': str(exc)},
        ) from exc


def _trim_output(value: str, *, limit: int = 4000) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + '...'


def _install_error(
    message: str,
    *,
    code: str,
    plugin_id: str | None = None,
    safe_details: Mapping[str, object] | None = None,
) -> PluginDependencyError:
    return PluginDependencyError(
        message,
        plugin_id=plugin_id,
        phase='dependency_install',
        code=code,
        safe_details=safe_details,
    )


__all__ = [
    'PipInstaller',
    'PluginEnvironment',
    'PluginEnvironmentManager',
    'ResolvedDependencies',
]
