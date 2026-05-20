import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from calcchain_core.hash import sha256_file
from calcchain_plugin_system.activation_plan import PluginActivationPlan
from calcchain_plugin_system.dependencies import (
    PluginDependencyPlanner,
    WheelLockReader,
    compute_env_hash,
    verify_wheel_hashes,
)
from calcchain_plugin_system.environment_lock import (
    PLUGIN_ENV_LOCK_NAME,
    PluginEnvLock,
    read_plugin_env_lock,
    verify_plugin_env_lock,
    write_plugin_env_lock,
)
from calcchain_capabilities.errors import PluginDependencyError
from calcchain_plugin_system.metadata import PluginDependencies, PluginMetadata, PluginPackage


class TestCorePluginDependencies(unittest.TestCase):
    def test_env_hash_is_stable_for_identical_path_independent_inputs(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_plan = self._dependency_plan(Path(first), requirements_text='demo==1.0\n')
            second_plan = self._dependency_plan(Path(second), requirements_text='demo==1.0\n')

            self.assertEqual(compute_env_hash(first_plan), compute_env_hash(second_plan))

    def test_env_hash_changes_when_requirements_content_changes(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_plan = self._dependency_plan(Path(first), requirements_text='demo==1.0\n')
            second_plan = self._dependency_plan(Path(second), requirements_text='demo==2.0\n')

            self.assertNotEqual(compute_env_hash(first_plan), compute_env_hash(second_plan))

    def test_env_hash_changes_when_plugin_version_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_plan = self._dependency_plan(root / 'first', plugin_version='1.0.0')
            second_plan = self._dependency_plan(root / 'second', plugin_version='2.0.0')

            self.assertNotEqual(compute_env_hash(first_plan), compute_env_hash(second_plan))

    def test_env_hash_changes_when_installer_or_wheel_hash_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_plan = self._dependency_plan(
                root / 'first',
                installer_backend_version='pip 24.0',
            )
            second_plan = self._dependency_plan(
                root / 'second',
                installer_backend_version='pip 25.0',
            )
            third_plan = self._dependency_plan(root / 'third', wheel_content=b'different-wheel')

            self.assertNotEqual(compute_env_hash(first_plan), compute_env_hash(second_plan))
            self.assertNotEqual(compute_env_hash(first_plan), compute_env_hash(third_plan))

    def test_verify_wheel_hashes_accepts_plugin_and_shared_wheelhouse_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._dependency_plan(root / 'plugin', wheel_content=b'plugin-wheel')
            self.assertEqual(verify_wheel_hashes(plan)[0].source, 'plugin')

            shared_root = root / 'shared-case'
            package = self._write_package(shared_root / 'plugin', wheel_content=None)
            shared_wheelhouse = shared_root / 'wheelhouse'
            shared_wheelhouse.mkdir()
            shared_wheel = shared_wheelhouse / 'demo-1.0-py3-none-any.whl'
            shared_wheel.write_bytes(b'shared-wheel')
            self._write_wheel_lock(
                package.root / 'wheels',
                [{'file': shared_wheel.name, 'sha256': sha256_file(shared_wheel)}],
            )
            shared_plan = PluginDependencyPlanner().plan(
                self._activation_plan(package),
                shared_wheelhouse=shared_wheelhouse,
                installer_backend_version='pip 24.0',
            )

            record = verify_wheel_hashes(shared_plan)[0]
            self.assertEqual(record.source, 'shared')
            self.assertEqual(record.path, shared_wheel)

    def test_wheel_sha256_mismatch_is_rejected_before_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            package = self._write_package(Path(tmp), wheel_content=b'wheel')
            self._write_wheel_lock(
                package.root / 'wheels',
                [{'file': 'demo-1.0-py3-none-any.whl', 'sha256': '0' * 64}],
            )
            plan = PluginDependencyPlanner().plan(
                self._activation_plan(package),
                shared_wheelhouse=None,
                installer_backend_version='pip 24.0',
            )

            with self.assertRaises(PluginDependencyError) as caught:
                verify_wheel_hashes(plan)

            self.assertEqual(caught.exception.diagnostic.code, 'plugin_wheel_hash_mismatch')

    def test_missing_locked_wheel_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            package = self._write_package(Path(tmp), wheel_content=None)
            self._write_wheel_lock(
                package.root / 'wheels',
                [{'file': 'missing-1.0-py3-none-any.whl', 'sha256': 'a' * 64}],
            )
            plan = PluginDependencyPlanner().plan(
                self._activation_plan(package),
                shared_wheelhouse=None,
                installer_backend_version='pip 24.0',
            )

            with self.assertRaises(PluginDependencyError) as caught:
                verify_wheel_hashes(plan)

            self.assertEqual(caught.exception.diagnostic.code, 'plugin_wheel_missing')

    def test_unsafe_requirements_path_is_rejected_before_hashing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = self._write_package(root / 'plugin')
            outside = root / 'outside.txt'
            outside.write_text('secret-ish', encoding='utf-8')
            unsafe_values = ('../outside.txt', 'C:outside.txt')

            for requirements in unsafe_values:
                with self.subTest(requirements=requirements):
                    unsafe_package = PluginPackage(
                        root=package.root,
                        metadata_path=package.metadata_path,
                        metadata=replace(
                            package.metadata,
                            dependencies=replace(
                                package.metadata.dependencies,
                                requirements=requirements,
                            ),
                        ),
                    )

                    with self.assertRaises(PluginDependencyError) as caught:
                        PluginDependencyPlanner().plan(
                            self._activation_plan(unsafe_package),
                            shared_wheelhouse=None,
                            installer_backend_version='pip 24.0',
                        )

                    self.assertEqual(
                        caught.exception.diagnostic.code,
                        'plugin_requirements_path_unsafe',
                    )

    def test_unsafe_wheel_file_name_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock_dir = Path(tmp)
            unsafe_locks = (
                '../escape.whl',
                'nested/package.whl',
                'nested\\package.whl',
                '/absolute/package.whl',
                'C:demo.whl',
            )
            for wheel_name in unsafe_locks:
                with self.subTest(wheel_name=wheel_name):
                    self._write_wheel_lock(lock_dir, [{'file': wheel_name, 'sha256': 'a' * 64}])
                    with self.assertRaises(PluginDependencyError) as caught:
                        WheelLockReader().read(lock_dir / 'wheels.lock.json')
                    self.assertEqual(caught.exception.diagnostic.code, 'plugin_wheel_name_unsafe')

    def test_plugin_env_lock_write_read_and_verify_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._dependency_plan(root / 'plugin')
            used_wheels = verify_wheel_hashes(plan)
            lock = PluginEnvLock.from_plan(plan, used_wheels=used_wheels)
            env_dir = root / 'plugin_envs' / lock.env_hash

            write_plugin_env_lock(lock, env_dir / PLUGIN_ENV_LOCK_NAME)

            self.assertEqual(read_plugin_env_lock(env_dir / PLUGIN_ENV_LOCK_NAME), lock)
            self.assertEqual(verify_plugin_env_lock(env_dir, lock.env_hash), lock)
            self.assertFalse((env_dir / '.ready').exists())

    def test_plugin_env_lock_missing_malformed_and_mismatch_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_dir = Path(tmp)
            with self.assertRaises(PluginDependencyError) as missing:
                verify_plugin_env_lock(env_dir, 'a' * 64)
            self.assertEqual(missing.exception.diagnostic.code, 'plugin_env_lock_read_failed')

            lock_path = env_dir / PLUGIN_ENV_LOCK_NAME
            lock_path.write_text('{bad-json', encoding='utf-8')
            with self.assertRaises(PluginDependencyError) as malformed:
                verify_plugin_env_lock(env_dir, 'a' * 64)
            self.assertEqual(malformed.exception.diagnostic.code, 'plugin_env_lock_invalid_json')

            with tempfile.TemporaryDirectory() as package_tmp:
                plan = self._dependency_plan(Path(package_tmp))
                lock = PluginEnvLock.from_plan(plan, used_wheels=verify_wheel_hashes(plan))
                write_plugin_env_lock(lock, lock_path)
                with self.assertRaises(PluginDependencyError) as mismatch:
                    verify_plugin_env_lock(env_dir, 'b' * 64)
                self.assertEqual(
                    mismatch.exception.diagnostic.code,
                    'plugin_env_lock_hash_mismatch',
                )

    def test_plugin_env_lock_rejects_changed_wheel_hash_material(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original_plan = self._dependency_plan(root / 'original', wheel_content=b'wheel')
            original_lock = PluginEnvLock.from_plan(
                original_plan,
                used_wheels=verify_wheel_hashes(original_plan),
            )
            env_dir = root / 'plugin_envs' / original_lock.env_hash
            write_plugin_env_lock(original_lock, env_dir / PLUGIN_ENV_LOCK_NAME)

            changed_plan = self._dependency_plan(root / 'changed', wheel_content=b'changed-wheel')

            with self.assertRaises(PluginDependencyError) as caught:
                verify_plugin_env_lock(env_dir, compute_env_hash(changed_plan))

            self.assertEqual(
                caught.exception.diagnostic.code,
                'plugin_env_lock_hash_mismatch',
            )

    def _dependency_plan(
        self,
        root: Path,
        *,
        requirements_text: str = 'demo==1.0\n',
        wheel_content: bytes | None = b'wheel',
        installer_backend_version: str = 'pip 24.0',
        plugin_version: str = '1.0.0',
    ):
        package = self._write_package(
            root,
            requirements_text=requirements_text,
            wheel_content=wheel_content,
            plugin_version=plugin_version,
        )
        return PluginDependencyPlanner().plan(
            self._activation_plan(package),
            shared_wheelhouse=None,
            installer_backend_version=installer_backend_version,
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
        requirements_text: str = 'demo==1.0\n',
        wheel_content: bytes | None = b'wheel',
        plugin_version: str = '1.0.0',
    ) -> PluginPackage:
        root.mkdir(parents=True, exist_ok=True)
        requirements = root / 'requirements.txt'
        requirements.write_text(requirements_text, encoding='utf-8')
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
                plugin_version=plugin_version,
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
