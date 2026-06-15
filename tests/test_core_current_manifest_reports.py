import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from calcchain_core.capabilities import CapabilityKey, CapabilityOwner, CapabilityRecord, RuntimeCapabilities
from calcchain_core.common.errors import ReportError
from calcchain_core.common.status import RunStatus
from calcchain_core.manifest import BuildManifestArtifacts, JobManifestInfo, ManifestWriter
from calcchain_core.reports import (
    ReportDescriptor,
    ReportRegistry,
    ReportRequest,
    ReportResult,
    export_report_result,
)
from calcchain_core.workspace.file_map import FileMapEntry
from calcchain_core.workspace.maps import FileSetMap
from calcchain_core.workspace.output_classifier import classify_files
from calcchain_core.workspace.snapshot import Snapshot, SnapshotEntry, create_snapshot, diff_snapshots


class FakeReportAdapter:
    def __init__(self):
        self.render_context = None

    def describe(self, context):
        return ReportDescriptor(id='summary', title='Summary', content_type='text/plain', file_extension='txt')

    def render(self, request, context):
        self.render_context = context
        try:
            context.manifest['job']['status'] = 'mutated'
        except TypeError:
            pass
        return ReportResult(report_id=request.report_id, content='ok', content_type='text/plain')


class TestCoreCurrentManifestReports(unittest.TestCase):
    def test_snapshot_diff_and_file_set_map_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'a.txt').write_text('a', encoding='utf-8')
            before = create_snapshot(root)
            (root / 'a.txt').write_text('b', encoding='utf-8')
            (root / 'b.txt').write_text('new', encoding='utf-8')
            after = create_snapshot(root)

            diff = diff_snapshots(before, after)

            self.assertEqual([entry.path for entry in diff.modified], ['a.txt'])
            self.assertEqual([entry.path for entry in diff.added], ['b.txt'])

            file_set = FileSetMap(
                name='code',
                tree_sha256='tree',
                sources=[],
                map=[FileMapEntry(sha256='hash', source_path='a.txt', work_path='a.txt')],
            )
            self.assertEqual(FileSetMap.from_dict(file_set.to_dict()), file_set)

    def test_manifest_writer_after_build_and_run_uses_typed_sources(self):
        code_set = FileSetMap(
            name='code',
            tree_sha256='code-tree',
            map=[FileMapEntry(sha256='h1', source_path='solver.py', work_path='solver.py')],
        )
        input_set = FileSetMap(
            name='mesh',
            tree_sha256='input-tree',
            map=[FileMapEntry(sha256='h2', source_path='mesh.dat', work_path='mesh.dat')],
        )

        class FileGroupsLike:
            def to_dict(self):
                return {'outputs': ['result.txt'], 'logs': [], 'temp': [], 'ignored': [], 'unknown': [], 'deleted': []}

        job = JobManifestInfo(id='job-1', job_dir=Path('job'))
        build_result = SimpleNamespace(code_set=code_set, input_sets=[input_set])
        run_result = SimpleNamespace(status=RunStatus.SUCCEEDED)

        built = ManifestWriter.create_after_build(job, build_result, BuildManifestArtifacts())
        ran = ManifestWriter.create_after_run(job, build_result, run_result, FileGroupsLike())

        self.assertEqual(built.to_dict()['job']['status'], 'Built')
        self.assertEqual(ran.to_dict()['job']['status'], 'Succeeded')
        self.assertEqual(ran.to_dict()['build']['code']['name'], 'code')
        self.assertEqual(ran.to_dict()['run']['file_groups']['outputs'], ['result.txt'])

    def test_manifest_writer_after_run_preserves_run_result_details(self):
        code_set = FileSetMap(
            name='code',
            tree_sha256='code-tree',
            map=[FileMapEntry(sha256='h1', source_path='solver.py', work_path='solver.py')],
        )

        class FileGroupsLike:
            def to_dict(self):
                return {'outputs': ['result.txt'], 'logs': ['logs/solver.log'], 'temp': [], 'ignored': [], 'unknown': [], 'deleted': []}

        class RunResultLike:
            status = RunStatus.SUCCEEDED

            def to_dict(self):
                return {
                    'command': ['python', 'solver.py'],
                    'cwd': '.',
                    'timeout_seconds': 10,
                    'encoding': 'utf-8',
                    'env': {'VISIBLE': '1'},
                    'secret_names': ['TOKEN'],
                    'stdin': {'mode': 'script', 'log': '.calcchain/logs/stdin.txt'},
                    'stdout_log': '.calcchain/logs/stdout.txt',
                    'stderr_log': '.calcchain/logs/stderr.txt',
                    'status': 'raw-status',
                    'return_code': 0,
                    'started_at': '2026-06-13T10:00:00+00:00',
                    'finished_at': '2026-06-13T10:00:01+00:00',
                    'post_run_snapshot': {'schema_version': '1.0', 'entries': []},
                    'warnings': [],
                }

        manifest = ManifestWriter.create_after_run(
            JobManifestInfo(id='job-1', job_dir=Path('job')),
            SimpleNamespace(code_set=code_set, input_sets=[]),
            RunResultLike(),
            FileGroupsLike(),
        ).to_dict()

        run = manifest['run']
        self.assertEqual(run['command'], ['python', 'solver.py'])
        self.assertEqual(run['cwd'], '.')
        self.assertEqual(run['env'], {'VISIBLE': '1'})
        self.assertEqual(run['secret_names'], ['TOKEN'])
        self.assertEqual(run['stdin']['mode'], 'script')
        self.assertEqual(run['stdout_log'], '.calcchain/logs/stdout.txt')
        self.assertEqual(run['stderr_log'], '.calcchain/logs/stderr.txt')
        self.assertEqual(run['return_code'], 0)
        self.assertEqual(run['started_at'], '2026-06-13T10:00:00+00:00')
        self.assertEqual(run['finished_at'], '2026-06-13T10:00:01+00:00')
        self.assertEqual(run['status'], 'Succeeded')
        self.assertEqual(run['file_groups']['outputs'], ['result.txt'])

    def test_output_classifier_defaults_to_outputs_without_output_rules(self):
        build_result = type(
            'BuildResultLike',
            (),
            {
                'code_set': FileSetMap(
                    name='code',
                    tree_sha256='tree',
                    map=[FileMapEntry(sha256='h', work_path='solver.py')],
                ),
                'input_sets': [],
            },
        )()
        pre = Snapshot(schema_version='1.0', created_at='before', entries=[])
        post = Snapshot(
            schema_version='1.0',
            created_at='after',
            entries=[SnapshotEntry(path='results/value.txt', sha256='h', size=1)],
        )

        groups = classify_files(build_result, pre, post, rules=None)

        self.assertEqual(groups.outputs, ['results/value.txt'])
        self.assertEqual(groups.unknown, [])

    def test_report_registry_from_runtime_renders_with_frozen_manifest_and_exports(self):
        adapter = FakeReportAdapter()
        runtime = RuntimeCapabilities(
            capabilities={
                CapabilityKey('report', 'summary'): CapabilityRecord(
                    CapabilityKey('report', 'summary'),
                    adapter,
                    owner=CapabilityOwner('report-owner', version='1.0'),
                ),
            },
        )
        registry = ReportRegistry.from_runtime(runtime)
        manifest = {'job': {'status': 'Succeeded'}, 'build': {'inputs': []}}

        descriptor = registry.describe('summary')
        result = registry.render(ReportRequest('summary'), manifest)

        self.assertEqual(descriptor.title, 'Summary')
        self.assertEqual(result.content, 'ok')
        self.assertEqual(adapter.render_context.owner_id, 'report-owner')
        self.assertEqual(manifest['job']['status'], 'Succeeded')

        with tempfile.TemporaryDirectory() as tmp:
            exported = export_report_result(result, descriptor, Path(tmp))
            self.assertIsNone(exported.content)
            self.assertEqual(exported.path.read_text(encoding='utf-8'), 'ok')

    def test_report_export_rejects_paths_outside_reports_dir(self):
        result = ReportResult(report_id='summary', content='ok', content_type='text/plain')
        descriptor = ReportDescriptor(id='summary', title='Summary')

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ReportError):
                export_report_result(result, descriptor, Path(tmp) / 'reports', output_dir=Path(tmp) / 'outside')


if __name__ == '__main__':
    unittest.main()
