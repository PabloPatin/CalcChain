import sys
import tempfile
import unittest
from types import ModuleType
from pathlib import Path
from uuid import uuid4

from calcchain_plugin_system import CapabilityKey, create_plugin_context
from calcchain_plugin_system.activation_plan import (
    PlannedCapabilityDeclaration,
    PluginActivationPlan,
)
from calcchain_plugin_system.environment import PluginEnvironment
from calcchain_plugin_system.errors import (
    PluginActivationError,
    PluginCapabilityConflictError,
    PluginDependencyError,
    PluginEntrypointError,
)
from calcchain_plugin_system.environment_lock import PluginEnvLock, write_plugin_env_lock
from calcchain_plugin_system.importer import PluginImporter
from calcchain_plugin_system.manager import PluginManager
from calcchain_plugin_system.metadata import (
    DeclaredCapability,
    PluginDependencies,
    PluginMetadata,
    PluginPackage,
)
from plugins.svn.calcchain_svn_plugin.plugin import SvnPlugin


class TestCorePluginManager(unittest.TestCase):
    def test_bundled_svn_plugin_registers_source_and_target_capabilities(self):
        context, registry = create_plugin_context(owner='calcchain.svn')

        SvnPlugin().register(context)

        snapshot = registry.snapshot()
        self.assertEqual(
            sorted(key.qualified_id for key in snapshot),
            ['source:svn', 'target:svn'],
        )
        self.assertEqual(snapshot[CapabilityKey('source', 'svn')].owner, 'calcchain.svn')
        self.assertEqual(snapshot[CapabilityKey('target', 'svn')].owner, 'calcchain.svn')

    def test_successful_activation_imports_and_registers_capabilities(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            environment = self._environment(root)
            package = self._write_package(
                root / 'plugin',
                register_body=(
                    "context.sources.register('git', object(), owner=self.plugin_id)\n"
                    "        context.reports.register('summary', object(), owner=self.plugin_id)"
                ),
                declared=(('source', 'git'), ('report', 'summary')),
            )
            manager = PluginManager()

            runtime_set = manager.activate(self._activation_plan(package), environment)

            self.assertIs(manager.active_set, runtime_set)
            self.assertEqual(runtime_set.active_owner_ids, ('plugin.demo',))
            self.assertEqual(
                sorted(key.qualified_id for key in runtime_set.capabilities),
                ['report:summary', 'source:git'],
            )
            self.assertEqual(
                runtime_set.capabilities[CapabilityKey('source', 'git')].owner,
                'plugin.demo',
            )
            with self.assertRaises(TypeError):
                runtime_set.capabilities[CapabilityKey('source', 'svn')] = object()

    def test_import_failure_is_structured_and_restores_sys_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            environment = self._environment(root)
            package = self._write_package(
                root / 'plugin',
                module_body="raise RuntimeError('token=abc123')\n",
            )
            module_name = package.metadata.entrypoint.partition(':')[0]
            stale_module = ModuleType(module_name)
            sys.modules[module_name] = stale_module
            original_path = list(sys.path)

            try:
                with self.assertRaises(PluginEntrypointError) as caught:
                    PluginImporter().import_plugin(package, environment)

                diagnostic = caught.exception.diagnostic
                self.assertEqual(diagnostic.phase, 'entrypoint_import')
                self.assertEqual(diagnostic.code, 'plugin_entrypoint_import_failed')
                self.assertNotIn('abc123', diagnostic.safe_details['error'])
                self.assertEqual(sys.path, original_path)
                self.assertIs(sys.modules[module_name], stale_module)
            finally:
                sys.modules.pop(module_name, None)

    def test_import_ignores_stale_sys_modules_cache_and_restores_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            environment = self._environment(root)
            package = self._write_package(
                root / 'plugin',
                class_body=(
                    "plugin_id = 'plugin.demo'\n"
                    "    plugin_version = '1.0.0'\n"
                    "    origin = 'package-root'\n"
                    "    def register(self, context):\n"
                    "        pass\n"
                ),
            )
            module_name = package.metadata.entrypoint.partition(':')[0]
            stale_module = ModuleType(module_name)

            class StalePlugin:
                plugin_id = 'plugin.demo'
                plugin_version = '1.0.0'
                origin = 'sys-modules-cache'

                def register(self, context):
                    return None

            stale_module.Plugin = StalePlugin
            sys.modules[module_name] = stale_module

            try:
                plugin = PluginImporter().import_plugin(package, environment)

                self.assertEqual(plugin.origin, 'package-root')
                self.assertIs(sys.modules[module_name], stale_module)
            finally:
                sys.modules.pop(module_name, None)

    def test_import_prefers_package_root_entrypoint_over_site_packages_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            environment = self._environment(root)
            package = self._write_package(
                root / 'plugin',
                class_body=(
                    "plugin_id = 'plugin.demo'\n"
                    "    plugin_version = '1.0.0'\n"
                    "    origin = 'package-root'\n"
                    "    def register(self, context):\n"
                    "        pass\n"
                ),
            )
            module_name = package.metadata.entrypoint.partition(':')[0]
            (environment.site_packages / f'{module_name}.py').write_text(
                (
                    'class Plugin:\n'
                    "    plugin_id = 'plugin.demo'\n"
                    "    plugin_version = '1.0.0'\n"
                    "    origin = 'site-packages'\n"
                    '    def register(self, context):\n'
                    '        pass\n'
                ),
                encoding='utf-8',
            )
            original_path = list(sys.path)

            plugin = PluginImporter().import_plugin(package, environment)

            self.assertEqual(plugin.origin, 'package-root')
            self.assertEqual(sys.path, original_path)
            self.assertNotIn(module_name, sys.modules)

    def test_package_entrypoint_descendant_modules_are_isolated_per_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            environment = self._environment(root)
            first = self._write_package_style_package(
                root / 'first',
                plugin_id='plugin.first',
                helper_value='first-root',
            )
            second = self._write_package_style_package(
                root / 'second',
                plugin_id='plugin.second',
                helper_value='second-root',
            )

            first_plugin = PluginImporter().import_plugin(first, environment)
            second_plugin = PluginImporter().import_plugin(second, environment)

            self.assertEqual(first_plugin.origin, 'first-root')
            self.assertEqual(second_plugin.origin, 'second-root')
            self.assertFalse(
                any(
                    name == 'plugin_pkg' or name.startswith('plugin_pkg.')
                    for name in sys.modules
                ),
            )

    def test_missing_site_packages_rejects_before_plugin_import_side_effects(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker = root / 'import-marker.txt'
            environment = self._environment(root, create_site_packages=False)
            package = self._write_side_effect_package(root / 'plugin', marker)

            with self.assertRaises(PluginDependencyError) as caught:
                PluginImporter().import_plugin(package, environment)

            self.assertEqual(caught.exception.diagnostic.phase, 'dependency_install')
            self.assertEqual(caught.exception.diagnostic.code, 'plugin_environment_not_ready')
            self.assertFalse(marker.exists())

    def test_missing_environment_lock_rejects_before_plugin_import_side_effects(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker = root / 'import-marker.txt'
            environment = self._environment(root, write_lock=False)
            package = self._write_side_effect_package(root / 'plugin', marker)

            with self.assertRaises(PluginDependencyError) as caught:
                PluginImporter().import_plugin(package, environment)

            self.assertEqual(caught.exception.diagnostic.phase, 'dependency_install')
            self.assertEqual(caught.exception.diagnostic.code, 'plugin_env_lock_read_failed')
            self.assertFalse(marker.exists())

    def test_missing_register_is_plugin_instantiate_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = self._write_package(
                root / 'plugin',
                class_body=(
                    "plugin_id = 'plugin.demo'\n"
                    "    plugin_version = '1.0.0'\n"
                ),
            )

            with self.assertRaises(PluginActivationError) as caught:
                PluginImporter().import_plugin(package, self._environment(root))

            self.assertEqual(caught.exception.diagnostic.phase, 'plugin_instantiate')
            self.assertEqual(caught.exception.diagnostic.code, 'plugin_register_missing')

    def test_missing_entrypoint_class_is_structured_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = self._write_package(
                root / 'plugin',
                module_body='class Other:\n    pass\n',
            )

            with self.assertRaises(PluginEntrypointError) as caught:
                PluginImporter().import_plugin(package, self._environment(root))

            self.assertEqual(caught.exception.diagnostic.phase, 'entrypoint_import')
            self.assertEqual(caught.exception.diagnostic.code, 'plugin_entrypoint_class_missing')

    def test_plugin_id_or_version_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = self._write_package(
                root / 'plugin',
                plugin_id='plugin.demo',
                object_plugin_id='plugin.other',
            )

            with self.assertRaises(PluginActivationError) as caught:
                PluginImporter().import_plugin(package, self._environment(root))

            self.assertEqual(caught.exception.diagnostic.code, 'plugin_id_mismatch')

            package = self._write_package(
                root / 'plugin-version',
                class_body=(
                    "plugin_id = 'plugin.demo'\n"
                    "    plugin_version = '2.0.0'\n"
                    "    def register(self, context):\n"
                    "        pass\n"
                ),
            )

            with self.assertRaises(PluginActivationError) as caught:
                PluginImporter().import_plugin(package, self._environment(root))

            self.assertEqual(caught.exception.diagnostic.code, 'plugin_version_mismatch')

    def test_register_exception_preserves_previous_active_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            environment = self._environment(root)
            good_package = self._write_package(
                root / 'good',
                plugin_id='plugin.good',
                register_body="context.sources.register('git', object(), owner=self.plugin_id)",
            )
            bad_package = self._write_package(
                root / 'bad',
                plugin_id='plugin.bad',
                register_body="raise RuntimeError('password=secret')",
            )
            manager = PluginManager()
            previous = manager.activate(self._activation_plan(good_package), environment)

            with self.assertRaises(PluginActivationError) as caught:
                manager.activate(self._activation_plan(bad_package), environment)

            self.assertIs(manager.active_set, previous)
            diagnostic = caught.exception.diagnostic
            self.assertEqual(diagnostic.phase, 'capability_registration')
            self.assertEqual(diagnostic.code, 'plugin_register_failed')
            self.assertNotIn('password=secret', diagnostic.safe_details['error'])

    def test_registration_conflict_preserves_previous_active_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            environment = self._environment(root)
            stable_package = self._write_package(
                root / 'stable',
                plugin_id='plugin.stable',
                register_body="context.sources.register('svn', object(), owner=self.plugin_id)",
            )
            first = self._write_package(
                root / 'first',
                plugin_id='plugin.first',
                register_body="context.sources.register('git', object(), owner=self.plugin_id)",
            )
            second = self._write_package(
                root / 'second',
                plugin_id='plugin.second',
                register_body="context.sources.register('git', object(), owner=self.plugin_id)",
            )
            manager = PluginManager()
            previous = manager.activate(self._activation_plan(stable_package), environment)

            with self.assertRaises(PluginCapabilityConflictError):
                manager.activate(self._activation_plan(first, second), environment)

            self.assertIs(manager.active_set, previous)

    def test_declared_capability_mismatch_is_activation_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = self._write_package(
                root / 'plugin',
                register_body="context.targets.register('git', object(), owner=self.plugin_id)",
                declared=(('source', 'git'),),
            )
            manager = PluginManager()

            with self.assertRaises(PluginActivationError) as caught:
                manager.activate(self._activation_plan(package), self._environment(root))

            diagnostic = caught.exception.diagnostic
            self.assertEqual(diagnostic.phase, 'activation_commit')
            self.assertEqual(diagnostic.code, 'plugin_declared_capabilities_mismatch')
            self.assertIsNone(manager.active_set)

    def test_fresh_draft_registry_for_every_activation_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            environment = self._environment(root)
            first = self._write_package(
                root / 'first',
                plugin_id='plugin.first',
                register_body="context.sources.register('git', object(), owner=self.plugin_id)",
            )
            second = self._write_package(
                root / 'second',
                plugin_id='plugin.second',
                register_body="context.sources.register('git', object(), owner=self.plugin_id)",
            )
            manager = PluginManager()

            first_runtime = manager.activate(self._activation_plan(first), environment)
            second_runtime = manager.activate(self._activation_plan(second), environment)

            self.assertEqual(
                first_runtime.capabilities[CapabilityKey('source', 'git')].owner,
                'plugin.first',
            )
            self.assertEqual(
                second_runtime.capabilities[CapabilityKey('source', 'git')].owner,
                'plugin.second',
            )

    def _environment(
        self,
        root: Path,
        *,
        create_site_packages: bool = True,
        write_lock: bool = True,
    ) -> PluginEnvironment:
        env_root = root / 'plugin_envs' / ('a' * 64)
        site_packages = env_root / 'site-packages'
        if create_site_packages:
            site_packages.mkdir(parents=True, exist_ok=True)
        environment = PluginEnvironment(
            root=env_root,
            env_hash='a' * 64,
            site_packages=site_packages,
            lock_path=env_root / 'plugin-env.lock.json',
        )
        if write_lock:
            write_plugin_env_lock(
                PluginEnvLock(
                    env_hash=environment.env_hash,
                    python_version='3.12.1',
                    plugin_api_version='1.0',
                    installer_backend_version='pip 24.0',
                    active_plugins=(),
                    requirements=(),
                    resolved_dependencies=(),
                    used_wheels=(),
                ),
                environment.lock_path,
            )
        return environment

    def _activation_plan(self, *packages: PluginPackage) -> PluginActivationPlan:
        declarations = []
        for package in packages:
            for capability in package.metadata.declared_capabilities:
                declarations.append(
                    PlannedCapabilityDeclaration.from_declared(
                        package.metadata.plugin_id,
                        capability,
                    ),
                )
        return PluginActivationPlan(
            enabled_packages=tuple(packages),
            diagnostics=(),
            plugin_api_version='1.0',
            python_version='3.12.1',
            declared_capabilities=tuple(declarations),
        )

    def _write_package(
        self,
        root: Path,
        *,
        plugin_id: str = 'plugin.demo',
        plugin_version: str = '1.0.0',
        object_plugin_id: str | None = None,
        module_body: str | None = None,
        class_body: str | None = None,
        register_body: str = 'pass',
        declared: tuple[tuple[str, str], ...] = (),
    ) -> PluginPackage:
        root.mkdir(parents=True, exist_ok=True)
        module_name = f'plugin_mod_{uuid4().hex}'
        module_path = root / f'{module_name}.py'
        object_plugin_id = object_plugin_id or plugin_id
        if module_body is None:
            class_body = class_body or (
                f"plugin_id = '{object_plugin_id}'\n"
                f"    plugin_version = '{plugin_version}'\n"
                "    def register(self, context):\n"
                f"        {register_body}\n"
            )
            module_body = f'class Plugin:\n    {class_body}'
        module_path.write_text(module_body, encoding='utf-8')
        sys.modules.pop(module_name, None)
        return PluginPackage(
            root=root,
            metadata_path=root / 'plugin.json',
            metadata=PluginMetadata(
                schema_version='1.0',
                plugin_id=plugin_id,
                plugin_version=plugin_version,
                requires_plugin_api='>=1.0,<2.0',
                python_requires='>=3.10',
                entrypoint=f'{module_name}:Plugin',
                dependencies=PluginDependencies(
                    mode='wheels',
                    wheels_path='wheels',
                    requirements='requirements.txt',
                ),
                declared_capabilities=tuple(
                    DeclaredCapability(namespace=namespace, id=id)
                    for namespace, id in declared
                ),
            ),
        )

    def _write_package_style_package(
        self,
        root: Path,
        *,
        plugin_id: str,
        helper_value: str,
    ) -> PluginPackage:
        package_dir = root / 'plugin_pkg'
        package_dir.mkdir(parents=True, exist_ok=True)
        (package_dir / '__init__.py').write_text('', encoding='utf-8')
        (package_dir / 'helper.py').write_text(
            f"VALUE = '{helper_value}'\n",
            encoding='utf-8',
        )
        (package_dir / 'entry.py').write_text(
            (
                'from .helper import VALUE\n'
                'class Plugin:\n'
                f"    plugin_id = '{plugin_id}'\n"
                "    plugin_version = '1.0.0'\n"
                '    origin = VALUE\n'
                '    def register(self, context):\n'
                '        pass\n'
            ),
            encoding='utf-8',
        )
        for name in tuple(sys.modules):
            if name == 'plugin_pkg' or name.startswith('plugin_pkg.'):
                sys.modules.pop(name, None)
        return PluginPackage(
            root=root,
            metadata_path=root / 'plugin.json',
            metadata=PluginMetadata(
                schema_version='1.0',
                plugin_id=plugin_id,
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

    def _write_side_effect_package(self, root: Path, marker: Path) -> PluginPackage:
        root.mkdir(parents=True, exist_ok=True)
        module_name = f'plugin_mod_{uuid4().hex}'
        (root / f'{module_name}.py').write_text(
            (
                'from pathlib import Path\n'
                f'Path({str(marker)!r}).write_text("ran", encoding="utf-8")\n'
                'class Plugin:\n'
                "    plugin_id = 'plugin.demo'\n"
                "    plugin_version = '1.0.0'\n"
                '    def register(self, context):\n'
                '        pass\n'
            ),
            encoding='utf-8',
        )
        sys.modules.pop(module_name, None)
        return PluginPackage(
            root=root,
            metadata_path=root / 'plugin.json',
            metadata=PluginMetadata(
                schema_version='1.0',
                plugin_id='plugin.demo',
                plugin_version='1.0.0',
                requires_plugin_api='>=1.0,<2.0',
                python_requires='>=3.10',
                entrypoint=f'{module_name}:Plugin',
                dependencies=PluginDependencies(
                    mode='wheels',
                    wheels_path='wheels',
                    requirements='requirements.txt',
                ),
            ),
        )


if __name__ == '__main__':
    unittest.main()
