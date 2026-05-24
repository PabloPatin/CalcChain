import tempfile
import unittest
from pathlib import Path

import calcchain_core
from calcchain_core import CalculationCore
from calcchain_core.capabilities import RuntimeCapabilities
from calcchain_core.io import SourceRef, SourceRegistry, TargetRef, TargetRegistry
from calcchain_core.secrets import MemorySecretStore, SecretPersistencePolicy


class TestCoreCurrentPublicApi(unittest.TestCase):
    def test_public_core_exports_facade_and_default_registries(self):
        with tempfile.TemporaryDirectory() as tmp:
            core = CalculationCore(
                Path(tmp) / 'job',
                runtime=RuntimeCapabilities(),
                secret_policy=SecretPersistencePolicy(allow_memory=True, allow_store=False),
                secret_store=MemorySecretStore(),
            )

            self.assertIs(calcchain_core.CalculationCore, CalculationCore)
            self.assertIsInstance(core.source_registry, SourceRegistry)
            self.assertIsInstance(core.target_registry, TargetRegistry)
            self.assertEqual(core.layout.job_dir, Path(tmp) / 'job')

    def test_builtin_local_source_and_target_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_root = root / 'source'
            target_root = root / 'target'
            source_root.mkdir()
            (source_root / 'file.txt').write_text('data', encoding='utf-8')
            source = SourceRef({'type': 'local', 'path': str(source_root)})
            target = TargetRef({'type': 'local', 'path': str(target_root)})

            source_registry = SourceRegistry()
            target_registry = TargetRegistry()
            published = target_registry.write_file(
                target,
                'copied/file.txt',
                source_registry.read_file(source, 'file.txt'),
            )

            self.assertEqual(source_registry.list_files(source), ['file.txt'])
            self.assertEqual((target_root / 'copied' / 'file.txt').read_text(encoding='utf-8'), 'data')
            self.assertEqual(published.source.data['type'], 'local')


if __name__ == '__main__':
    unittest.main()
