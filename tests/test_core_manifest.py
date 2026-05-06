from __future__ import annotations

from dataclasses import dataclass
import json
import tempfile
import unittest
from pathlib import Path

from calcchain_core.artifacts import artifact_ref, published_source
from calcchain_core.builder import BuildResult, RulesArtifact
from calcchain_core.errors import ConfigFormatError
from calcchain_core.layout import JobLayout
from calcchain_core.manifest import ManifestWriter, write_manifest
from calcchain_core.maps import FileSetMap
from calcchain_core.models import FileMapEntry, Manifest, RuleUse, SourceRef, SourceType, TargetRef
from calcchain_core.output_classifier import FileGroups
from calcchain_core.runner import RunResult
from calcchain_core.snapshot import Snapshot
from calcchain_core.hash import tree_sha256
from calcchain_core.models import RunStatus


@dataclass(frozen=True)
class PublishResult:
    service_target: TargetRef
    lock: Path
    outputs: list[dict]
    logs: list[dict]
    temp: list[dict]


class TestCoreManifest(unittest.TestCase):
    def test_built_only_manifest_embeds_maps_rules_and_snapshot_refs(self):
        with tempfile.TemporaryDirectory() as tmp:
            layout, build_result = _build_fixture(Path(tmp))
            build_snapshot_path = layout.snapshots_dir / 'build_snapshot.json'
            build_snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            build_snapshot_path.write_text('{}\n', encoding='utf-8')

            manifest = ManifestWriter().create_after_build(
                _job(layout),
                build_result,
                {'build': build_snapshot_path},
            )

            data = manifest.to_dict()
            self.assertEqual(data['job']['status'], 'Built')
            self.assertNotIn('run', data)
            self.assertNotIn('publication', data)
            self.assertEqual(data['build']['code']['rules'], {'set': 'code_all', 'status': 'stable'})
            self.assertEqual(data['build']['inputs'][0]['map'][0]['work_path'], 'input/mesh.dat')
            self.assertIn('lock', data['build'])
            self.assertIn('rules', data)
            self.assertIn('build', data['snapshots'])
            self.assertIsInstance(Manifest.from_dict(json.loads(json.dumps(data))), Manifest)

    def test_run_manifest_uses_secret_names_and_local_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            layout, build_result = _build_fixture(Path(tmp), rules=False)
            stdin_log = layout.logs_dir / 'stdin.txt'
            stdout_log = layout.logs_dir / 'stdout.txt'
            stderr_log = layout.logs_dir / 'stderr.txt'
            for path, text in ((stdin_log, 'input'), (stdout_log, 'secret masked'), (stderr_log, 'warn')):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding='utf-8')

            run_result = RunResult(
                command=['solver.exe'],
                cwd='.',
                timeout_seconds=10,
                encoding='utf-8',
                env={'VISIBLE': '1'},
                secret_names=['TOKEN'],
                stdin={'mode': 'script', 'log': '.calcchain/logs/stdin.txt'},
                stdout_log='.calcchain/logs/stdout.txt',
                stderr_log='.calcchain/logs/stderr.txt',
                status=RunStatus.FAILED,
                return_code=2,
                started_at='2026-05-04T00:00:00+00:00',
                finished_at='2026-05-04T00:00:01+00:00',
                post_run_snapshot=Snapshot('1.0', '', []),
            )

            manifest = ManifestWriter().create_after_run(
                _job(layout),
                build_result,
                run_result,
                FileGroups(outputs=['result.txt'], unknown=['debug.bin']),
                {},
            )

            data = manifest.to_dict()
            serialized = json.dumps(data, ensure_ascii=False)
            self.assertEqual(data['job']['status'], 'Failed')
            self.assertEqual(data['run']['env'], {'VISIBLE': '1', 'secrets': ['TOKEN']})
            self.assertNotIn('secret-value', serialized)
            self.assertEqual(data['run']['file_groups']['unknown'], ['debug.bin'])
            self.assertEqual(data['run']['stdin']['log']['sources'][0]['type'], 'local')
            self.assertEqual(data['run']['stdout']['log']['sources'][0]['type'], 'local')
            self.assertNotIn('rules', data)

    def test_published_manifest_adds_publication_and_published_log_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            layout, build_result = _build_fixture(Path(tmp), rules=False)
            stdout_log = layout.logs_dir / 'stdout.txt'
            stdout_log.parent.mkdir(parents=True, exist_ok=True)
            stdout_log.write_text('out', encoding='utf-8')
            run_result = RunResult(
                command=['solver.exe'],
                cwd='.',
                timeout_seconds=None,
                encoding='utf-8',
                env={},
                secret_names=[],
                stdin={'mode': 'none'},
                stdout_log='.calcchain/logs/stdout.txt',
                stderr_log=None,
                status=RunStatus.SUCCEEDED,
                return_code=0,
                started_at='2026-05-04T00:00:00+00:00',
                finished_at='2026-05-04T00:00:01+00:00',
                post_run_snapshot=Snapshot('1.0', '', []),
            )
            existing = ManifestWriter().create_after_run(_job(layout), build_result, run_result, FileGroups(), {})
            publish_lock = layout.publication_artifacts_dir / 'publish.lock.toml'
            publish_lock.parent.mkdir(parents=True, exist_ok=True)
            publish_lock.write_text('lock', encoding='utf-8')
            target = TargetRef(type=SourceType.SVN, location='https://svn.example.org/results', path='case-1', revision=42)
            publish_result = PublishResult(
                service_target=target,
                lock=publish_lock,
                outputs=[_publication_set('primary', target)],
                logs=[],
                temp=[],
            )

            manifest = ManifestWriter().create_after_publish(existing, publish_result)

            data = manifest.to_dict()
            self.assertEqual(data['job']['status'], 'Published')
            self.assertEqual(data['publication']['outputs'][0]['target']['revision'], 42)
            self.assertEqual(len(data['run']['stdout']['log']['sources']), 2)
            self.assertEqual(data['run']['stdout']['log']['sources'][1]['path'], 'case-1/_calcchain/logs/stdout.txt')
            self.assertIsInstance(Manifest.from_dict(data), Manifest)

    def test_artifact_helpers_hash_local_and_reject_svn_userinfo(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = Path(tmp) / 'payload.txt'
            payload.write_text('payload', encoding='utf-8')

            ref = artifact_ref(payload)

            self.assertEqual(ref.sources[0].path, str(payload))
            self.assertEqual(ref.sha256, '239f59ed55e737c77147cf55ad0c1b030b6d7ee748a7426952f9b852d5a935e5')
            target = TargetRef(type=SourceType.SVN, location='https://svn.example.org/repo', path='pub', revision=7)
            self.assertEqual(published_source(target, 'logs/stdout.txt').path, 'pub/logs/stdout.txt')
            with self.assertRaises(Exception):
                published_source(
                    TargetRef(type=SourceType.SVN, location='https://user:secret@svn.example.org/repo', path='pub', revision=7),
                    'logs/stdout.txt',
                )

    def test_manifest_writer_rejects_svn_userinfo_in_embedded_build_maps(self):
        with tempfile.TemporaryDirectory() as tmp:
            layout, build_result = _build_fixture(Path(tmp), rules=False)
            credentialed = SourceRef(
                type=SourceType.SVN,
                location='https://user:secret@svn.example.org/repo',
                path='solver',
                revision=12,
            )
            build_result = BuildResult(
                code_set=FileSetMap(
                    name='solver',
                    tree_sha256=build_result.code_set.tree_sha256,
                    source=credentialed,
                    sources=[],
                    rules=None,
                    map=build_result.code_set.map,
                ),
                input_sets=[
                    FileSetMap(
                        name='mesh',
                        tree_sha256=build_result.input_sets[0].tree_sha256,
                        source=None,
                        sources=[credentialed],
                        rules=None,
                        map=build_result.input_sets[0].map,
                    ),
                ],
                build_snapshot=build_result.build_snapshot,
                rules_artifact=None,
            )

            with self.assertRaises(ConfigFormatError):
                ManifestWriter().create_after_build(_job(layout), build_result, {})

    def test_manifest_parser_rejects_svn_userinfo_in_generic_source_refs(self):
        credentialed_source = {
            'type': 'svn',
            'location': 'https://user:secret@svn.example.org/repo',
            'path': 'solver',
            'revision': 12,
        }
        base = {'schema_version': '1.0', 'job': {'status': 'Built'}}

        with self.assertRaises(ConfigFormatError):
            Manifest.from_dict({'build': {'code': {'source': credentialed_source}}, **base})
        with self.assertRaises(ConfigFormatError):
            Manifest.from_dict(
                {
                    'build': {
                        'inputs': [
                            {
                                'name': 'mesh',
                                'tree_sha256': 'a' * 64,
                                'sources': [credentialed_source],
                                'map': [],
                            },
                        ],
                    },
                    **base,
                }
            )
        with self.assertRaises(ConfigFormatError):
            Manifest.from_dict(
                {
                    'build': {},
                    'rules': {
                        'sha256': 'b' * 64,
                        'sources': [credentialed_source],
                    },
                    **base,
                }
            )

    def test_manifest_parser_and_ref_serialization_reject_svn_userinfo(self):
        credentialed_source = SourceRef(
            type=SourceType.SVN,
            location='https://user:secret@svn.example.org/repo',
            path='solver',
            revision=12,
        )
        credentialed_target = TargetRef(
            type=SourceType.SVN,
            location='https://user:secret@svn.example.org/repo',
            path='published',
            revision=12,
        )
        base = {'schema_version': '1.0', 'job': {'status': 'Published'}, 'build': {}}

        with self.assertRaises(ConfigFormatError):
            credentialed_source.to_dict()
        with self.assertRaises(ConfigFormatError):
            credentialed_target.to_dict()
        with self.assertRaises(ConfigFormatError):
            Manifest.from_dict(
                {
                    'publication': {
                        'outputs': [
                            {
                                'name': 'primary',
                                'tree_sha256': 'c' * 64,
                                'target': {
                                    'type': 'svn',
                                    'location': 'https://user:secret@svn.example.org/repo',
                                    'path': 'published',
                                    'revision': 12,
                                },
                                'map': [],
                            },
                        ],
                    },
                    **base,
                }
            )

    def test_write_manifest_writes_strict_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'manifest.json'
            manifest = Manifest.from_dict({'job': {'status': 'Built'}, 'build': {}})

            write_manifest(manifest, path)

            self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['job']['status'], 'Built')


def _build_fixture(root: Path, *, rules: bool = True) -> tuple[JobLayout, BuildResult]:
    layout = JobLayout.from_job_dir(root / 'job')
    layout.build_artifacts_dir.mkdir(parents=True, exist_ok=True)
    (layout.build_artifacts_dir / 'build_lock.json').write_text('{}\n', encoding='utf-8')
    code_source = SourceRef(type=SourceType.LOCAL, path='D:/solver')
    input_source = SourceRef(type=SourceType.LOCAL, path='D:/input')
    code = FileSetMap(
        name='solver',
        tree_sha256=tree_sha256([('solver.exe', 'a' * 64)]),
        source=code_source,
        sources=[],
        rules=RuleUse(set='code_all', status='stable') if rules else None,
        map=[FileMapEntry(sha256='a' * 64, source_path='solver.exe', work_path='solver.exe')],
    )
    inputs = [
        FileSetMap(
            name='mesh',
            tree_sha256=tree_sha256([('input/mesh.dat', 'b' * 64)]),
            source=input_source,
            sources=[],
            rules=RuleUse(set='input_all', status='experimental') if rules else None,
            map=[FileMapEntry(sha256='b' * 64, source_path='mesh.dat', work_path='input/mesh.dat')],
        ),
    ]
    rules_artifact = None
    if rules:
        rules_path = layout.rules_dir / 'rules.json'
        rules_path.parent.mkdir(parents=True, exist_ok=True)
        rules_path.write_text('{"rule_sets": {}}\n', encoding='utf-8')
        rules_artifact = RulesArtifact(path='.calcchain/rules/rules.json')
    return layout, BuildResult(code_set=code, input_sets=inputs, build_snapshot=Snapshot('1.0', '', []), rules_artifact=rules_artifact)


def _job(layout: JobLayout) -> dict:
    return {
        'id': 'run-1',
        'created_at': '2026-05-04T00:00:00+00:00',
        'job_dir': layout.job_dir,
        'layout': layout,
    }


def _publication_set(name: str, target: TargetRef) -> dict:
    return {
        'name': name,
        'tree_sha256': tree_sha256([('result.txt', 'c' * 64)]),
        'target': target.to_dict(),
        'rules': {'set': 'outputs', 'status': 'stable'},
        'map': [FileMapEntry(sha256='c' * 64, work_path='result.txt', target_path='result.txt').to_dict()],
    }


if __name__ == '__main__':
    unittest.main()
