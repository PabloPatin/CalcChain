import inspect
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import calcchain_core
import calcchain_plugin_system.bootstrap as bootstrap_module
import calcchain_plugin_system as plugin_infrastructure
from calcchain_core.api import CalculationCore
from calcchain_plugin_system import CapabilityKey
from calcchain_plugin_system import PluginRuntimeSet
from calcchain_plugin_system.registrars import CapabilityRecord
from calcchain_plugin_system import (
    PluginActivationError,
    PluginActivationPlanner,
    PluginDiscovery,
    PluginEnvLock,
    PluginEnvironment,
    PluginManager,
    PluginSettings,
    PluginSettingsStore,
    activate_plugins,
    write_plugin_env_lock,
)
from calcchain_core.io.sources import SourceRegistry
from calcchain_core.io.targets import TargetRegistry


class TestCorePluginInfrastructure(unittest.TestCase):
    def test_public_and_internal_export_boundaries_are_narrow(self):
        self.assertIn('PLUGIN_API_VERSION', calcchain_core.__all__)
        self.assertIn('CalcChainPlugin', calcchain_core.__all__)
        self.assertIn('PluginContext', calcchain_core.__all__)
        self.assertNotIn('PluginManager', calcchain_core.__all__)
        self.assertNotIn('CapabilityRegistry', plugin_infrastructure.__all__)
        self.assertNotIn('CapabilityRecord', plugin_infrastructure.__all__)
        self.assertNotIn('SourceRegistrar', plugin_infrastructure.__all__)
        self.assertIn('PluginDiscovery', plugin_infrastructure.__all__)
        self.assertIn('PluginEnvironmentManager', plugin_infrastructure.__all__)
        self.assertIn('PluginManager', plugin_infrastructure.__all__)
        self.assertIn('activate_plugins', plugin_infrastructure.__all__)

    def test_explicit_bootstrap_returns_runtime_set_and_core_consumes_it(self):
        class FakeInstaller:
            def __init__(self):
                self.calls = []

            def install(self, plan, target_site_packages: Path, *, allow_online: bool):
                from calcchain_plugin_system.environment import ResolvedDependencies

                self.calls.append((plan, target_site_packages, allow_online))
                target_site_packages.mkdir(parents=True, exist_ok=True)
                return ResolvedDependencies()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_root = self._write_plugin_package(root / 'plugins' / 'demo')
            settings_path = root / 'plugins.json'
            PluginSettingsStore(settings_path).save(PluginSettings(('plugin.demo',)))
            installer = FakeInstaller()

            runtime_set = activate_plugins(
                [plugin_root.parent],
                settings_path,
                root / 'plugin_envs',
                python_executable=sys.executable,
                pip_installer=installer,
            )
            core = CalculationCore(root / 'job', plugin_runtime=runtime_set)

        self.assertEqual(runtime_set.active_owner_ids, ('plugin.demo',))
        self.assertEqual(
            sorted(key.qualified_id for key in runtime_set.capabilities),
            ['report:summary', 'source:demo'],
        )
        self.assertEqual(len(installer.calls), 1)
        self.assertFalse(installer.calls[0][2])
        self.assertIn('demo', core.source_registry._entries)
        self.assertIn('summary', core.report_registry._entries)

    def test_explicit_bootstrap_invokes_lifecycle_components_in_order(self):
        calls = []
        repository = object()
        settings = object()
        activation_plan = type('ActivationPlan', (), {'has_errors': False, 'diagnostics': ()})()
        dependency_plan = object()
        environment = object()
        runtime_set = PluginRuntimeSet(active_owner_ids=('plugin.demo',), environment=environment, capabilities={})

        class FakeDiscovery:
            def discover(self, roots):
                calls.append(('discover', roots))
                return repository

        class FakeSettingsStore:
            def __init__(self, path):
                self.path = path

            def load(self):
                calls.append(('settings', self.path))
                return settings

        class FakeActivationPlanner:
            def __init__(self, *, python_version):
                self.python_version = python_version

            def plan(self, discovered_repository, loaded_settings):
                calls.append(('activation_plan', self.python_version, discovered_repository, loaded_settings))
                return activation_plan

        class FakeDependencyPlanner:
            def plan(self, planned_activation, *, shared_wheelhouse, installer_backend_version):
                calls.append(('dependency_plan', planned_activation, shared_wheelhouse, installer_backend_version))
                return dependency_plan

        class FakeEnvironmentManager:
            def __init__(self, root, *, installer):
                self.root = root
                self.installer = installer

            def ensure_environment(self, planned_dependencies, *, allow_online):
                calls.append(('environment', self.root, self.installer, planned_dependencies, allow_online))
                return environment

        class FakePluginManager:
            def activate(self, planned_activation, prepared_environment):
                calls.append(('manager', planned_activation, prepared_environment))
                return runtime_set

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            installer = object()
            with (
                patch.object(bootstrap_module, 'PluginDiscovery', return_value=FakeDiscovery()),
                patch.object(bootstrap_module, 'PluginSettingsStore', FakeSettingsStore),
                patch.object(bootstrap_module, 'PluginActivationPlanner', FakeActivationPlanner),
                patch.object(bootstrap_module, 'PluginDependencyPlanner', return_value=FakeDependencyPlanner()),
                patch.object(bootstrap_module, 'PluginEnvironmentManager', FakeEnvironmentManager),
                patch.object(bootstrap_module, 'PluginManager', return_value=FakePluginManager()),
                patch.object(bootstrap_module, '_python_version', return_value='3.12.1'),
                patch.object(bootstrap_module, '_pip_version', return_value='pip 24.0'),
            ):
                result = activate_plugins(
                    [root / 'plugins'],
                    root / 'plugins.json',
                    root / 'plugin_envs',
                    python_executable=sys.executable,
                    pip_installer=installer,
                )

        self.assertIs(result, runtime_set)
        self.assertEqual(
            calls,
            [
                ('discover', (root / 'plugins',)),
                ('settings', root / 'plugins.json'),
                ('activation_plan', '3.12.1', repository, settings),
                ('dependency_plan', activation_plan, None, 'pip 24.0'),
                ('environment', root / 'plugin_envs', installer, dependency_plan, False),
                ('manager', activation_plan, environment),
            ],
        )

    def test_calculation_core_constructor_does_not_call_explicit_bootstrap(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('calcchain_plugin_system.bootstrap.PluginDiscovery') as discovery:
                CalculationCore(Path(tmp))

        discovery.assert_not_called()

    def test_explicit_bootstrap_fails_fast_before_environment_for_invalid_activation_plan(self):
        class FakeInstaller:
            def __init__(self):
                self.calls = []

            def install(self, plan, target_site_packages: Path, *, allow_online: bool):
                self.calls.append((plan, target_site_packages, allow_online))
                raise AssertionError('installer must not be called')

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_root = self._write_plugin_package(root / 'plugins' / 'demo')
            settings_path = root / 'plugins.json'
            envs_dir = root / 'plugin_envs'
            PluginSettingsStore(settings_path).save(PluginSettings(('plugin.missing', 'plugin.demo')))
            installer = FakeInstaller()

            with self.assertRaises(PluginActivationError) as caught:
                activate_plugins(
                    [plugin_root.parent],
                    settings_path,
                    envs_dir,
                    python_executable=sys.executable,
                    pip_installer=installer,
                )

        self.assertEqual(caught.exception.diagnostic.code, 'plugin_activation_plan_invalid')
        self.assertEqual(installer.calls, [])
        self.assertFalse(envs_dir.exists())

    def test_demo_main_uses_explicit_bootstrap_without_network_operations(self):
        import examples.plugin_system.plugin_system_demo as demo

        runtime_set = PluginRuntimeSet(active_owner_ids=('plugin.demo',), environment=object(), capabilities={})

        with patch.object(demo, 'activate_plugins', return_value=runtime_set) as activate:
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = demo.main()

        self.assertEqual(exit_code, 0)
        activate.assert_called_once_with(demo.PLUGIN_ROOTS, demo.PLUGIN_SETTINGS, demo.PLUGIN_ENVS)
        self.assertIn("active plugin ids: ('plugin.demo',)", output.getvalue())
        self.assertIn('No SVN network operation is run by this demo.', output.getvalue())

    def test_temp_plugin_package_end_to_end_infrastructure_smoke(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_root = self._write_plugin_package(root / 'plugins' / 'demo')
            settings_path = root / 'plugins.json'
            environment = self._ready_environment(root / 'plugin_envs')

            repository = PluginDiscovery().discover([plugin_root.parent])
            PluginSettingsStore(settings_path).save(PluginSettings(('plugin.demo',)))
            settings = PluginSettingsStore(settings_path).load()
            plan = PluginActivationPlanner(python_version='3.12.1').plan(repository, settings)

            self.assertFalse(plan.has_errors)
            runtime_set = PluginManager().activate(plan, environment)

            self.assertEqual(runtime_set.active_owner_ids, ('plugin.demo',))
            self.assertEqual(
                sorted(key.qualified_id for key in runtime_set.capabilities),
                ['report:summary', 'source:demo'],
            )
            self.assertEqual(
                runtime_set.capabilities[CapabilityKey('source', 'demo')].owner,
                'plugin.demo',
            )
            self.assertFalse((root / 'plugin_envs' / '.ready').exists())

    def test_calculation_core_accepts_plugin_runtime_without_lifecycle_helpers(self):
        signature = inspect.signature(CalculationCore)
        self.assertEqual(
            list(signature.parameters),
            ['job_dir', 'plugin_runtime', 'source_registry', 'target_registry', 'auth_service'],
        )
        with tempfile.TemporaryDirectory() as tmp:
            core = CalculationCore(Path(tmp))

            self.assertIsInstance(core.source_registry, SourceRegistry)
            self.assertIsInstance(core.target_registry, TargetRegistry)
            self.assertFalse(hasattr(core, 'plugin_manager'))
            self.assertFalse(hasattr(core, 'plugin_runtime_set'))
            self.assertFalse(hasattr(core, 'activate_plugins'))

    def test_calculation_core_builds_registries_from_supplied_runtime_only(self):
        auth_service = object()
        runtime = PluginRuntimeSet(
            active_owner_ids=('plugin.demo',),
            environment=object(),
            capabilities={
                CapabilityKey('source', 'demo-source'): CapabilityRecord(
                    key=CapabilityKey('source', 'demo-source'),
                    capability=object(),
                    owner='plugin.demo',
                ),
                CapabilityKey('target', 'demo-target'): CapabilityRecord(
                    key=CapabilityKey('target', 'demo-target'),
                    capability=object(),
                    owner='plugin.demo',
                ),
            },
        )

        with tempfile.TemporaryDirectory() as tmp:
            core = CalculationCore(Path(tmp), plugin_runtime=runtime, auth_service=auth_service)

        self.assertIn('local', core.source_registry._entries)
        self.assertIn('local', core.target_registry._entries)
        self.assertIn('demo-source', core.source_registry._entries)
        self.assertIn('demo-target', core.target_registry._entries)
        self.assertEqual(core.source_registry._entries['demo-source'].plugin_id, 'plugin.demo')
        self.assertEqual(core.target_registry._entries['demo-target'].plugin_id, 'plugin.demo')
        self.assertFalse(hasattr(core, 'plugin_manager'))
        self.assertFalse(hasattr(core, 'activate_plugins'))

    def test_calculation_core_injected_registries_override_plugin_runtime_factories(self):
        runtime = PluginRuntimeSet(
            active_owner_ids=('plugin.demo',),
            environment=object(),
            capabilities={
                CapabilityKey('source', 'demo-source'): CapabilityRecord(
                    key=CapabilityKey('source', 'demo-source'),
                    capability=object(),
                    owner='plugin.demo',
                ),
                CapabilityKey('target', 'demo-target'): CapabilityRecord(
                    key=CapabilityKey('target', 'demo-target'),
                    capability=object(),
                    owner='plugin.demo',
                ),
            },
        )
        source_registry = SourceRegistry()
        target_registry = TargetRegistry()

        with tempfile.TemporaryDirectory() as tmp:
            core = CalculationCore(
                Path(tmp),
                plugin_runtime=runtime,
                source_registry=source_registry,
                target_registry=target_registry,
            )

        self.assertIs(core.source_registry, source_registry)
        self.assertIs(core.target_registry, target_registry)
        self.assertNotIn('demo-source', core.source_registry._entries)
        self.assertNotIn('demo-target', core.target_registry._entries)

    def _write_plugin_package(self, plugin_root: Path) -> Path:
        package_dir = plugin_root / 'demo_plugin'
        package_dir.mkdir(parents=True)
        (plugin_root / 'requirements.txt').write_text('', encoding='utf-8')
        wheels_dir = plugin_root / 'wheels'
        wheels_dir.mkdir()
        (wheels_dir / 'wheels.lock.json').write_text(
            json.dumps({'wheels': []}, indent=2),
            encoding='utf-8',
        )
        (package_dir / '__init__.py').write_text('', encoding='utf-8')
        (package_dir / 'entry.py').write_text(
            (
                'class Plugin:\n'
                "    plugin_id = 'plugin.demo'\n"
                "    plugin_version = '1.0.0'\n"
                '    def register(self, context):\n'
                "        context.sources.register('demo', object(), owner=self.plugin_id)\n"
                "        context.reports.register('summary', object(), owner=self.plugin_id)\n"
            ),
            encoding='utf-8',
        )
        (plugin_root / 'plugin.json').write_text(
            json.dumps(
                {
                    'schema_version': '1.0',
                    'plugin_id': 'plugin.demo',
                    'plugin_version': '1.0.0',
                    'requires_plugin_api': '>=1.0,<2.0',
                    'python_requires': '>=3.10',
                    'entrypoint': 'demo_plugin.entry:Plugin',
                    'dependencies': {
                        'mode': 'wheels',
                        'wheels_path': 'wheels',
                        'requirements': 'requirements.txt',
                    },
                    'declared_capabilities': [
                        {'namespace': 'source', 'id': 'demo'},
                        {'namespace': 'report', 'id': 'summary'},
                    ],
                },
                indent=2,
            ),
            encoding='utf-8',
        )
        return plugin_root

    def _ready_environment(self, plugin_envs_dir: Path) -> PluginEnvironment:
        env_hash = 'b' * 64
        env_root = plugin_envs_dir / env_hash
        site_packages = env_root / 'site-packages'
        site_packages.mkdir(parents=True)
        environment = PluginEnvironment(
            root=env_root,
            env_hash=env_hash,
            site_packages=site_packages,
            lock_path=env_root / 'plugin-env.lock.json',
        )
        write_plugin_env_lock(
            PluginEnvLock(
                env_hash=env_hash,
                python_version='3.12.1',
                plugin_api_version='1.0',
                installer_backend_version='fake',
                active_plugins=(),
                requirements=(),
                resolved_dependencies=(),
                used_wheels=(),
            ),
            environment.lock_path,
        )
        return environment


if __name__ == '__main__':
    unittest.main()
