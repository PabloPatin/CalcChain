from __future__ import annotations

from dataclasses import dataclass, replace
import json
import tempfile
import unittest
from pathlib import Path

from calcchain_core.auth import AuthService
from calcchain_core.api import CalculationCore
from calcchain_core.config import read_publish, write_manifest
from calcchain_core.errors import ConfigFormatError, PublishError
from calcchain_core.hash import sha256_file
from calcchain_core.models import Manifest, PublishConfig, RuleSetType, RulesFile, SourceType, TargetRef
from calcchain_core.plugin_runtime import AuthCredentials, AuthField, AuthRequirement
from calcchain_core.plugin_runtime import PublishedRef as RuntimePublishedRef
from calcchain_core.plugins.manager import PluginRuntimeSet
from calcchain_core.plugins.registrars import CapabilityKey, CapabilityRecord
from calcchain_core.publish import build_publish_plan, create_publish_lock, execute_publish_plan
from calcchain_core.restore import RestoreRequest, restore_from_manifest
from calcchain_core.sources import SourceRegistry
from calcchain_core.targets import LocalTargetAdapter, PublishedRef, TargetRegistry
from plugins.svn.calcchain_svn_plugin.plugin import SvnTargetAdapter as BundledSvnTargetAdapter


class RecordingTargetAdapter:
    def __init__(self, revision: int = 2910):
        self.revision = revision
        self.writes: list[tuple[str, bytes]] = []
        self.ensured: list[TargetRef] = []

    def write_file(self, target: TargetRef, relative_path: str, data: bytes) -> PublishedRef:
        self.writes.append((relative_path, data))
        return PublishedRef(target=target, relative_path=relative_path, source=target_to_source(target, relative_path))

    def ensure_root(self, target: TargetRef) -> TargetRef:
        self.ensured.append(target)
        return target

    def resolve_revision(self, target: TargetRef) -> TargetRef:
        if target.type is SourceType.SVN:
            return TargetRef(type=target.type, location=target.location, path=target.path, revision=self.revision)
        return target


class FailingManifestAdapter(RecordingTargetAdapter):
    def write_file(self, target: TargetRef, relative_path: str, data: bytes) -> PublishedRef:
        if relative_path == 'manifest.json':
            raise PublishError('manifest write failed')
        return super().write_file(target, relative_path, data)


class FakeSvnTargetClient:
    def __init__(self):
        self.calls = []

    def info(self, path, *, revision=None):
        self.calls.append(('info', path, revision))
        return type('Info', (), {'commit_revision': 77})()

    def mkdir(self, path, *, message='', parents=False, exist_ok=False):
        self.calls.append(('mkdir', path, message, parents, exist_ok))

    def import_(self, from_path, to_path, message='', *, force=False):
        self.calls.append(('import', Path(from_path).read_bytes(), to_path, message, force))


class StaticAuthService:
    def __init__(self):
        self.calls = []

    def get_credentials(self, requirement):
        self.calls.append(requirement)
        return AuthCredentials({'username': 'user', 'password': 'plain-secret-value'})


class TestCorePublish(unittest.TestCase):
    def test_create_publish_lock_resolves_svn_head_and_keeps_local_shape(self):
        config = PublishConfig.from_dict(
            {
                'publish': {'message': 'publish'},
                'service_target': {
                    'type': 'svn',
                    'location': 'https://svn.example.org/results',
                    'path': 'case/_calcchain',
                    'revision': 'HEAD',
                },
                'targets': [
                    {
                        'name': 'outputs',
                        'type': 'svn',
                        'location': 'https://svn.example.org/results',
                        'path': 'case/results',
                        'revision': 'HEAD',
                        'rule_sets': ['standard_outputs'],
                    },
                    {'name': 'logs', 'type': 'local', 'path': 'D:/published/logs', 'rule_sets': ['standard_logs']},
                ],
            },
        )
        registry = TargetRegistry(
            {
                SourceType.SVN: RecordingTargetAdapter(revision=77),
                SourceType.LOCAL: RecordingTargetAdapter(),
            },
        )

        lock = create_publish_lock(config, registry)
        serialized = lock.to_dict()

        self.assertEqual(lock.service_target.revision, 77)
        self.assertEqual(lock.targets[0].target.revision, 77)
        self.assertNotEqual(lock.service_target.revision, 'HEAD')
        self.assertEqual(serialized['targets'][1], {'name': 'logs', 'type': 'local', 'path': 'D:/published/logs', 'rule_sets': ['standard_logs'], 'message': 'publish'})

    def test_build_plan_uses_target_specific_rule_sets_and_skips_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = manifest_fixture(root)
            lock = local_lock(root)

            plan = build_publish_plan(manifest, lock, rules_fixture())

            self.assertEqual([(group.category, group.target.path) for group in plan.groups], [('outputs', str(root / 'published' / 'outputs')), ('logs', str(root / 'published' / 'logs'))])
            self.assertEqual(plan.groups[0].map[0].work_path, 'results/value.txt')
            self.assertEqual(plan.groups[0].map[0].target_path, 'value.txt')
            self.assertFalse(any('debug.bin' in item.relative_path for group in plan.groups for item in group.files))
            self.assertIn('publish.lock.toml', [item.relative_path for item in plan.service_artifacts])
            self.assertIn('build.lock.toml', [item.relative_path for item in plan.service_artifacts])
            self.assertIn('snapshots/build_snapshot.json', [item.relative_path for item in plan.service_artifacts])

    def test_build_plan_keeps_outputs_on_svn_and_logs_on_local_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = manifest_fixture(root)
            config = PublishConfig.from_dict(
                {
                    'publish': {'message': 'publish'},
                    'service_target': {'type': 'local', 'path': str(root / 'service')},
                    'targets': [
                        {
                            'name': 'outputs',
                            'type': 'svn',
                            'location': 'https://svn.example.org/results',
                            'path': 'case/results',
                            'revision': 'HEAD',
                            'rule_sets': ['standard_outputs'],
                        },
                        {
                            'name': 'logs',
                            'type': 'local',
                            'path': str(root / 'published' / 'logs'),
                            'rule_sets': ['standard_logs'],
                        },
                    ],
                },
            )
            lock = create_publish_lock(
                config,
                TargetRegistry(
                    {
                        SourceType.LOCAL: RecordingTargetAdapter(),
                        SourceType.SVN: RecordingTargetAdapter(revision=444),
                    },
                ),
            )

            plan = build_publish_plan(manifest, lock, rules_fixture())

            self.assertEqual([group.category for group in plan.groups], ['outputs', 'logs'])
            self.assertEqual(plan.groups[0].target.type, SourceType.SVN)
            self.assertEqual(plan.groups[0].target.revision, 444)
            self.assertEqual(plan.groups[0].rules.set, 'standard_outputs')
            self.assertEqual([file.target.type for file in plan.groups[0].files], [SourceType.SVN])
            self.assertEqual(plan.groups[1].target.type, SourceType.LOCAL)
            self.assertEqual(plan.groups[1].target.path, str(root / 'published' / 'logs'))
            self.assertEqual(plan.groups[1].rules.set, 'standard_logs')
            self.assertEqual([file.target.type for file in plan.groups[1].files], [SourceType.LOCAL])

    def test_execute_publish_plan_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter = RecordingTargetAdapter()
            plan = build_publish_plan(manifest_fixture(root), local_lock(root), rules_fixture())
            plan.target_registry.register(SourceType.LOCAL, adapter)

            result = execute_publish_plan(plan, dry_run=True)

            self.assertTrue(result.dry_run)
            self.assertEqual(adapter.writes, [])
            self.assertFalse((root / 'service' / 'manifest.json').exists())

    def test_execute_publish_plan_writes_manifest_last_and_updates_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter = RecordingTargetAdapter()
            plan = build_publish_plan(manifest_fixture(root), local_lock(root), rules_fixture())
            plan.target_registry.register(SourceType.LOCAL, adapter)

            result = execute_publish_plan(plan)

            self.assertEqual(adapter.writes[-1][0], 'manifest.json')
            publication = result.updated_manifest.to_dict()['publication']
            self.assertEqual(publication['outputs'][0]['target']['path'], str(root / 'published' / 'outputs'))
            self.assertEqual(publication['logs'][0]['rules']['set'], 'standard_logs')
            self.assertEqual(result.updated_manifest.to_dict()['job']['status'], 'Published')

    def test_manifest_write_failure_reports_incomplete_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter = FailingManifestAdapter()
            plan = build_publish_plan(manifest_fixture(root), local_lock(root), rules_fixture())
            plan.target_registry.register(SourceType.LOCAL, adapter)

            with self.assertRaises(PublishError):
                execute_publish_plan(plan)

            self.assertNotEqual(adapter.writes[-1][0], 'manifest.json')
            self.assertIn('publish.lock.toml', [path for path, _ in adapter.writes])

    def test_service_only_publication_is_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lock = local_lock(root, targets=[])
            plan = build_publish_plan(manifest_fixture(root), lock, rules_fixture())

            self.assertEqual(plan.groups, [])
            self.assertTrue(plan.service_artifacts)

    def test_publish_config_rejects_dry_run_and_requires_service_target(self):
        with self.assertRaises(ConfigFormatError):
            PublishConfig.from_dict(
                {
                    'publish': {'dry_run': True},
                    'service_target': {'type': 'local', 'path': 'D:/service'},
                },
            )
        with self.assertRaises(ConfigFormatError):
            PublishConfig.from_dict({'targets': []})

    def test_local_target_adapter_blocks_relative_path_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = TargetRef(type=SourceType.LOCAL, path=str(Path(tmp) / 'target'))
            adapter = LocalTargetAdapter()

            adapter.ensure_root(target)
            adapter.write_file(target, 'nested/file.txt', b'ok')

            self.assertEqual((Path(tmp) / 'target' / 'nested' / 'file.txt').read_bytes(), b'ok')
            with self.assertRaises(PublishError):
                adapter.write_file(target, '../escape.txt', b'bad')

    def test_target_registry_default_keeps_local_only(self):
        registry = TargetRegistry()
        target = TargetRef.from_dict(
            {
                'type': 'svn',
                'location': 'https://svn.example.org/results',
                'path': 'case/results',
                'revision': 'HEAD',
            },
        )

        with self.assertRaises(PublishError):
            registry.resolve_revision(target)

    def test_bundled_svn_target_plugin_resolves_and_publishes_with_fake_client(self):
        fake = FakeSvnTargetClient()
        registry = _svn_target_registry(
            BundledSvnTargetAdapter(client_factory=lambda location, **kwargs: fake),
            auth=StaticAuthService(),
        )
        target = TargetRef.from_dict(
            {
                'type': 'svn',
                'location': 'https://svn.example.org/results',
                'path': 'case/results',
                'revision': 'HEAD',
            },
        )

        resolved = registry.resolve_revision(target)
        ensured = registry.ensure_root(resolved)
        published = registry.write_file(ensured, 'nested/value.txt', b'value')

        self.assertEqual(resolved.revision, 77)
        self.assertEqual(resolved.plugin.id, 'calcchain.svn')
        self.assertEqual(published.source.location, 'https://svn.example.org/results')
        self.assertEqual(published.source.path, 'case/results/nested/value.txt')
        self.assertEqual(published.source.revision, 77)
        self.assertEqual(published.source.plugin.id, 'calcchain.svn')
        self.assertIn(('mkdir', 'case/results', '', True, True), fake.calls)
        self.assertIn(('import', b'value', 'case/results/nested/value.txt', '', True), fake.calls)

    def test_bundled_svn_target_lock_ref_preserves_safe_auth_metadata_for_post_lock_operations(self):
        fake = FakeSvnTargetClient()
        auth = StaticAuthService()
        registry = _svn_target_registry(
            BundledSvnTargetAdapter(client_factory=lambda location, **kwargs: fake),
            auth=auth,
        )
        target = TargetRef.from_dict(
            {
                'type': 'svn',
                'location': 'https://svn.example.org/results',
                'path': 'case/results',
                'revision': 'HEAD',
                'auth': {'scheme': 'username_password', 'persistence': 'allowed', 'optional': True},
            },
        )

        resolved = registry.resolve_lock_ref(target)
        serialized = resolved.to_dict()
        ensured = registry.ensure_root(resolved)
        registry.write_file(ensured, 'nested/value.txt', b'value')

        self.assertEqual(serialized['revision'], 77)
        self.assertEqual(
            serialized['auth'],
            {'scheme': 'username_password', 'persistence': 'allowed', 'optional': True},
        )
        self.assertNotIn('plain-secret-value', json.dumps(serialized, sort_keys=True))
        self.assertNotIn('abc123', json.dumps(serialized, sort_keys=True))
        self.assertNotIn('token', serialized['auth'])
        self.assertIn(('mkdir', 'case/results', '', True, True), fake.calls)
        self.assertIn(('import', b'value', 'case/results/nested/value.txt', '', True), fake.calls)
        self.assertEqual(len(auth.calls), 3)
        for requirement in auth.calls:
            self.assertEqual(requirement.scheme, 'username_password')
            self.assertEqual(requirement.persistence, 'allowed')
            self.assertTrue(requirement.optional)
            self.assertEqual(requirement.scope, {'target_type': 'svn', 'location': 'https://svn.example.org/results'})

    def test_bundled_svn_target_auth_config_rejects_secret_like_fields_before_client(self):
        calls = []

        def factory(location):
            calls.append(location)
            return FakeSvnTargetClient()

        registry = _svn_target_registry(BundledSvnTargetAdapter(client_factory=factory))
        target = TargetRef.from_dict(
            {
                'type': 'svn',
                'location': 'https://svn.example.org/results',
                'path': 'case/results',
                'revision': 'HEAD',
                'auth': {'scheme': 'username_password', 'password': 'plain-secret-value', 'token': 'abc123'},
            },
        )

        with self.assertRaises(PublishError) as caught:
            registry.resolve_lock_ref(target)

        self.assertIn('unsupported fields', str(caught.exception))
        self.assertNotIn('plain-secret-value', str(caught.exception))
        self.assertNotIn('abc123', str(caught.exception))
        self.assertEqual(calls, [])

    def test_target_registry_from_runtime_dispatches_plugin_capability_with_context(self):
        class PluginTargetAdapter:
            def __init__(self):
                self.calls = []

            def validate_config(self, ref, context):
                self.calls.append(('validate_config', ref, context))

            def resolve_lock_ref(self, ref, context):
                self.calls.append(('resolve_lock_ref', ref, context))
                return {'type': 'artifact-store', 'path': ref['path'], 'revision': 99}

            def validate_lock_ref(self, ref, context):
                self.calls.append(('validate_lock_ref', ref, context))

            def ensure_root(self, ref, context):
                self.calls.append(('ensure_root', ref, context))
                return dict(ref)

            def write_file(self, ref, relative_path, data, context):
                self.calls.append(('write_file', ref, relative_path, data, context))
                return RuntimePublishedRef(ref={'type': 'artifact-store', 'path': f"{ref['path']}/{relative_path}"})

        adapter = PluginTargetAdapter()
        runtime = PluginRuntimeSet(
            active_plugin_ids=('plugin.publisher',),
            environment=object(),
            capabilities={
                CapabilityKey('target', 'artifact-store'): CapabilityRecord(
                    key=CapabilityKey('target', 'artifact-store'),
                    capability=adapter,
                    owner='plugin.publisher',
                ),
            },
        )
        auth = object()
        registry = TargetRegistry.from_runtime(runtime, auth=auth)
        target = TargetRef.from_dict({'type': 'artifact-store', 'path': 'runs/42'})

        resolved = registry.resolve_revision(target)
        registry.ensure_root(resolved)
        published = registry.write_file(resolved, 'manifest.json', b'{}')

        self.assertEqual(resolved.revision, 99)
        self.assertEqual(published.source.path, 'runs/42/manifest.json')
        self.assertEqual(registry._entries['artifact-store'].plugin_id, 'plugin.publisher')
        self.assertIsNone(registry._entries['artifact-store'].plugin_version)
        self.assertEqual(
            [call[0] for call in adapter.calls],
            ['validate_config', 'resolve_lock_ref', 'validate_lock_ref', 'ensure_root', 'validate_lock_ref', 'write_file'],
        )
        for call in adapter.calls:
            context = call[-1]
            self.assertEqual(context.plugin_id, 'plugin.publisher')
            self.assertEqual(context.capability_id, 'artifact-store')
            self.assertIs(context.auth, auth)

    def test_target_registry_from_runtime_does_not_override_builtin_local(self):
        adapter = object()
        runtime = PluginRuntimeSet(
            active_plugin_ids=('plugin.publisher',),
            environment=object(),
            capabilities={
                CapabilityKey('target', 'local'): CapabilityRecord(
                    key=CapabilityKey('target', 'local'),
                    capability=adapter,
                    owner='plugin.publisher',
                ),
            },
        )

        registry = TargetRegistry.from_runtime(runtime)

        self.assertIsNone(registry._entries['local'].plugin_id)
        self.assertIsNone(registry._entries['local'].plugin_version)
        self.assertIsInstance(registry.adapter_for(TargetRef.from_dict({'type': 'local', 'path': 'D:/unused'})), LocalTargetAdapter)

    def test_plugin_target_lifecycle_adds_lock_metadata_and_uses_published_refs(self):
        class PluginTargetAdapter:
            plugin_version = '2.3.4'

            def __init__(self):
                self.calls = []

            def validate_config(self, ref, context):
                self.calls.append(('validate_config', ref['type'], context.operation))

            def resolve_lock_ref(self, ref, context):
                self.calls.append(('resolve_lock_ref', ref['type'], context.operation))
                return {'type': 'artifact-store', 'path': ref['path'], 'revision': 5, 'bucket': ref['bucket']}

            def validate_lock_ref(self, ref, context):
                self.calls.append(('validate_lock_ref', ref['revision'], context.operation))

            def ensure_root(self, ref, context):
                self.calls.append(('ensure_root', ref['path'], context.operation))
                return dict(ref)

            def write_file(self, ref, relative_path, data, context):
                self.calls.append(('write_file', relative_path, context.operation))
                return RuntimePublishedRef(
                    ref={
                        'type': 'artifact-source',
                        'path': f"{ref['path']}/{relative_path}",
                        'revision': ref['revision'],
                        'plugin': {'id': 'plugin.publisher', 'version': '2.3.4'},
                    },
                )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter = PluginTargetAdapter()
            registry = TargetRegistry.from_runtime(
                PluginRuntimeSet(
                    active_plugin_ids=('plugin.publisher',),
                    environment=object(),
                    capabilities={
                        CapabilityKey('target', 'artifact-store'): CapabilityRecord(
                            key=CapabilityKey('target', 'artifact-store'),
                            capability=adapter,
                            owner='plugin.publisher',
                        ),
                    },
                ),
            )
            config = PublishConfig.from_dict(
                {
                    'publish': {'message': 'publish'},
                    'service_target': {'type': 'artifact-store', 'path': 'service', 'bucket': 'b1'},
                    'targets': [
                        {
                            'name': 'published',
                            'type': 'artifact-store',
                            'path': 'outputs',
                            'bucket': 'b1',
                            'rule_sets': ['standard_outputs', 'standard_logs', 'standard_temp'],
                        },
                    ],
                },
            )

            lock = create_publish_lock(config, registry)
            manifest_data = manifest_fixture(root).to_dict()
            manifest_data['run']['file_groups']['temp'] = ['tmp/debug.bin']
            manifest_data['run']['file_groups']['unknown'] = []
            plan = build_publish_plan(Manifest.from_dict(manifest_data), lock, rules_fixture())
            result = execute_publish_plan(replace(plan, target_registry=registry))

            self.assertEqual(lock.service_target.plugin.id, 'plugin.publisher')
            self.assertEqual(lock.service_target.plugin.version, '2.3.4')
            self.assertEqual(lock.service_target.extra['bucket'], 'b1')
            self.assertEqual(
                [call[0] for call in adapter.calls[:6]],
                [
                    'validate_config',
                    'resolve_lock_ref',
                    'validate_lock_ref',
                    'validate_config',
                    'resolve_lock_ref',
                    'validate_lock_ref',
                ],
            )
            publication = result.updated_manifest.to_dict()['publication']
            self.assertEqual(publication['lock']['sources'][0]['type'], 'artifact-source')
            self.assertEqual(publication['lock']['sources'][0]['plugin']['id'], 'plugin.publisher')
            self.assertEqual(publication['outputs'][0]['target']['plugin']['version'], '2.3.4')
            self.assertEqual(publication['outputs'][0]['published_sources']['value.txt']['type'], 'artifact-source')
            self.assertEqual(publication['outputs'][0]['published_sources']['value.txt']['path'], 'outputs/value.txt')
            self.assertEqual(publication['outputs'][0]['published_sources']['value.txt']['plugin']['id'], 'plugin.publisher')
            self.assertEqual(publication['logs'][0]['published_sources']['solver.log']['type'], 'artifact-source')
            self.assertEqual(publication['logs'][0]['published_sources']['solver.log']['path'], 'outputs/solver.log')
            self.assertEqual(publication['temp'][0]['published_sources']['debug.bin']['type'], 'artifact-source')
            self.assertEqual(publication['temp'][0]['published_sources']['debug.bin']['path'], 'outputs/debug.bin')

            class PublishedSourceAdapter:
                data = {
                    'outputs/value.txt': b'value',
                    'outputs/solver.log': b'log',
                    'outputs/debug.bin': b'debug',
                }

                def list_files(self, source):
                    return [Path(source.path).name]

                def read_file(self, source, relative_path):
                    return self.data[source.path]

                def resolve_revision(self, source):
                    return source

                def is_versionable(self, source):
                    return True

            manifest_path = root / 'published_manifest.json'
            restored = root / 'restored'
            manifest_data = result.updated_manifest.to_dict()
            manifest_data['build']['inputs'] = []
            write_manifest(Manifest.from_dict(manifest_data), manifest_path)
            restore_result = restore_from_manifest(
                RestoreRequest(manifest_path, restored),
                SourceRegistry({'artifact-source': PublishedSourceAdapter()}),
            )

            self.assertEqual(restore_result.status, 'restored')
            self.assertEqual((restored / 'work' / 'results' / 'value.txt').read_bytes(), b'value')
            self.assertEqual((restored / 'work' / 'logs' / 'solver.log').read_bytes(), b'log')
            self.assertEqual((restored / 'work' / 'tmp' / 'debug.bin').read_bytes(), b'debug')

    def test_plugin_target_lifecycle_exception_is_wrapped_and_redacted(self):
        class FailingPluginTargetAdapter:
            def validate_config(self, ref, context):
                raise RuntimeError(f'boom secret=abc ref={ref}')

            def resolve_lock_ref(self, ref, context):
                return dict(ref)

            def validate_lock_ref(self, ref, context):
                pass

            def ensure_root(self, ref, context):
                return dict(ref)

            def write_file(self, ref, relative_path, data, context):
                return RuntimePublishedRef(ref={'type': 'artifact-source', 'path': relative_path})

        registry = TargetRegistry.from_runtime(
            PluginRuntimeSet(
                active_plugin_ids=('plugin.publisher',),
                environment=object(),
                capabilities={
                    CapabilityKey('target', 'artifact-store'): CapabilityRecord(
                        key=CapabilityKey('target', 'artifact-store'),
                        capability=FailingPluginTargetAdapter(),
                        owner='plugin.publisher',
                    ),
                },
            ),
        )
        config = PublishConfig.from_dict(
            {'service_target': {'type': 'artifact-store', 'path': 'service', 'token': 'abc123'}},
        )

        with self.assertRaises(PublishError) as caught:
            create_publish_lock(config, registry)

        message = str(caught.exception)
        self.assertIn('plugin target validate_config failed', message)
        self.assertIn('secret=[redacted]', message)
        self.assertNotIn('abc', message)
        self.assertIn("'token': '[redacted]'", message)
        self.assertNotIn('abc123', message)

    def test_plugin_target_runtime_errors_redact_secret_like_extra_fields_on_adapter_paths(self):
        class FailingPluginTargetAdapter:
            def __init__(self, failing_operation):
                self.failing_operation = failing_operation

            def validate_config(self, ref, context):
                if self.failing_operation == 'validate_config':
                    raise RuntimeError(f'bad ref {ref}')

            def resolve_lock_ref(self, ref, context):
                return {**ref, 'revision': 5}

            def validate_lock_ref(self, ref, context):
                pass

            def ensure_root(self, ref, context):
                if self.failing_operation == 'ensure_root':
                    raise RuntimeError(f'bad ref {ref}')
                return dict(ref)

            def write_file(self, ref, relative_path, data, context):
                if self.failing_operation == 'write_file':
                    raise RuntimeError(f'bad ref {ref}')
                return RuntimePublishedRef(ref={'type': 'artifact-source', 'path': relative_path})

        target_data = {
            'type': 'artifact-store',
            'path': 'service',
            'token': 'abc123',
            'password': 'pw456',
            'api-key': 'key789',
            'bucket': 'public-bucket',
        }

        for operation in ('validate_config', 'ensure_root', 'write_file'):
            with self.subTest(operation=operation):
                registry = TargetRegistry.from_runtime(
                    PluginRuntimeSet(
                        active_plugin_ids=('plugin.publisher',),
                        environment=object(),
                        capabilities={
                            CapabilityKey('target', 'artifact-store'): CapabilityRecord(
                                key=CapabilityKey('target', 'artifact-store'),
                                capability=FailingPluginTargetAdapter(operation),
                                owner='plugin.publisher',
                            ),
                        },
                    ),
                )
                target = TargetRef.from_dict({**target_data, 'revision': 5}, resolved_revision=True)

                with self.assertRaises(PublishError) as caught:
                    if operation == 'validate_config':
                        create_publish_lock(
                            PublishConfig.from_dict({'service_target': target_data}),
                            registry,
                        )
                    elif operation == 'ensure_root':
                        registry.ensure_root(target)
                    else:
                        registry.write_file(target, 'manifest.json', b'{}')

                message = str(caught.exception)
                self.assertIn(f'plugin target {operation} failed', message)
                self.assertIn('public-bucket', message)
                self.assertNotIn('abc123', message)
                self.assertNotIn('pw456', message)
                self.assertNotIn('key789', message)
                self.assertIn("'token': '[redacted]'", message)
                self.assertIn("'password': '[redacted]'", message)
                self.assertIn("'api-key': '[redacted]'", message)

    def test_target_runtime_context_auth_service_provides_credentials(self):
        class AuthProvider:
            def can_handle(self, requirement, context):
                return requirement.scheme == 'token'

            def validate_requirement(self, requirement, context):
                pass

            def get_credentials(self, requirement, context):
                return AuthCredentials({'token': 'target-token'})

        class PluginTargetAdapter:
            def validate_config(self, ref, context):
                pass

            def resolve_lock_ref(self, ref, context):
                return {'type': 'secure-target', 'path': ref['path'], 'revision': 1}

            def validate_lock_ref(self, ref, context):
                pass

            def ensure_root(self, ref, context):
                return dict(ref)

            def write_file(self, ref, relative_path, data, context):
                credentials = context.auth.get_credentials(
                    AuthRequirement(
                        scheme='token',
                        scope={'use': 'target'},
                        fields=(AuthField('token', True),),
                    ),
                )
                return RuntimePublishedRef(
                    ref={
                        'type': 'secure-source',
                        'path': f"{credentials.values['token']}/{relative_path}",
                    },
                )

        runtime = PluginRuntimeSet(
            active_plugin_ids=('plugin.secure',),
            environment=object(),
            capabilities={
                CapabilityKey('target', 'secure-target'): CapabilityRecord(
                    key=CapabilityKey('target', 'secure-target'),
                    capability=PluginTargetAdapter(),
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
        registry = TargetRegistry.from_runtime(runtime, auth=auth_service)
        target = TargetRef.from_dict({'type': 'secure-target', 'path': 'service'})

        resolved = registry.resolve_revision(target)
        published = registry.write_file(resolved, 'manifest.json', b'{}')

        self.assertEqual(published.source.path, 'target-token/manifest.json')

    def test_calculation_core_passes_explicit_auth_service_to_target_context(self):
        class AuthProvider:
            def can_handle(self, requirement, context):
                return requirement.scheme == 'token'

            def validate_requirement(self, requirement, context):
                pass

            def get_credentials(self, requirement, context):
                return AuthCredentials({'token': 'explicit-target-token'})

        class PluginTargetAdapter:
            def validate_config(self, ref, context):
                pass

            def resolve_lock_ref(self, ref, context):
                return {'type': 'secure-target', 'path': ref['path'], 'revision': 1}

            def validate_lock_ref(self, ref, context):
                pass

            def ensure_root(self, ref, context):
                return dict(ref)

            def write_file(self, ref, relative_path, data, context):
                credentials = context.auth.get_credentials(
                    AuthRequirement(
                        scheme='token',
                        scope={'use': 'target'},
                        fields=(AuthField('token', True),),
                    ),
                )
                return RuntimePublishedRef(
                    ref={
                        'type': 'secure-source',
                        'path': f"{credentials.values['token']}/{relative_path}",
                    },
                )

        runtime = PluginRuntimeSet(
            active_plugin_ids=('plugin.secure',),
            environment=object(),
            capabilities={
                CapabilityKey('target', 'secure-target'): CapabilityRecord(
                    key=CapabilityKey('target', 'secure-target'),
                    capability=PluginTargetAdapter(),
                    owner='plugin.secure',
                ),
                CapabilityKey('auth', 'token'): CapabilityRecord(
                    key=CapabilityKey('auth', 'token'),
                    capability=AuthProvider(),
                    owner='plugin.secure',
                ),
            },
        )

        with tempfile.TemporaryDirectory() as tmp:
            core = CalculationCore(
                Path(tmp),
                plugin_runtime=runtime,
                auth_service=AuthService.from_runtime(runtime),
            )
            resolved = core.target_registry.resolve_revision(
                TargetRef.from_dict({'type': 'secure-target', 'path': 'service'}),
            )
            published = core.target_registry.write_file(resolved, 'manifest.json', b'{}')

        self.assertEqual(published.source.path, 'explicit-target-token/manifest.json')

    def test_calculation_core_does_not_auto_enable_auth_provider_for_target_context(self):
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
                return AuthCredentials({'token': 'auto-enabled-target-token'})

        class PluginTargetAdapter:
            def validate_config(self, ref, context):
                pass

            def resolve_lock_ref(self, ref, context):
                return {'type': 'secure-target', 'path': ref['path'], 'revision': 1}

            def validate_lock_ref(self, ref, context):
                pass

            def ensure_root(self, ref, context):
                return dict(ref)

            def write_file(self, ref, relative_path, data, context):
                context.auth.get_credentials(
                    AuthRequirement(
                        scheme='token',
                        scope={'use': 'target'},
                        fields=(AuthField('token', True),),
                    ),
                )
                return RuntimePublishedRef(ref={'type': 'secure-source', 'path': relative_path})

        provider = AuthProvider()
        runtime = PluginRuntimeSet(
            active_plugin_ids=('plugin.secure',),
            environment=object(),
            capabilities={
                CapabilityKey('target', 'secure-target'): CapabilityRecord(
                    key=CapabilityKey('target', 'secure-target'),
                    capability=PluginTargetAdapter(),
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
            resolved = core.target_registry.resolve_revision(
                TargetRef.from_dict({'type': 'secure-target', 'path': 'service'}),
            )

            with self.assertRaises(PublishError) as caught:
                core.target_registry.write_file(resolved, 'manifest.json', b'{}')

        self.assertIn('auth service is not configured', str(caught.exception))
        self.assertEqual(provider.calls, [])


def manifest_fixture(root: Path) -> Manifest:
    job_dir = root / 'job'
    work = job_dir / 'work'
    service = job_dir / '.calcchain'
    (work / 'results').mkdir(parents=True)
    (work / 'logs').mkdir(parents=True)
    (work / 'tmp').mkdir(parents=True)
    (service / 'build').mkdir(parents=True)
    (service / 'snapshots').mkdir(parents=True)
    (service / 'frozen_inputs' / 'input').mkdir(parents=True)
    (service / 'logs').mkdir(parents=True)
    (work / 'results' / 'value.txt').write_text('value', encoding='utf-8')
    (work / 'logs' / 'solver.log').write_text('log', encoding='utf-8')
    (work / 'tmp' / 'debug.bin').write_bytes(b'debug')
    build_lock = service / 'build' / 'build_lock.json'
    snapshot = service / 'snapshots' / 'build_snapshot.json'
    frozen = service / 'frozen_inputs' / 'input' / 'mesh.dat'
    stdout = service / 'logs' / 'stdout.txt'
    build_lock.write_text('{}\n', encoding='utf-8')
    snapshot.write_text('{}\n', encoding='utf-8')
    frozen.write_text('mesh', encoding='utf-8')
    stdout.write_text('stdout', encoding='utf-8')
    return Manifest.from_dict(
        {
            'schema_version': '1.0',
            'job': {'id': 'run-1', 'status': 'Succeeded', 'job_dir': str(job_dir)},
            'build': {
                'lock': artifact(build_lock),
                'inputs': [
                    {
                        'name': 'frozen_inputs',
                        'tree_sha256': 'a' * 64,
                        'sources': [{'type': 'local', 'path': str(service / 'frozen_inputs')}],
                        'map': [],
                    },
                ],
            },
            'run': {
                'status': 'Succeeded',
                'file_groups': {
                    'outputs': ['results/value.txt'],
                    'logs': ['logs/solver.log'],
                    'temp': [],
                    'ignored': [],
                    'unknown': ['tmp/debug.bin'],
                },
                'stdout': {'log': artifact(stdout)},
            },
            'snapshots': {'build': artifact(snapshot)},
        },
    )


def rules_fixture() -> RulesFile:
    return RulesFile.from_dict(
        {
            'rule_sets': {
                'standard_outputs': {
                    'type': RuleSetType.OUTPUT.value,
                    'status': 'stable',
                    'ensure_all_files': True,
                    'rules': [{'source': 'results/(.*)', 'destination': '<capt:1>'}],
                },
                'standard_logs': {
                    'type': RuleSetType.LOGS.value,
                    'status': 'stable',
                    'ensure_all_files': True,
                    'rules': [{'source': 'logs/(.*)', 'destination': '<capt:1>'}],
                },
                'standard_temp': {
                    'type': RuleSetType.TEMP.value,
                    'status': 'transient',
                    'ensure_all_files': True,
                    'rules': [{'source': 'tmp/(.*)', 'destination': '<capt:1>'}],
                },
            },
        },
    )


def local_lock(root: Path, *, targets=None):
    config = PublishConfig.from_dict(
        {
            'publish': {'message': 'publish'},
            'service_target': {'type': 'local', 'path': str(root / 'service')},
            'targets': targets
            if targets is not None
            else [
                {'name': 'results', 'type': 'local', 'path': str(root / 'published' / 'outputs'), 'rule_sets': ['standard_outputs']},
                {'name': 'logs', 'type': 'local', 'path': str(root / 'published' / 'logs'), 'rule_sets': ['standard_logs']},
            ],
        },
    )
    return create_publish_lock(config, TargetRegistry({SourceType.LOCAL: RecordingTargetAdapter()}))


def _svn_target_registry(adapter, *, auth=None) -> TargetRegistry:
    runtime = PluginRuntimeSet(
        active_plugin_ids=('calcchain.svn',),
        environment=object(),
        capabilities={
            CapabilityKey('target', 'svn'): CapabilityRecord(
                key=CapabilityKey('target', 'svn'),
                capability=adapter,
                owner='calcchain.svn',
            ),
        },
    )
    return TargetRegistry.from_runtime(runtime, auth=auth)


def artifact(path: Path) -> dict:
    return {'sha256': sha256_file(path), 'sources': [{'type': 'local', 'path': str(path)}]}


def target_to_source(target: TargetRef, relative_path: str):
    from calcchain_core.artifacts import published_source

    return published_source(target, relative_path)


if __name__ == '__main__':
    unittest.main()
