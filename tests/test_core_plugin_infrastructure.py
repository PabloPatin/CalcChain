import inspect
import json
import tempfile
import unittest
from pathlib import Path

import calcchain_core
import calcchain_core.plugins as plugin_infrastructure
from calcchain_core.api import CalculationCore
from calcchain_core.plugin_api import CapabilityKey
from calcchain_core.plugins import (
    PluginActivationPlanner,
    PluginDiscovery,
    PluginEnvLock,
    PluginEnvironment,
    PluginManager,
    PluginSettings,
    PluginSettingsStore,
    write_plugin_env_lock,
)
from calcchain_core.sources import SourceRegistry
from calcchain_core.targets import TargetRegistry


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

            self.assertEqual(runtime_set.active_plugin_ids, ('plugin.demo',))
            self.assertEqual(
                sorted(key.qualified_id for key in runtime_set.capabilities),
                ['report:summary', 'source:demo'],
            )
            self.assertEqual(
                runtime_set.capabilities[CapabilityKey('source', 'demo')].owner,
                'plugin.demo',
            )
            self.assertFalse((root / 'plugin_envs' / '.ready').exists())

    def test_current_calculation_core_lifecycle_boundary_has_no_plugin_integration(self):
        signature = inspect.signature(CalculationCore)
        self.assertEqual(
            list(signature.parameters),
            ['job_dir', 'source_registry', 'target_registry'],
        )
        with tempfile.TemporaryDirectory() as tmp:
            core = CalculationCore(Path(tmp))

            self.assertIsInstance(core.source_registry, SourceRegistry)
            self.assertIsInstance(core.target_registry, TargetRegistry)
            self.assertFalse(hasattr(core, 'plugin_manager'))
            self.assertFalse(hasattr(core, 'plugin_runtime_set'))
            self.assertFalse(hasattr(core, 'activate_plugins'))

    def _write_plugin_package(self, plugin_root: Path) -> Path:
        package_dir = plugin_root / 'demo_plugin'
        package_dir.mkdir(parents=True)
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
