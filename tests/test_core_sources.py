from types import SimpleNamespace
import tempfile
import unittest
from pathlib import Path

from calcchain_core.errors import SourceError
from calcchain_core.models import SourceRef
from calcchain_core.sources import LocalSourceAdapter, SourceRegistry, SvnSourceAdapter


class FakeSvnClient:
    def __init__(self):
        self.calls = []

    def info(self, path, *, revision=None):
        self.calls.append(('info', path, revision))
        return SimpleNamespace(commit_revision=1842)

    def list(self, path, *, recursive=False, revision=None):
        self.calls.append(('list', path, recursive, revision))
        return SimpleNamespace(
            nodes=(
                SimpleNamespace(kind='file', rel_path='case/bc.dat'),
                SimpleNamespace(kind='dir', rel_path='case/tmp'),
                SimpleNamespace(kind='file', rel_path='case/nested/input.txt'),
            ),
        )

    def cat(self, path, *, revision=None, return_binary=False):
        self.calls.append(('cat', path, revision, return_binary))
        return b'boundary'


class FailingSvnClient:
    def info(self, path, *, revision=None):
        raise RuntimeError('cannot access https://user:secret@svn.example.org/repo')


class TestCoreSources(unittest.TestCase):
    def test_local_source_lists_and_reads_relative_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'solver.py').write_text('print("ok")\n', encoding='utf-8')
            (root / 'pkg').mkdir()
            (root / 'pkg' / 'lib.txt').write_bytes(b'library')

            source = SourceRef.from_dict({'type': 'local', 'path': str(root)})
            adapter = LocalSourceAdapter()

            self.assertEqual(adapter.list_files(source), ['pkg/lib.txt', 'solver.py'])
            self.assertEqual(adapter.read_file(source, 'pkg/lib.txt'), b'library')
            self.assertEqual(adapter.resolve_revision(source), source)
            self.assertFalse(adapter.is_versionable(source))

    def test_local_source_rejects_unsafe_relative_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = SourceRef.from_dict({'type': 'local', 'path': tmp})
            adapter = LocalSourceAdapter()

            with self.assertRaises(SourceError):
                adapter.read_file(source, '../outside.txt')
            with self.assertRaises(SourceError):
                adapter.read_file(source, 'C:/outside.txt')

    def test_svn_source_resolves_head_and_reads_with_source_path(self):
        fake = FakeSvnClient()
        adapter = SvnSourceAdapter(client_factory=lambda location: fake)
        source = SourceRef.from_dict(
            {
                'type': 'svn',
                'location': 'https://svn.example.org/repo',
                'path': 'trunk/data',
                'revision': 'HEAD',
            },
        )

        resolved = adapter.resolve_revision(source)

        self.assertEqual(resolved.revision, 1842)
        self.assertTrue(adapter.is_versionable(source))
        self.assertEqual(adapter.list_files(resolved), ['case/bc.dat', 'case/nested/input.txt'])
        self.assertEqual(adapter.read_file(resolved, 'case/bc.dat'), b'boundary')
        self.assertIn(('cat', 'trunk/data/case/bc.dat', 1842, True), fake.calls)

    def test_svn_source_rejects_unsafe_ref_before_client(self):
        calls = []

        def factory(location):
            calls.append(location)
            return FakeSvnClient()

        adapter = SvnSourceAdapter(client_factory=factory)
        unsafe_sources = (
            {
                'type': 'svn',
                'location': 'https://svn.example.org/repo',
                'path': '../private',
                'revision': 'HEAD',
            },
            {
                'type': 'svn',
                'location': 'https://svn.example.org/repo',
                'path': '/private',
                'revision': 'HEAD',
            },
            {
                'type': 'svn',
                'location': 'https://svn.example.org/repo',
                'path': 'C:/private',
                'revision': 'HEAD',
            },
            {
                'type': 'svn',
                'location': 'https://user:secret@svn.example.org/repo',
                'path': 'trunk/data',
                'revision': 'HEAD',
            },
        )

        for source_data in unsafe_sources:
            with self.subTest(source=source_data):
                with self.assertRaises(SourceError) as caught:
                    adapter.resolve_revision(SourceRef.from_dict(source_data))
                self.assertNotIn('secret', str(caught.exception))

        self.assertEqual(calls, [])

    def test_svn_adapter_sanitizes_credentials_in_client_errors(self):
        adapter = SvnSourceAdapter(client_factory=lambda location: FailingSvnClient())
        source = SourceRef.from_dict(
            {
                'type': 'svn',
                'location': 'https://svn.example.org/repo',
                'path': 'trunk/data',
                'revision': 'HEAD',
            },
        )

        with self.assertRaises(SourceError) as caught:
            adapter.resolve_revision(source)

        message = str(caught.exception)
        self.assertIn('https://[redacted]@svn.example.org/repo', message)
        self.assertNotIn('user:secret', message)
        self.assertNotIn('secret', message)

    def test_source_registry_dispatches_custom_adapter(self):
        class Adapter(LocalSourceAdapter):
            def list_files(self, source):
                return ['one.txt']

        source = SourceRef.from_dict({'type': 'local', 'path': 'D:/unused'})
        registry = SourceRegistry({'local': Adapter()})

        self.assertEqual(registry.list_files(source), ['one.txt'])


if __name__ == '__main__':
    unittest.main()
