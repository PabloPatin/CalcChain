import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from calcchain_core.build_plan import BuildPlan, BuildPlanEntry
from calcchain_core.builder import EnvironmentBuilder
from calcchain_core.layout import JobLayout
from calcchain_core.models import (
    BuildInfo,
    BuildLock,
    CodeConfig,
    InputConfig,
    LockMetadata,
    RuleUse,
    RulesReference,
    SourceRef,
)
from calcchain_core.sources import SourceRegistry


class MemoryAdapter:
    def __init__(self, trees):
        self.trees = trees

    def list_files(self, source):
        return sorted(self.trees[source.path])

    def read_file(self, source, relative_path):
        return self.trees[source.path][relative_path]

    def resolve_revision(self, source):
        return source

    def is_versionable(self, source):
        return source.type.value == 'svn'


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _plan(rules_path):
    code_source = SourceRef.from_dict({'type': 'local', 'path': 'code'})
    input_source = SourceRef.from_dict({'type': 'local', 'path': 'input'})
    rules_source = SourceRef.from_dict({'type': 'local', 'path': str(rules_path)})
    lock = BuildLock(
        schema_version='1.0',
        lock=LockMetadata('2026-05-03T00:00:00+00:00', 'build.toml', '1' * 64, 'build_toml_sha256'),
        build=BuildInfo(name='case'),
        code=CodeConfig(source=code_source, name='solver', rule_set='code_all'),
        inputs=[InputConfig(source=input_source, name='mesh', rule_set='input_all')],
        rules=RulesReference(source=rules_source, resolved={'schema_version': '1.0', 'sha256': '2' * 64}),
    )
    return BuildPlan(
        lock=lock,
        entries=[
            BuildPlanEntry(
                'code',
                'solver',
                code_source,
                'solver.py',
                'solver.py',
                _sha(b'print("ok")\n'),
                RuleUse(set='code_all', status='stable'),
            ),
            BuildPlanEntry(
                'input',
                'mesh',
                input_source,
                'mesh.dat',
                'input/mesh.dat',
                _sha(b'mesh'),
                RuleUse(set='input_all', status='stable'),
            ),
        ],
        warnings=[],
    )


class TestCoreBuilder(unittest.TestCase):
    def test_build_creates_work_dir_maps_snapshots_rules_and_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rules_path = root / 'rules.json'
            rules_path.write_text('{"rule_sets": {}}\n', encoding='utf-8')
            layout = JobLayout.from_job_dir(root / 'job')
            registry = SourceRegistry(
                {
                    'local': MemoryAdapter(
                        {
                            'code': {'solver.py': b'print("ok")\n'},
                            'input': {'mesh.dat': b'mesh'},
                        },
                    ),
                },
            )

            result = EnvironmentBuilder(registry, rules_file_path=rules_path).build(layout, _plan(rules_path))

            self.assertEqual((layout.work_dir / 'solver.py').read_text(encoding='utf-8'), 'print("ok")\n')
            self.assertEqual((layout.work_dir / 'input' / 'mesh.dat').read_bytes(), b'mesh')
            self.assertEqual((layout.rules_dir / 'rules.json').read_text(encoding='utf-8'), '{"rule_sets": {}}\n')
            self.assertTrue((layout.snapshots_dir / 'build_snapshot.json').is_file())
            self.assertFalse((layout.snapshots_dir / 'pre_run_snapshot.json').exists())
            self.assertTrue((layout.build_artifacts_dir / 'build_lock.json').is_file())
            self.assertEqual(json.loads((layout.service_dir / 'runtime_status.json').read_text())['job_status'], 'Built')
            self.assertEqual(result.code_set.name, 'solver')
            self.assertEqual(result.input_sets[0].name, 'mesh')
            self.assertEqual(result.rules_artifact.path, '.calcchain/rules/rules.json')
            self.assertEqual(len(result.build_snapshot.entries), 2)
            self.assertIsNone(result.pre_run_snapshot)

    def test_pre_run_check_records_code_rules_and_lock_blockers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rules_path = root / 'rules.json'
            rules_path.write_text('{"rule_sets": {}}\n', encoding='utf-8')
            layout = JobLayout.from_job_dir(root / 'job')
            registry = SourceRegistry(
                {
                    'local': MemoryAdapter(
                        {
                            'code': {'solver.py': b'print("ok")\n'},
                            'input': {'mesh.dat': b'mesh'},
                        },
                    ),
                },
            )
            builder = EnvironmentBuilder(registry, rules_file_path=rules_path)
            plan = _plan(rules_path)
            build_result = builder.build(layout, plan)
            (layout.work_dir / 'solver.py').write_text('print("changed")\n', encoding='utf-8')
            (layout.rules_dir / 'rules.json').write_text('{"changed": true}\n', encoding='utf-8')
            (layout.build_artifacts_dir / 'build_lock.json').write_text('{"changed": true}\n', encoding='utf-8')

            check_result = builder.check_pre_run(layout, build_result, plan)
            status = json.loads((layout.service_dir / 'runtime_status.json').read_text(encoding='utf-8'))

            self.assertTrue((layout.snapshots_dir / 'pre_run_snapshot.json').is_file())
            self.assertEqual(len(check_result.blockers), 3)
            self.assertEqual(status['blockers'], check_result.blockers)
            self.assertTrue(any('code file changed before run: solver.py' == item for item in check_result.blockers))
            self.assertTrue(any('rules artifact changed before run' in item for item in check_result.blockers))
            self.assertTrue(any('build lock artifact changed before run' in item for item in check_result.blockers))

    def test_pre_run_check_freezes_changed_input_without_blocker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            layout = JobLayout.from_job_dir(root / 'job')
            registry = SourceRegistry({'local': MemoryAdapter({'code': {'solver.py': b'code'}, 'input': {'mesh.dat': b'mesh'}})})
            code_source = SourceRef.from_dict({'type': 'local', 'path': 'code'})
            input_source = SourceRef.from_dict({'type': 'svn', 'location': 'https://svn.example.org/data', 'path': 'input', 'revision': 1})
            registry = SourceRegistry(
                {
                    'local': MemoryAdapter({'code': {'solver.py': b'code'}}),
                    'svn': MemoryAdapter({'input': {'mesh.dat': b'mesh'}}),
                },
            )
            lock = BuildLock(
                schema_version='1.0',
                lock=LockMetadata('2026-05-03T00:00:00+00:00', 'build.toml', '1' * 64, 'build_toml_sha256'),
                build=BuildInfo(name='case'),
                code=CodeConfig(source=code_source, name='solver'),
                inputs=[InputConfig(source=input_source, name='mesh')],
            )
            plan = BuildPlan(
                lock=lock,
                entries=[
                    BuildPlanEntry('code', 'solver', code_source, 'solver.py', 'solver.py', _sha(b'code')),
                    BuildPlanEntry('input', 'mesh', input_source, 'mesh.dat', 'input/mesh.dat', _sha(b'mesh')),
                ],
                warnings=[],
            )
            builder = EnvironmentBuilder(registry)
            build_result = builder.build(layout, plan)
            (layout.work_dir / 'input' / 'mesh.dat').write_bytes(b'changed mesh')

            check_result = builder.check_pre_run(layout, build_result, plan)

            self.assertEqual(check_result.blockers, [])
            self.assertIsNotNone(check_result.frozen_inputs)
            self.assertEqual((layout.frozen_inputs_dir / 'input' / 'mesh.dat').read_bytes(), b'changed mesh')

    def test_dry_run_returns_preview_without_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rules_path = root / 'rules.json'
            rules_path.write_text('{}', encoding='utf-8')
            layout = JobLayout.from_job_dir(root / 'job')
            registry = SourceRegistry({'local': MemoryAdapter({'code': {}, 'input': {}})})

            result = EnvironmentBuilder(registry, rules_file_path=rules_path).build(
                layout,
                _plan(rules_path),
                dry_run=True,
            )

            self.assertTrue(result.dry_run)
            self.assertFalse(layout.job_dir.exists())
            self.assertIn('copy files: 2', result.preview)
            self.assertEqual(result.build_snapshot.entries, [])

    def test_pre_run_dry_run_returns_preview_without_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rules_path = root / 'rules.json'
            rules_path.write_text('{}', encoding='utf-8')
            layout = JobLayout.from_job_dir(root / 'job')
            registry = SourceRegistry({'local': MemoryAdapter({'code': {'solver.py': b'print("ok")\n'}, 'input': {'mesh.dat': b'mesh'}})})
            builder = EnvironmentBuilder(registry, rules_file_path=rules_path)
            plan = _plan(rules_path)
            build_result = builder.build(layout, plan)

            check_result = builder.check_pre_run(layout, build_result, plan, dry_run=True)

            self.assertTrue(check_result.dry_run)
            self.assertFalse((layout.snapshots_dir / 'pre_run_snapshot.json').exists())
            self.assertFalse((layout.frozen_inputs_dir / 'frozen_inputs.json').exists())
            self.assertIn(f'write runtime status: {layout.service_dir / "runtime_status.json"}', check_result.preview)


if __name__ == '__main__':
    unittest.main()
