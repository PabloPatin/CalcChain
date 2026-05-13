import json
import tempfile
import unittest
from pathlib import Path

from calcchain_core.plugins.activation_plan import PluginActivationPlanner
from calcchain_core.plugins.errors import PluginError
from calcchain_core.plugins.metadata import (
    DeclaredCapability,
    PluginDependencies,
    PluginMetadata,
    PluginPackage,
)
from calcchain_core.plugins.repository import PluginRepository
from calcchain_core.plugins.settings import PluginSettings, PluginSettingsStore


class TestCorePluginActivationPlan(unittest.TestCase):
    def test_missing_plugins_json_means_empty_enabled_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = PluginSettingsStore(Path(tmp) / 'plugins.json').load()

        self.assertEqual(settings.enabled_plugins, ())

    def test_settings_save_load_roundtrip_uses_ids_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / 'config' / 'plugins.json'
            store = PluginSettingsStore(settings_path)

            store.save(PluginSettings(enabled_plugins=('plugin.one', 'plugin.two')))
            loaded = store.load()

            self.assertEqual(loaded.enabled_plugins, ('plugin.one', 'plugin.two'))
            self.assertEqual(
                json.loads(settings_path.read_text(encoding='utf-8')),
                {'enabled_plugins': ['plugin.one', 'plugin.two']},
            )

    def test_settings_invalid_json_uses_public_plugin_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / 'plugins.json'
            settings_path.write_text('{"enabled_plugins": [', encoding='utf-8')

            with self.assertRaises(PluginError) as caught:
                PluginSettingsStore(settings_path).load()

            self.assertEqual(caught.exception.diagnostic.phase, 'dependency_plan')
            self.assertEqual(caught.exception.diagnostic.code, 'plugin_settings_invalid_json')

    def test_settings_invalid_shape_uses_public_plugin_error(self):
        invalid_settings = (
            {'enabled_plugins': 'plugin.one'},
            {'enabled_plugins': ['plugin.one', '']},
        )
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / 'plugins.json'
            for data in invalid_settings:
                with self.subTest(data=data):
                    settings_path.write_text(json.dumps(data), encoding='utf-8')

                    with self.assertRaises(PluginError) as caught:
                        PluginSettingsStore(settings_path).load()

                    self.assertEqual(caught.exception.diagnostic.phase, 'dependency_plan')
                    self.assertEqual(caught.exception.diagnostic.code, 'plugin_settings_invalid')

    def test_planner_reports_missing_installed_plugin_id(self):
        plan = PluginActivationPlanner(python_version='3.12.1').plan(
            PluginRepository(),
            PluginSettings(enabled_plugins=('missing.plugin',)),
        )

        self.assertEqual(plan.enabled_packages, ())
        self.assertEqual(plan.diagnostics[0].code, 'plugin_enabled_id_missing')
        self.assertEqual(plan.diagnostics[0].phase, 'dependency_plan')

    def test_planner_reports_duplicate_enabled_ids_deterministically(self):
        repository = self._repository(
            self._package('plugin.one', capabilities=(('source', 'git'),)),
        )

        plan = PluginActivationPlanner(python_version='3.12.1').plan(
            repository,
            PluginSettings(enabled_plugins=('plugin.one', 'plugin.one')),
        )

        self.assertEqual(plan.enabled_plugin_ids, ('plugin.one',))
        self.assertEqual(
            [diagnostic.code for diagnostic in plan.diagnostics],
            ['plugin_enabled_id_duplicate'],
        )

    def test_planner_reports_compatibility_failure_for_enabled_package(self):
        repository = self._repository(
            self._package('plugin.one', requires_plugin_api='>=2.0,<3.0'),
        )

        plan = PluginActivationPlanner(plugin_api_version='1.0', python_version='3.12.1').plan(
            repository,
            PluginSettings(enabled_plugins=('plugin.one',)),
        )

        self.assertEqual(plan.enabled_plugin_ids, ('plugin.one',))
        self.assertEqual(plan.diagnostics[0].code, 'plugin_api_incompatible')
        self.assertEqual(plan.diagnostics[0].phase, 'compatibility_check')

    def test_preliminary_declared_capability_conflict_is_diagnosed(self):
        repository = self._repository(
            self._package('plugin.one', capabilities=(('source', 'git'),)),
            self._package('plugin.two', capabilities=(('source', 'git'),)),
        )

        plan = PluginActivationPlanner(python_version='3.12.1').plan(
            repository,
            PluginSettings(enabled_plugins=('plugin.one', 'plugin.two')),
        )

        self.assertEqual(plan.enabled_plugin_ids, ('plugin.one', 'plugin.two'))
        self.assertEqual(plan.diagnostics[0].code, 'plugin_declared_capability_conflict')
        self.assertEqual(plan.diagnostics[0].safe_details['existing_plugin_id'], 'plugin.one')
        self.assertEqual(plan.diagnostics[0].safe_details['plugin_id'], 'plugin.two')

    def test_same_capability_id_in_different_namespaces_is_allowed_and_ordered(self):
        repository = self._repository(
            self._package('plugin.one', capabilities=(('source', 'git'),)),
            self._package('plugin.two', capabilities=(('target', 'git'),)),
        )

        plan = PluginActivationPlanner(
            plugin_api_version='1.0',
            python_version='3.12.1',
        ).plan(
            repository,
            PluginSettings(enabled_plugins=('plugin.two', 'plugin.one')),
        )

        self.assertFalse(plan.has_errors)
        self.assertEqual(plan.enabled_plugin_ids, ('plugin.two', 'plugin.one'))
        self.assertEqual(plan.plugin_api_version, '1.0')
        self.assertEqual(plan.python_version, '3.12.1')
        self.assertEqual(
            [
                (capability.plugin_id, capability.qualified_id)
                for capability in plan.declared_capabilities
            ],
            [('plugin.two', 'target:git'), ('plugin.one', 'source:git')],
        )

    def _repository(self, *packages: PluginPackage) -> PluginRepository:
        repository = PluginRepository()
        for package in packages:
            repository.add(package)
        return repository

    def _package(
        self,
        plugin_id: str,
        *,
        requires_plugin_api: str = '>=1.0,<2.0',
        python_requires: str = '>=3.10',
        capabilities: tuple[tuple[str, str], ...] = (),
    ) -> PluginPackage:
        root = Path('D:/unused') / plugin_id
        return PluginPackage(
            root=root,
            metadata_path=root / 'plugin.json',
            metadata=PluginMetadata(
                schema_version='1.0',
                plugin_id=plugin_id,
                plugin_version='1.0.0',
                requires_plugin_api=requires_plugin_api,
                python_requires=python_requires,
                entrypoint='plugin_pkg.entry:Plugin',
                dependencies=PluginDependencies(
                    mode='wheels',
                    wheels_path='wheels',
                    requirements='requirements.txt',
                ),
                declared_capabilities=tuple(
                    DeclaredCapability(namespace=namespace, id=capability_id)
                    for namespace, capability_id in capabilities
                ),
            ),
        )


if __name__ == '__main__':
    unittest.main()
