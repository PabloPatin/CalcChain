from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from calcchain_core.api import CalculationCore  # noqa: E402
from calcchain_core.plugins import (  # noqa: E402
    PluginActivationPlanner,
    PluginDependencyPlanner,
    PluginDiscovery,
    PluginEnvironmentManager,
    PluginManager,
    PluginSettings,
    PluginSettingsStore,
    compute_env_hash,
)
from calcchain_core.plugins.errors import PluginError  # noqa: E402


PLUGIN_ROOTS = REPO_ROOT / 'plugins'
PLUGIN_SETTINGS = REPO_ROOT / 'plugins.json'
PLUGIN_ENVS = REPO_ROOT / 'plugin_envs'
EXPECTED_PLUGIN_ID = 'calcchain.svn'


class ReuseGuardInstaller:
    def install(self, plan, target_site_packages: Path, *, allow_online: bool):
        raise RuntimeError('installer was called, so the environment was not reused')


def main() -> int:
    print('CalcChain plugin infrastructure demo')
    print(f'repo: {REPO_ROOT}')

    if not (PLUGIN_ROOTS / 'svn' / 'plugin.json').is_file():
        print()
        print('Demo plugin is missing: plugins/svn/plugin.json')
        print('Create the svn demo plugin before running this script.')
        return 1

    try:
        repository = discover_plugins()
        settings = load_settings()
        activation_plan = build_activation_plan(repository, settings)
        dependency_plan = build_dependency_plan(activation_plan)
        environment = ensure_environment(dependency_plan)
        prove_environment_reuse(dependency_plan)
        activate_plugins(activation_plan, environment)
        show_planning_diagnostic(repository)
        show_current_core_boundary()
    except PluginError as exc:
        print_plugin_error(exc)
        return 2

    return 0


def discover_plugins():
    section('1. Discovery без импорта кода плагина')
    repository = PluginDiscovery().discover([PLUGIN_ROOTS])
    print(f'plugin roots: {PLUGIN_ROOTS}')
    print(f'discovered plugin ids: {sorted(repository.snapshot())}')

    package = repository.require(EXPECTED_PLUGIN_ID)
    metadata = package.metadata
    print(f'metadata path: {package.metadata_path}')
    print(f'entrypoint: {metadata.entrypoint}')
    print(
        'declared capabilities: '
        + ', '.join(
            f'{capability.namespace}:{capability.id}'
            for capability in metadata.declared_capabilities
        ),
    )
    return repository


def load_settings():
    section('2. Enabled settings')
    settings = PluginSettingsStore(PLUGIN_SETTINGS).load()
    print(f'settings path: {PLUGIN_SETTINGS}')
    print(f'enabled plugins: {settings.enabled_plugins}')
    return settings


def build_activation_plan(repository, settings):
    section('3. Activation plan')
    plan = PluginActivationPlanner().plan(repository, settings)
    print(f'enabled plugin ids in plan: {plan.enabled_plugin_ids}')
    print(f'plugin API version: {plan.plugin_api_version}')
    print(f'python version: {plan.python_version}')
    print(f'has blocking diagnostics: {plan.has_errors}')
    print_diagnostics(plan.diagnostics)
    if plan.has_errors:
        raise SystemExit('Activation plan has diagnostics, activation is intentionally stopped.')
    return plan


def build_dependency_plan(activation_plan):
    section('4. Dependency plan и env hash')
    pip_version = current_pip_version()
    plan = PluginDependencyPlanner().plan(
        activation_plan,
        shared_wheelhouse=None,
        installer_backend_version=pip_version,
    )
    print(f'installer backend: {pip_version}')
    print(f'env hash: {compute_env_hash(plan)}')
    for requirement in plan.requirements:
        print(f'requirements: {requirement.path} sha256={requirement.sha256}')
    for wheel_lock in plan.plugin_wheel_locks:
        print(
            f'wheel lock: {wheel_lock.lock.path} '
            f'wheels={len(wheel_lock.lock.wheels)}',
        )
    return plan


def ensure_environment(dependency_plan):
    section('5. Environment build/reuse')
    env_hash = compute_env_hash(dependency_plan)
    expected_root = PLUGIN_ENVS / env_hash
    existed_before = expected_root.is_dir()
    environment = PluginEnvironmentManager(PLUGIN_ENVS).ensure_environment(
        dependency_plan,
        allow_online=False,
    )
    status = 'reused' if existed_before else 'created'
    print(f'environment status: {status}')
    print(f'environment root: {environment.root}')
    print(f'site-packages exists: {environment.site_packages.is_dir()}')
    print(f'lock path: {environment.lock_path}')
    return environment


def prove_environment_reuse(dependency_plan) -> None:
    section('6. Reuse check без повторного installer call')
    environment = PluginEnvironmentManager(
        PLUGIN_ENVS,
        installer=ReuseGuardInstaller(),
    ).ensure_environment(dependency_plan, allow_online=False)
    print(f'reuse succeeded: {environment.root}')


def activate_plugins(activation_plan, environment) -> None:
    section('7. Atomic activation через PluginManager')
    manager = PluginManager()
    print(f'active set before activation: {manager.active_set}')
    runtime_set = manager.activate(activation_plan, environment)
    print(f'active plugin ids: {runtime_set.active_plugin_ids}')
    print(f'active set committed: {manager.active_set is runtime_set}')
    print('runtime capabilities:')
    for key, record in sorted(
        runtime_set.capabilities.items(),
        key=lambda item: item[0].qualified_id,
    ):
        print(
            f'  - {key.qualified_id} owner={record.owner} '
            f'payload={type(record.capability).__name__}',
        )


def show_planning_diagnostic(repository) -> None:
    section('8. Пример planning diagnostic без импорта плагина')
    bad_settings = PluginSettings(enabled_plugins=('missing.plugin',))
    bad_plan = PluginActivationPlanner().plan(repository, bad_settings)
    print(f'bad plan has diagnostics: {bad_plan.has_errors}')
    print_diagnostics(bad_plan.diagnostics)


def show_current_core_boundary() -> None:
    section('9. Текущая граница реализации')
    print(
        'PluginRuntimeSet уже содержит source:svn и target:svn, '
        'но CalculationCore пока не подключает эти capabilities автоматически.',
    )
    print(
        'CalculationCore constructor parameters: '
        + ', '.join(CalculationCore.__init__.__annotations__.keys()),
    )


def print_diagnostics(diagnostics) -> None:
    if not diagnostics:
        print('diagnostics: none')
        return
    print('diagnostics:')
    for diagnostic in diagnostics:
        print(
            f'  - code={diagnostic.code} phase={diagnostic.phase} '
            f'plugin_id={diagnostic.plugin_id} message={diagnostic.message}',
        )


def print_plugin_error(exc: PluginError) -> None:
    diagnostic = exc.diagnostic
    print()
    print('Plugin error:')
    print(f'  code: {diagnostic.code}')
    print(f'  phase: {diagnostic.phase}')
    print(f'  plugin_id: {diagnostic.plugin_id}')
    print(f'  message: {diagnostic.message}')
    print(f'  details: {diagnostic.safe_details}')


def current_pip_version() -> str:
    result = subprocess.run(
        [sys.executable, '-m', 'pip', '--version'],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def section(title: str) -> None:
    print()
    print(title)
    print('-' * len(title))


if __name__ == '__main__':
    raise SystemExit(main())
