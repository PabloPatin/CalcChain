from types import SimpleNamespace
import json
import tempfile
import unittest
from pathlib import Path

from calcchain_core.io.auth import AuthService
from calcchain_core.api import CalculationCore
from calcchain_core.common.errors import SourceError
from calcchain_core.models import SourceRef
from calcchain_plugin_system import AuthCredentials, AuthField, AuthRequirement
from calcchain_plugin_system import PluginRuntimeSet
from calcchain_plugin_system.registrars import CapabilityKey, CapabilityRecord
from calcchain_core.io.sources import LocalSourceAdapter, SourceRegistry
from plugins.svn.calcchain_svn_plugin.plugin import SvnSourceAdapter as BundledSvnSourceAdapter


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


class StaticAuthService:
    def __init__(self):
        self.calls = []

    def get_credentials(self, requirement):
        self.calls.append(requirement)
        return AuthCredentials({'username': 'user', 'password': 'plain-secret-value'})


def _svn_source_registry(adapter, *, auth=None) -> SourceRegistry:
    runtime = PluginRuntimeSet(
        active_owner_ids=('calcchain.svn',),
        environment=object(),
        capabilities={
            CapabilityKey('source', 'svn'): CapabilityRecord(
                key=CapabilityKey('source', 'svn'),
                capability=adapter,
                owner='calcchain.svn',
            ),
        },
    )
    return SourceRegistry.from_runtime(runtime, auth=auth)


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
            self.assertEqual(adapter.resolve_lock_ref(source), source)
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
        registry = _svn_source_registry(
            BundledSvnSourceAdapter(client_factory=lambda location, **kwargs: fake),
            auth=StaticAuthService(),
        )
        source = SourceRef.from_dict(
            {
                'type': 'svn',
                'location': 'https://svn.example.org/repo',
                'path': 'trunk/data',
                'revision': 'HEAD',
            },
        )

        resolved = registry.resolve_lock_ref(source)

        self.assertEqual(resolved.revision, 1842)
        self.assertEqual(resolved.plugin.id, 'calcchain.svn')
        self.assertTrue(registry.is_versionable(resolved))
        self.assertEqual(registry.list_files(resolved), ['case/bc.dat', 'case/nested/input.txt'])
        self.assertEqual(registry.read_file(resolved, 'case/bc.dat'), b'boundary')
        self.assertIn(('cat', 'trunk/data/case/bc.dat', 1842, True), fake.calls)

    def test_svn_source_lock_ref_preserves_safe_auth_metadata_for_post_lock_operations(self):
        fake = FakeSvnClient()
        auth = StaticAuthService()
        registry = _svn_source_registry(
            BundledSvnSourceAdapter(client_factory=lambda location, **kwargs: fake),
            auth=auth,
        )
        source = SourceRef.from_dict(
            {
                'type': 'svn',
                'location': 'https://svn.example.org/repo',
                'path': 'trunk/data',
                'revision': 'HEAD',
                'auth': {'scheme': 'username_password', 'persistence': 'allowed', 'optional': True},
            },
        )

        resolved = registry.resolve_lock_ref(source)
        serialized = resolved.to_dict()
        files = registry.list_files(resolved)
        data = registry.read_file(resolved, 'case/bc.dat')

        self.assertEqual(serialized['revision'], 1842)
        self.assertEqual(
            serialized['auth'],
            {'scheme': 'username_password', 'persistence': 'allowed', 'optional': True},
        )
        self.assertNotIn('plain-secret-value', json.dumps(serialized, sort_keys=True))
        self.assertNotIn('abc123', json.dumps(serialized, sort_keys=True))
        self.assertNotIn('token', serialized['auth'])
        self.assertEqual(files, ['case/bc.dat', 'case/nested/input.txt'])
        self.assertEqual(data, b'boundary')
        self.assertEqual(len(auth.calls), 3)
        for requirement in auth.calls:
            self.assertEqual(requirement.scheme, 'username_password')
            self.assertEqual(requirement.persistence, 'allowed')
            self.assertTrue(requirement.optional)
            self.assertEqual(requirement.scope, {'source_type': 'svn', 'location': 'https://svn.example.org/repo'})

    def test_svn_source_auth_config_rejects_secret_like_fields_before_client(self):
        calls = []

        def factory(location):
            calls.append(location)
            return FakeSvnClient()

        registry = _svn_source_registry(BundledSvnSourceAdapter(client_factory=factory))
        source = SourceRef.from_dict(
            {
                'type': 'svn',
                'location': 'https://svn.example.org/repo',
                'path': 'trunk/data',
                'revision': 'HEAD',
                'auth': {'scheme': 'username_password', 'password': 'plain-secret-value', 'token': 'abc123'},
            },
        )

        with self.assertRaises(SourceError) as caught:
            registry.resolve_lock_ref(source)

        self.assertIn('unsupported fields', str(caught.exception))
        self.assertNotIn('plain-secret-value', str(caught.exception))
        self.assertNotIn('abc123', str(caught.exception))
        self.assertEqual(calls, [])

    def test_svn_source_rejects_unsafe_ref_before_client(self):
        calls = []

        def factory(location):
            calls.append(location)
            return FakeSvnClient()

        registry = _svn_source_registry(BundledSvnSourceAdapter(client_factory=factory))
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
                    registry.resolve_lock_ref(SourceRef.from_dict(source_data))
                self.assertNotIn('secret', str(caught.exception))

        self.assertEqual(calls, [])

    def test_svn_adapter_sanitizes_credentials_in_client_errors(self):
        registry = _svn_source_registry(BundledSvnSourceAdapter(client_factory=lambda location: FailingSvnClient()))
        source = SourceRef.from_dict(
            {
                'type': 'svn',
                'location': 'https://svn.example.org/repo',
                'path': 'trunk/data',
                'revision': 'HEAD',
            },
        )

        with self.assertRaises(SourceError) as caught:
            registry.resolve_lock_ref(source)

        message = str(caught.exception)
        self.assertIn('https://[redacted]@svn.example.org/repo', message)
        self.assertNotIn('user:secret', message)
        self.assertNotIn('secret', message)

    def test_source_registry_dispatches_custom_adapter(self):
        class Adapter(LocalSourceAdapter):
            def list_files(self, source):
                return ['one.txt']

        source = SourceRef.from_dict({'type': 'demo', 'path': 'D:/unused'})
        registry = SourceRegistry({'demo': Adapter()})

        self.assertEqual(registry.list_files(source), ['one.txt'])

    def test_source_registry_default_keeps_local_only(self):
        registry = SourceRegistry()
        source = SourceRef.from_dict(
            {
                'type': 'svn',
                'location': 'https://svn.example.org/repo',
                'path': 'trunk/data',
                'revision': 'HEAD',
            },
        )

        with self.assertRaises(SourceError):
            registry.resolve_lock_ref(source)

    def test_source_registry_from_runtime_dispatches_plugin_capability_with_context(self):
        class PluginSourceAdapter:
            def __init__(self):
                self.calls = []

            def validate_config(self, ref, context):
                self.calls.append(('validate_config', ref, context))

            def resolve_lock_ref(self, ref, context):
                self.calls.append(('resolve_lock_ref', ref, context))
                return {'type': 'demo', 'path': ref['path'], 'revision': 42}

            def validate_lock_ref(self, ref, context):
                self.calls.append(('validate_lock_ref', ref, context))

            def list_files(self, ref, context):
                self.calls.append(('list_files', ref, context))
                return ['result.txt']

            def read_file(self, ref, relative_path, context):
                self.calls.append(('read_file', ref, relative_path, context))
                return b'plugin-data'

            def is_versionable(self, ref, context):
                self.calls.append(('is_versionable', ref, context))
                return True

        adapter = PluginSourceAdapter()
        runtime = PluginRuntimeSet(
            active_owner_ids=('plugin.demo',),
            environment=object(),
            capabilities={
                CapabilityKey('source', 'demo'): CapabilityRecord(
                    key=CapabilityKey('source', 'demo'),
                    capability=adapter,
                    owner='plugin.demo',
                ),
            },
        )
        auth = object()
        registry = SourceRegistry.from_runtime(runtime, auth=auth)
        source = SourceRef.from_dict({'type': 'demo', 'path': 'dataset'})

        resolved = registry.resolve_lock_ref(source)

        self.assertEqual(resolved.revision, 42)
        self.assertEqual(registry.list_files(resolved), ['result.txt'])
        self.assertEqual(registry.read_file(resolved, 'result.txt'), b'plugin-data')
        self.assertTrue(registry.is_versionable(resolved))
        self.assertEqual(registry._entries['demo'].plugin_id, 'plugin.demo')
        self.assertIsNone(registry._entries['demo'].plugin_version)
        self.assertEqual(
            [call[0] for call in adapter.calls],
            [
                'resolve_lock_ref',
                'validate_lock_ref',
                'list_files',
                'validate_lock_ref',
                'read_file',
                'validate_lock_ref',
                'is_versionable',
            ],
        )
        for call in adapter.calls:
            context = call[-1]
            self.assertEqual(context.owner_id, 'plugin.demo')
            self.assertEqual(context.capability_id, 'demo')
            self.assertIs(context.auth, auth)

    def test_source_registry_from_runtime_does_not_override_builtin_local(self):
        adapter = object()
        runtime = PluginRuntimeSet(
            active_owner_ids=('plugin.demo',),
            environment=object(),
            capabilities={
                CapabilityKey('source', 'local'): CapabilityRecord(
                    key=CapabilityKey('source', 'local'),
                    capability=adapter,
                    owner='plugin.demo',
                ),
            },
        )

        with self.assertRaises(SourceError) as caught:
            SourceRegistry.from_runtime(runtime)

        self.assertIn("source type 'local' is already registered", str(caught.exception))

    def test_source_runtime_context_auth_service_provides_credentials(self):
        class AuthProvider:
            def can_handle(self, requirement, context):
                return requirement.scheme == 'token'

            def validate_requirement(self, requirement, context):
                pass

            def get_credentials(self, requirement, context):
                return AuthCredentials({'token': 'source-token'})

        class PluginSourceAdapter:
            def validate_config(self, ref, context):
                pass

            def resolve_lock_ref(self, ref, context):
                return {'type': 'secure-source', 'path': ref['path'], 'revision': 1}

            def validate_lock_ref(self, ref, context):
                pass

            def list_files(self, ref, context):
                credentials = context.auth.get_credentials(
                    AuthRequirement(
                        scheme='token',
                        scope={'use': 'source'},
                        fields=(AuthField('token', True),),
                    ),
                )
                return [credentials.values['token']]

            def read_file(self, ref, relative_path, context):
                return b''

            def is_versionable(self, ref, context):
                return True

        runtime = PluginRuntimeSet(
            active_owner_ids=('plugin.secure',),
            environment=object(),
            capabilities={
                CapabilityKey('source', 'secure-source'): CapabilityRecord(
                    key=CapabilityKey('source', 'secure-source'),
                    capability=PluginSourceAdapter(),
                    owner='plugin.secure',
                ),
                CapabilityKey('auth', 'token'): CapabilityRecord(
                    key=CapabilityKey('auth', 'token'),
                    capability=AuthProvider(),
                    owner='plugin.secure',
                ),
            },
        )
        auth_service = AuthService.from_runtime(runtime)
        registry = SourceRegistry.from_runtime(runtime, auth=auth_service)
        source = SourceRef.from_dict({'type': 'secure-source', 'path': 'repo'})

        resolved = registry.resolve_lock_ref(source)

        self.assertEqual(registry.list_files(resolved), ['source-token'])

    def test_calculation_core_does_not_auto_enable_auth_provider_from_runtime(self):
        class AuthProvider:
            def __init__(self):
                self.calls = []

            def can_handle(self, requirement, context):
                self.calls.append(('can_handle', requirement.scheme))
                return True

            def validate_requirement(self, requirement, context):
                self.calls.append(('validate_requirement', requirement.scheme))

            def get_credentials(self, requirement, context):
                self.calls.append(('get_credentials', requirement.scheme))
                return AuthCredentials({'token': 'auto-enabled-token'})

        class PluginSourceAdapter:
            def validate_config(self, ref, context):
                pass

            def resolve_lock_ref(self, ref, context):
                return {'type': 'secure-source', 'path': ref['path'], 'revision': 1}

            def validate_lock_ref(self, ref, context):
                pass

            def list_files(self, ref, context):
                context.auth.get_credentials(
                    AuthRequirement(
                        scheme='token',
                        scope={'use': 'source'},
                        fields=(AuthField('token', True),),
                    ),
                )
                return ['must-not-return.txt']

            def read_file(self, ref, relative_path, context):
                return b''

            def is_versionable(self, ref, context):
                return True

        provider = AuthProvider()
        runtime = PluginRuntimeSet(
            active_owner_ids=('plugin.secure',),
            environment=object(),
            capabilities={
                CapabilityKey('source', 'secure-source'): CapabilityRecord(
                    key=CapabilityKey('source', 'secure-source'),
                    capability=PluginSourceAdapter(),
                    owner='plugin.secure',
                ),
                CapabilityKey('auth', 'token'): CapabilityRecord(
                    key=CapabilityKey('auth', 'token'),
                    capability=provider,
                    owner='plugin.secure',
                ),
            },
        )

        with tempfile.TemporaryDirectory() as tmp:
            core = CalculationCore(Path(tmp), plugin_runtime=runtime)
            resolved = core.source_registry.resolve_lock_ref(
                SourceRef.from_dict({'type': 'secure-source', 'path': 'repo'}),
            )

            with self.assertRaises(SourceError) as caught:
                core.source_registry.list_files(resolved)

        self.assertIn('auth service is not configured', str(caught.exception))
        self.assertEqual(provider.calls, [])


if __name__ == '__main__':
    unittest.main()
