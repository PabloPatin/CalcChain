import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from calcchain_core.hash import sha256_file
from calcchain_plugin_system.activation_plan import PluginActivationPlan
from calcchain_plugin_system.dependencies import (
    PluginDependencyPlanner,
    compute_env_hash,
    verify_wheel_hashes,
)
from calcchain_plugin_system.environment import (
    PipInstaller,
    PluginEnvironmentManager,
    ResolvedDependencies,
)
from calcchain_plugin_system.environment_lock import (
    PLUGIN_ENV_LOCK_NAME,
    PluginEnvLock,
    read_plugin_env_lock,
    write_plugin_env_lock,
)
from calcchain_capabilities.errors import PluginDependencyError
from calcchain_plugin_system.metadata import PluginDependencies, PluginMetadata, PluginPackage


class FakeInstaller:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = []

    def install(self, plan, target_site_packages: Path, *, allow_online: bool):
        self.calls.append(
            {
                'plan': plan,
                'target_site_packages': target_site_packages,
                'allow_online': allow_online,
            },
        )
        target_site_packages.mkdir(parents=True, exist_ok=True)
        (target_site_packages / 'installed.txt').write_text('ok\n', encoding='utf-8')
        if self.fail:
            raise PluginDependencyError(
                'fake installer failed',
                phase='dependency_install',
                code='plugin_installer_failed',
                safe_details={'backend': 'fake'},
            )
        return ResolvedDependencies(packages=('demo==1.0',))


class TestCorePluginEnvironment(unittest.TestCase):
    def test_valid_existing_environment_is_reused_without_installer_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._dependency_plan(root / 'plugin')
            env_hash = compute_env_hash(plan)
            env_root = root / 'plugin_envs' / env_hash
            site_packages = env_root / 'site-packages'
            site_packages.mkdir(parents=True)
            lock = PluginEnvLock.from_plan(plan, used_wheels=verify_wheel_hashes(plan))
            write_plugin_env_lock(lock, env_root / PLUGIN_ENV_LOCK_NAME)
            installer = FakeInstaller()

            environment = PluginEnvironmentManager(
                root / 'plugin_envs',
                installer=installer,
            ).ensure_environment(plan)

            self.assertEqual(environment.root, env_root)
            self.assertEqual(environment.site_packages, site_packages)
            self.assertEqual(installer.calls, [])

    def test_environment_is_built_in_temp_and_published_with_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._dependency_plan(root / 'plugin')
            env_hash = compute_env_hash(plan)
            plugin_envs = root / 'plugin_envs'
            installer = FakeInstaller()

            environment = PluginEnvironmentManager(
                plugin_envs,
                installer=installer,
            ).ensure_environment(plan, allow_online=True)

            self.assertEqual(environment.root, plugin_envs / env_hash)
            self.assertTrue((environment.site_packages / 'installed.txt').is_file())
            lock = read_plugin_env_lock(environment.lock_path)
            self.assertEqual(lock.env_hash, env_hash)
            self.assertEqual(lock.resolved_dependencies, ('demo==1.0',))
            installer_target = installer.calls[0]['target_site_packages']
            self.assertEqual(installer_target.name, 'site-packages')
            self.assertTrue(installer_target.parent.name.startswith('.tmp-'))
            self.assertTrue(installer.calls[0]['allow_online'])
            self.assertFalse((environment.root / '.ready').exists())
            self.assertEqual(list(plugin_envs.glob('.tmp-*')), [])

    def test_invalid_existing_lock_is_rebuilt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._dependency_plan(root / 'plugin')
            env_hash = compute_env_hash(plan)
            env_root = root / 'plugin_envs' / env_hash
            site_packages = env_root / 'site-packages'
            site_packages.mkdir(parents=True)
            (site_packages / 'old.txt').write_text('old\n', encoding='utf-8')
            (env_root / PLUGIN_ENV_LOCK_NAME).write_text('{bad-json', encoding='utf-8')
            installer = FakeInstaller()

            environment = PluginEnvironmentManager(
                root / 'plugin_envs',
                installer=installer,
            ).ensure_environment(plan)

            self.assertTrue((environment.site_packages / 'installed.txt').is_file())
            self.assertFalse((environment.site_packages / 'old.txt').exists())
            self.assertEqual(read_plugin_env_lock(environment.lock_path).env_hash, env_hash)
            self.assertEqual(len(installer.calls), 1)

    def test_missing_existing_lock_is_rebuilt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._dependency_plan(root / 'plugin')
            env_hash = compute_env_hash(plan)
            env_root = root / 'plugin_envs' / env_hash
            site_packages = env_root / 'site-packages'
            site_packages.mkdir(parents=True)
            (site_packages / 'old.txt').write_text('old\n', encoding='utf-8')
            installer = FakeInstaller()

            environment = PluginEnvironmentManager(
                root / 'plugin_envs',
                installer=installer,
            ).ensure_environment(plan)

            self.assertTrue((environment.site_packages / 'installed.txt').is_file())
            self.assertFalse((environment.site_packages / 'old.txt').exists())
            self.assertEqual(read_plugin_env_lock(environment.lock_path).env_hash, env_hash)
            self.assertEqual(len(installer.calls), 1)

    def test_pip_installer_uses_argv_no_index_requirements_and_wheel_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._dependency_plan(root / 'plugin')
            target = root / 'target-site-packages'
            completed = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout='',
                stderr='',
            )

            with patch('calcchain_plugin_system.environment.subprocess.run') as run:
                run.return_value = completed
                result = PipInstaller().install(plan, target, allow_online=False)

            args = run.call_args.args[0]
            self.assertEqual(args[1:4], ['-m', 'pip', 'install'])
            self.assertIn('--target', args)
            self.assertIn(str(target), args)
            self.assertIn('--no-index', args)
            self.assertIn('-r', args)
            self.assertIn(str(plan.requirements[0].path), args)
            self.assertIn('--find-links', args)
            self.assertIn(str(plan.plugin_wheel_locks[0].wheel_dir), args)
            self.assertFalse(run.call_args.kwargs['shell'])
            self.assertEqual(result, ResolvedDependencies())

    def test_pip_installer_failure_raises_dependency_install_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._dependency_plan(root / 'plugin')
            completed = subprocess.CompletedProcess(
                args=[],
                returncode=2,
                stdout='token=abc123',
                stderr='failed password=secret',
            )

            with patch('calcchain_plugin_system.environment.subprocess.run') as run:
                run.return_value = completed
                with self.assertRaises(PluginDependencyError) as caught:
                    PipInstaller().install(plan, root / 'target', allow_online=False)

            diagnostic = caught.exception.diagnostic
            self.assertEqual(diagnostic.phase, 'dependency_install')
            self.assertEqual(diagnostic.code, 'plugin_installer_failed')
            self.assertNotIn('abc123', diagnostic.safe_details['stdout'])
            self.assertNotIn('password=secret', diagnostic.safe_details['stderr'])

    def test_missing_wheel_is_rejected_before_installer_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = self._write_package(root / 'plugin', wheel_content=None)
            self._write_wheel_lock(
                package.root / 'wheels',
                [{'file': 'missing-1.0-py3-none-any.whl', 'sha256': 'a' * 64}],
            )
            plan = PluginDependencyPlanner().plan(
                self._activation_plan(package),
                shared_wheelhouse=None,
                installer_backend_version='pip 24.0',
            )
            env_hash = compute_env_hash(plan)
            installer = FakeInstaller()

            with self.assertRaises(PluginDependencyError) as caught:
                PluginEnvironmentManager(
                    root / 'plugin_envs',
                    installer=installer,
                ).ensure_environment(plan)

            self.assertEqual(caught.exception.diagnostic.phase, 'dependency_install')
            self.assertEqual(caught.exception.diagnostic.code, 'plugin_wheel_missing')
            self.assertEqual(installer.calls, [])
            self.assertFalse((root / 'plugin_envs' / env_hash).exists())

    def test_wheel_hash_mismatch_is_rejected_before_installer_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = self._write_package(root / 'plugin', wheel_content=b'wheel')
            self._write_wheel_lock(
                package.root / 'wheels',
                [{'file': 'demo-1.0-py3-none-any.whl', 'sha256': '0' * 64}],
            )
            plan = PluginDependencyPlanner().plan(
                self._activation_plan(package),
                shared_wheelhouse=None,
                installer_backend_version='pip 24.0',
            )
            env_hash = compute_env_hash(plan)
            installer = FakeInstaller()

            with self.assertRaises(PluginDependencyError) as caught:
                PluginEnvironmentManager(
                    root / 'plugin_envs',
                    installer=installer,
                ).ensure_environment(plan)

            self.assertEqual(caught.exception.diagnostic.phase, 'dependency_install')
            self.assertEqual(caught.exception.diagnostic.code, 'plugin_wheel_hash_mismatch')
            self.assertEqual(installer.calls, [])
            self.assertFalse((root / 'plugin_envs' / env_hash).exists())

    def test_installer_failure_does_not_publish_ready_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._dependency_plan(root / 'plugin')
            env_hash = compute_env_hash(plan)

            with self.assertRaises(PluginDependencyError):
                PluginEnvironmentManager(
                    root / 'plugin_envs',
                    installer=FakeInstaller(fail=True),
                ).ensure_environment(plan)

            self.assertFalse((root / 'plugin_envs' / env_hash).exists())
            self.assertEqual(list((root / 'plugin_envs').glob('.tmp-*')), [])

    def _dependency_plan(
        self,
        root: Path,
        *,
        wheel_content: bytes | None = b'wheel',
    ):
        package = self._write_package(root, wheel_content=wheel_content)
        return PluginDependencyPlanner().plan(
            self._activation_plan(package),
            shared_wheelhouse=None,
            installer_backend_version='pip 24.0',
        )

    def _activation_plan(self, package: PluginPackage) -> PluginActivationPlan:
        return PluginActivationPlan(
            enabled_packages=(package,),
            diagnostics=(),
            plugin_api_version='1.0',
            python_version='3.12.1',
            declared_capabilities=(),
        )

    def _write_package(
        self,
        root: Path,
        *,
        wheel_content: bytes | None = b'wheel',
    ) -> PluginPackage:
        root.mkdir(parents=True, exist_ok=True)
        (root / 'requirements.txt').write_text('demo==1.0\n', encoding='utf-8')
        wheel_dir = root / 'wheels'
        wheel_dir.mkdir()
        wheel_name = 'demo-1.0-py3-none-any.whl'
        wheel_records = []
        if wheel_content is not None:
            wheel_path = wheel_dir / wheel_name
            wheel_path.write_bytes(wheel_content)
            wheel_records.append({'file': wheel_name, 'sha256': sha256_file(wheel_path)})
        self._write_wheel_lock(wheel_dir, wheel_records)
        return PluginPackage(
            root=root,
            metadata_path=root / 'plugin.json',
            metadata=PluginMetadata(
                schema_version='1.0',
                plugin_id='plugin.demo',
                plugin_version='1.0.0',
                requires_plugin_api='>=1.0,<2.0',
                python_requires='>=3.10',
                entrypoint='plugin_pkg.entry:Plugin',
                dependencies=PluginDependencies(
                    mode='wheels',
                    wheels_path='wheels',
                    requirements='requirements.txt',
                ),
            ),
        )

    def _write_wheel_lock(self, wheel_dir: Path, wheels: list[dict[str, str]]) -> None:
        wheel_dir.mkdir(parents=True, exist_ok=True)
        (wheel_dir / 'wheels.lock.json').write_text(
            json.dumps({'wheels': wheels}, indent=2),
            encoding='utf-8',
        )


if __name__ == '__main__':
    unittest.main()
