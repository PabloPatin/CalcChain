import json
import sys
import tempfile
import unittest
from pathlib import Path

from calcchain_plugin_system.discovery import PluginDiscovery
from calcchain_capabilities.errors import PluginCompatibilityError, PluginMetadataError
from calcchain_plugin_system.metadata import (
    PluginMetadataReader,
    PluginPackage,
    PluginValidator,
)
from calcchain_plugin_system.repository import PluginRepository


class TestCorePluginMetadata(unittest.TestCase):
    def test_valid_metadata_read_and_validate(self):
        with tempfile.TemporaryDirectory() as tmp:
            package_root = self._write_plugin_package(Path(tmp), 'valid_plugin')
            metadata = PluginMetadataReader().read(package_root / 'plugin.json')

            PluginValidator().validate_package(package_root, metadata, python_version='3.12.1')

            self.assertEqual(metadata.plugin_id, 'valid_plugin')
            self.assertEqual(metadata.dependencies.mode, 'wheels')
            self.assertEqual(metadata.declared_capabilities[0].namespace, 'source')

    def test_missing_required_fields_raise_metadata_error(self):
        required_fields = (
            'schema_version',
            'plugin_id',
            'plugin_version',
            'requires_plugin_api',
            'python_requires',
            'entrypoint',
            'dependencies',
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for field in required_fields:
                with self.subTest(field=field):
                    package_root = self._write_plugin_package(root / field, f'plugin_{field}')
                    data = self._metadata_dict(f'plugin_{field}')
                    del data[field]
                    self._write_json(package_root / 'plugin.json', data)

                    with self.assertRaises(PluginMetadataError) as caught:
                        PluginMetadataReader().read(package_root / 'plugin.json')

                    self.assertEqual(caught.exception.diagnostic.phase, 'metadata_validation')

    def test_invalid_json_uses_metadata_read_phase(self):
        with tempfile.TemporaryDirectory() as tmp:
            metadata_path = Path(tmp) / 'plugin.json'
            metadata_path.write_text('{not-json', encoding='utf-8')

            with self.assertRaises(PluginMetadataError) as caught:
                PluginMetadataReader().read(metadata_path)

            self.assertEqual(caught.exception.diagnostic.phase, 'metadata_read')
            self.assertEqual(caught.exception.diagnostic.code, 'plugin_metadata_invalid_json')

    def test_requires_plugin_api_and_python_requires_compatibility(self):
        with tempfile.TemporaryDirectory() as tmp:
            package_root = self._write_plugin_package(Path(tmp), 'compatible')
            metadata = PluginMetadataReader().read(package_root / 'plugin.json')
            validator = PluginValidator()

            validator.validate_package(
                package_root,
                metadata,
                plugin_api_version='1.0',
                python_version='3.12.0',
            )

            with self.assertRaises(PluginCompatibilityError) as api_error:
                validator.validate_package(
                    package_root,
                    metadata,
                    plugin_api_version='2.0',
                    python_version='3.12.0',
                )
            self.assertEqual(api_error.exception.diagnostic.phase, 'compatibility_check')

            with self.assertRaises(PluginCompatibilityError) as python_error:
                validator.validate_package(
                    package_root,
                    metadata,
                    plugin_api_version='1.0',
                    python_version='2.7.18',
                )
            self.assertEqual(python_error.exception.diagnostic.code, 'plugin_python_incompatible')

    def test_invalid_specifiers_and_unsupported_dependency_mode_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            invalid_spec_root = self._write_plugin_package(root / 'invalid_spec', 'invalid_spec')
            data = self._metadata_dict('invalid_spec')
            data['requires_plugin_api'] = 'not-a-specifier'
            self._write_json(invalid_spec_root / 'plugin.json', data)
            metadata = PluginMetadataReader().read(invalid_spec_root / 'plugin.json')

            with self.assertRaises(PluginMetadataError) as specifier_error:
                PluginValidator().validate_package(invalid_spec_root, metadata)
            self.assertEqual(specifier_error.exception.diagnostic.phase, 'metadata_validation')

            deps_root = self._write_plugin_package(root / 'deps_mode', 'deps_mode')
            data = self._metadata_dict('deps_mode')
            data['dependencies']['mode'] = 'deps'
            self._write_json(deps_root / 'plugin.json', data)
            metadata = PluginMetadataReader().read(deps_root / 'plugin.json')

            with self.assertRaises(PluginMetadataError) as mode_error:
                PluginValidator().validate_package(deps_root, metadata)
            self.assertEqual(
                mode_error.exception.diagnostic.code,
                'plugin_dependency_mode_unsupported',
            )

    def test_invalid_entrypoint_is_rejected_without_importing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package_root = self._write_plugin_package(root, 'bad_entrypoint')
            marker = package_root / 'validator_imported.txt'
            (package_root / 'plugin_pkg' / 'entry.py').write_text(
                f"from pathlib import Path\nPath({str(marker)!r}).write_text('imported')\n",
                encoding='utf-8',
            )
            sys.modules.pop('plugin_pkg.entry', None)
            metadata = PluginMetadataReader().read(package_root / 'plugin.json')

            PluginValidator().validate_package(package_root, metadata)

            self.assertFalse(marker.exists())
            self.assertNotIn('plugin_pkg.entry', sys.modules)

            data = self._metadata_dict('bad_entrypoint')
            invalid_entrypoints = (
                '../outside:Plugin',
                '..\\outside:Plugin',
                '/outside/plugin.py:Plugin',
            )
            for entrypoint in invalid_entrypoints:
                with self.subTest(entrypoint=entrypoint):
                    data['entrypoint'] = entrypoint
                    self._write_json(package_root / 'plugin.json', data)
                    metadata = PluginMetadataReader().read(package_root / 'plugin.json')

                    with self.assertRaises(PluginMetadataError):
                        PluginValidator().validate_package(package_root, metadata)

            data['entrypoint'] = 'plugin_pkg.missing:Plugin'
            self._write_json(package_root / 'plugin.json', data)
            metadata = PluginMetadataReader().read(package_root / 'plugin.json')

            with self.assertRaises(PluginMetadataError) as missing_error:
                PluginValidator().validate_package(package_root, metadata)
            self.assertEqual(
                missing_error.exception.diagnostic.safe_details['field'],
                'entrypoint',
            )

    def test_declared_capability_namespace_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            package_root = self._write_plugin_package(Path(tmp), 'bad_capability')
            data = self._metadata_dict('bad_capability')
            data['declared_capabilities'] = [{'namespace': 'config', 'id': 'main'}]
            self._write_json(package_root / 'plugin.json', data)
            metadata = PluginMetadataReader().read(package_root / 'plugin.json')

            with self.assertRaises(PluginMetadataError) as caught:
                PluginValidator().validate_package(package_root, metadata)

            self.assertEqual(
                caught.exception.diagnostic.code,
                'plugin_declared_capability_namespace_unsupported',
            )

    def test_discovery_finds_direct_and_child_packages_without_importing_plugin_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            direct_root = self._write_plugin_package(root / 'direct', 'direct_plugin')
            child_plugins = root / 'plugins'
            child_root = self._write_plugin_package(child_plugins / 'child', 'child_plugin')
            marker = child_root / 'imported.txt'
            (child_root / 'plugin_pkg' / 'entry.py').write_text(
                f"from pathlib import Path\nPath({str(marker)!r}).write_text('imported')\n",
                encoding='utf-8',
            )
            sys.modules.pop('plugin_pkg.entry', None)

            repository = PluginDiscovery().discover([direct_root, child_plugins])

            self.assertEqual(sorted(repository.snapshot()), ['child_plugin', 'direct_plugin'])
            self.assertFalse(marker.exists())
            self.assertNotIn('plugin_pkg.entry', sys.modules)

    def test_repository_rejects_duplicate_plugin_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = self._package_for(root / 'first', 'duplicate')
            second = self._package_for(root / 'second', 'duplicate')
            repository = PluginRepository()

            repository.add(first)
            with self.assertRaises(PluginMetadataError) as caught:
                repository.add(second)

            self.assertEqual(caught.exception.diagnostic.code, 'plugin_id_duplicate')
            self.assertEqual(len(repository), 1)

    def _package_for(self, package_root: Path, plugin_id: str) -> PluginPackage:
        root = self._write_plugin_package(package_root, plugin_id)
        metadata_path = root / 'plugin.json'
        metadata = PluginMetadataReader().read(metadata_path)
        PluginValidator().validate_package(root, metadata, python_version='3.12.1')
        return PluginPackage(root=root, metadata_path=metadata_path, metadata=metadata)

    def _write_plugin_package(self, package_root: Path, plugin_id: str) -> Path:
        package_root.mkdir(parents=True, exist_ok=True)
        package_dir = package_root / 'plugin_pkg'
        package_dir.mkdir(exist_ok=True)
        (package_dir / '__init__.py').write_text('', encoding='utf-8')
        (package_dir / 'entry.py').write_text('class Plugin:\n    pass\n', encoding='utf-8')
        self._write_json(package_root / 'plugin.json', self._metadata_dict(plugin_id))
        return package_root

    def _metadata_dict(self, plugin_id: str) -> dict[str, object]:
        return {
            'schema_version': '1.0',
            'plugin_id': plugin_id,
            'plugin_version': '1.2.3',
            'requires_plugin_api': '>=1.0,<2.0',
            'python_requires': '>=3.10',
            'entrypoint': 'plugin_pkg.entry:Plugin',
            'dependencies': {
                'mode': 'wheels',
                'wheels_path': 'wheels',
                'requirements': 'requirements.txt',
            },
            'declared_capabilities': [{'namespace': 'source', 'id': 'git'}],
        }

    def _write_json(self, path: Path, data: dict[str, object]) -> None:
        path.write_text(json.dumps(data, indent=2), encoding='utf-8')


if __name__ == '__main__':
    unittest.main()
