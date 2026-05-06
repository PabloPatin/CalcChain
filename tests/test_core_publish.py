from __future__ import annotations

from dataclasses import dataclass
import json
import tempfile
import unittest
from pathlib import Path

from calcchain_core.config import read_publish
from calcchain_core.errors import ConfigFormatError, PublishError
from calcchain_core.hash import sha256_file
from calcchain_core.models import Manifest, PublishConfig, RuleSetType, RulesFile, SourceType, TargetRef
from calcchain_core.publish import build_publish_plan, create_publish_lock, execute_publish_plan
from calcchain_core.targets import LocalTargetAdapter, PublishedRef, TargetRegistry


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


def artifact(path: Path) -> dict:
    return {'sha256': sha256_file(path), 'sources': [{'type': 'local', 'path': str(path)}]}


def target_to_source(target: TargetRef, relative_path: str):
    from calcchain_core.artifacts import published_source

    return published_source(target, relative_path)


if __name__ == '__main__':
    unittest.main()
