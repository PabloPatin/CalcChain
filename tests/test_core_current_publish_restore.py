import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from calcchain_core.common.hash import tree_sha256
from calcchain_core.common.status import RunStatus
from calcchain_core.io import SourceRef, SourceRegistry, TargetRegistry
from calcchain_core.manifest import JobManifestInfo, Manifest, ManifestWriter, write_manifest
from calcchain_core.publish import (
    PublishConfig,
    build_publish_plan,
    create_publish_lock,
    execute_publish_plan,
)
from calcchain_core.restore import RestoreRequest, restore_from_manifest
from calcchain_core.rules import Rule, RuleSet, RuleSetType, RulesFile
from calcchain_core.run.frozen_inputs import freeze_effective_inputs
from calcchain_core.workspace.file_map import FileMapEntry
from calcchain_core.workspace.layout import JobLayout
from calcchain_core.workspace.maps import FileSetMap
from calcchain_core.workspace.snapshot import create_snapshot


class FileGroups:
    def __init__(self, outputs=None):
        self.outputs = list(outputs or [])

    def to_dict(self):
        return {
            'outputs': self.outputs,
            'logs': [],
            'temp': [],
            'ignored': [],
            'unknown': [],
            'deleted': [],
        }


class TestCoreCurrentPublishRestore(unittest.TestCase):
    def test_restore_uses_frozen_inputs_overlay_for_prerun_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job = root / 'job'
            layout = JobLayout.from_job_dir(job)
            layout.work_dir.mkdir(parents=True)
            code_source = root / 'code-source'
            input_source = root / 'input-source'
            code_source.mkdir()
            input_source.mkdir()
            (code_source / 'solver.py').write_text('print("ok")\n', encoding='utf-8')
            (input_source / 'mesh.dat').write_text('original\n', encoding='utf-8')
            (layout.work_dir / 'solver.py').write_text('print("ok")\n', encoding='utf-8')
            (layout.work_dir / 'mesh.dat').write_text('original\n', encoding='utf-8')
            build_snapshot = create_snapshot(layout.work_dir)
            (layout.work_dir / 'mesh.dat').write_text('edited-before-run\n', encoding='utf-8')
            pre_run_snapshot = create_snapshot(layout.work_dir)

            build_result = SimpleNamespace(
                code_set=_file_set('code', code_source, 'solver.py', 'solver.py'),
                input_sets=[_file_set('mesh', input_source, 'mesh.dat', 'mesh.dat')],
                build_snapshot=build_snapshot,
            )
            frozen = freeze_effective_inputs(layout, build_result, pre_run_snapshot, registry=SourceRegistry())
            manifest = ManifestWriter.create_after_run(
                JobManifestInfo(id='job', job_dir=job),
                build_result,
                SimpleNamespace(status=RunStatus.SUCCEEDED),
                FileGroups(),
                frozen_inputs=frozen,
            )
            manifest_path = root / 'manifest.json'
            write_manifest(manifest, manifest_path)

            target_job = root / 'restored'
            result = restore_from_manifest(
                RestoreRequest(manifest_path=manifest_path, target_job_dir=target_job),
                SourceRegistry(),
            )

            self.assertEqual(result.status, 'restored')
            self.assertEqual(
                (target_job / 'work' / 'mesh.dat').read_text(encoding='utf-8'),
                'edited-before-run\n',
            )
            self.assertEqual(
                (target_job / 'work' / 'solver.py').read_text(encoding='utf-8'),
                'print("ok")\n',
            )

    def test_publish_lock_plan_and_execute_write_local_targets_and_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job = root / 'job'
            work = job / 'work'
            work.mkdir(parents=True)
            (work / 'out.txt').write_text('result\n', encoding='utf-8')
            manifest = Manifest.from_dict(
                {
                    'job': {'id': 'job', 'status': 'Succeeded', 'job_dir': str(job)},
                    'build': {
                        'code': {'name': 'code', 'tree_sha256': 'empty', 'sources': [], 'map': []},
                        'inputs': [],
                    },
                    'run': {'status': 'Succeeded', 'file_groups': FileGroups(outputs=['out.txt']).to_dict()},
                },
            )
            rules = RulesFile(
                schema_version='1.0',
                rules_file={},
                rule_sets={
                    'outputs': RuleSet(
                        type=RuleSetType.OUTPUT,
                        status='approved',
                        description='',
                        ensure_all_files=True,
                        rules=[Rule(source=r'(.*)', destination=r'published/<capt:1>')],
                    ),
                },
            )
            config = PublishConfig.from_dict(
                {
                    'publish': {'message': 'done'},
                    'service_target': {'type': 'local', 'path': str(root / 'service')},
                    'targets': [
                        {
                            'name': 'public',
                            'type': 'local',
                            'path': str(root / 'published'),
                            'rule_sets': ['outputs'],
                        },
                    ],
                },
            )
            registry = TargetRegistry()

            lock = create_publish_lock(config, registry)
            plan = build_publish_plan(manifest, lock, rules, target_registry=registry)
            result = execute_publish_plan(plan)

            self.assertFalse(result.dry_run)
            self.assertTrue((root / 'service' / 'publish.lock.toml').is_file())
            self.assertTrue((root / 'service' / 'manifest.json').is_file())
            self.assertEqual((root / 'published' / 'published' / 'out.txt').read_text(encoding='utf-8'), 'result\n')
            publication = result.updated_manifest.to_dict()['publication']
            self.assertIn('outputs', publication)
            self.assertEqual(publication['outputs'][0]['published_sources']['published/out.txt']['type'], 'local')


def _file_set(name: str, source_root: Path, source_path: str, work_path: str) -> FileSetMap:
    data = (source_root / source_path).read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    return FileSetMap(
        name=name,
        tree_sha256=tree_sha256([(work_path, digest)]),
        sources=[SourceRef({'type': 'local', 'path': str(source_root)})],
        map=[FileMapEntry(sha256=digest, source_path=source_path, work_path=work_path)],
    )


if __name__ == '__main__':
    unittest.main()
