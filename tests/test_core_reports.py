from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from calcchain_core.api import CalculationCore
from calcchain_core.common.errors import ReportError
from calcchain_plugin_system import ReportDescriptor, ReportRequest, ReportResult
from calcchain_plugin_system import PluginRuntimeSet
from calcchain_plugin_system.registrars import CapabilityKey, CapabilityRecord


class FakeReportAdapter:
    def __init__(self):
        self.contexts = []
        self.requests = []

    def describe(self, context):
        self.contexts.append(context)
        return ReportDescriptor('summary', 'Summary', 'text/plain', '.txt')

    def render(self, request, context):
        self.requests.append(request)
        self.contexts.append(context)
        return ReportResult(
            report_id='summary',
            content=f"{context.manifest['job']['id']}:{request.parameters.get('suffix', '')}",
            content_type='text/plain',
            metadata={'rows': 1},
        )


class MutatingReportAdapter(FakeReportAdapter):
    def render(self, request, context):
        context.manifest['job']['id'] = 'mutated'
        return ReportResult('summary', 'bad', 'text/plain')


class PathChoosingReportAdapter(FakeReportAdapter):
    def render(self, request, context):
        return ReportResult('summary', 'bad', 'text/plain', path=Path('outside.txt'))


class FailingReportAdapter(FakeReportAdapter):
    def render(self, request, context):
        raise RuntimeError('report failed token=abc123')


class TestCoreReports(unittest.TestCase):
    def test_list_and_render_report_from_manifest_without_runtime_services(self):
        adapter = FakeReportAdapter()
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp) / 'job'
            manifest_path = _write_manifest(job)
            core = CalculationCore(job, plugin_runtime=_runtime(adapter))

            descriptors = core.list_reports()
            result = core.render_report(
                ReportRequest('summary', manifest_path=manifest_path, parameters={'suffix': 'ok'}),
            )

        self.assertEqual(descriptors, [ReportDescriptor('summary', 'Summary', 'text/plain', '.txt')])
        self.assertEqual(result.content, 'case-1:ok')
        self.assertEqual(result.metadata, {'rows': 1})
        render_context = adapter.contexts[-1]
        self.assertEqual(render_context.owner_id, 'plugin.reports')
        self.assertEqual(render_context.capability_id, 'summary')
        self.assertFalse(hasattr(render_context, 'sources'))
        self.assertFalse(hasattr(render_context, 'targets'))
        self.assertFalse(hasattr(render_context, 'auth'))

    def test_export_report_writes_only_to_core_controlled_reports_dir(self):
        adapter = FakeReportAdapter()
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp) / 'job'
            _write_manifest(job)
            core = CalculationCore(job, plugin_runtime=_runtime(adapter))

            result = core.export_report(ReportRequest('summary', parameters={'suffix': 'file'}))

            self.assertEqual(result.content, None)
            self.assertEqual(result.path, job / '.calcchain' / 'reports' / 'summary.txt')
            self.assertEqual(result.path.read_text(encoding='utf-8'), 'case-1:file')

            with self.assertRaises(ReportError):
                core.export_report(ReportRequest('summary'), output_dir=Path(tmp) / 'outside')

    def test_render_report_honors_file_output_request_in_controlled_reports_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp) / 'job'
            _write_manifest(job)
            core = CalculationCore(job, plugin_runtime=_runtime(FakeReportAdapter()))

            result = core.render_report(ReportRequest('summary', parameters={'suffix': 'render-file'}, output='file'))

            self.assertEqual(result.content, None)
            self.assertEqual(result.path, job / '.calcchain' / 'reports' / 'summary.txt')
            self.assertEqual(result.path.read_text(encoding='utf-8'), 'case-1:render-file')

    def test_report_manifest_is_read_only_and_manifest_file_is_not_mutated(self):
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp) / 'job'
            manifest_path = _write_manifest(job)
            lock_paths = _write_lock_files(job)
            before = manifest_path.read_text(encoding='utf-8')
            locks_before = {path: path.read_text(encoding='utf-8') for path in lock_paths}
            core = CalculationCore(job, plugin_runtime=_runtime(MutatingReportAdapter()))

            with self.assertRaises(ReportError):
                core.render_report(ReportRequest('summary'))

            self.assertEqual(manifest_path.read_text(encoding='utf-8'), before)
            self.assertEqual({path: path.read_text(encoding='utf-8') for path in lock_paths}, locks_before)

    def test_report_operations_do_not_mutate_manifest_or_lock_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp) / 'job'
            manifest_path = _write_manifest(job)
            lock_paths = _write_lock_files(job)
            tracked_paths = (manifest_path, *lock_paths)
            before = {path: path.read_text(encoding='utf-8') for path in tracked_paths}
            core = CalculationCore(job, plugin_runtime=_runtime(FakeReportAdapter()))

            core.list_reports()
            core.render_report(ReportRequest('summary', parameters={'suffix': 'render'}))
            core.export_report(ReportRequest('summary', parameters={'suffix': 'export'}))

            self.assertEqual({path: path.read_text(encoding='utf-8') for path in tracked_paths}, before)

    def test_report_adapter_must_not_choose_export_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp) / 'job'
            _write_manifest(job)
            core = CalculationCore(job, plugin_runtime=_runtime(PathChoosingReportAdapter()))

            with self.assertRaises(ReportError) as caught:
                core.render_report(ReportRequest('summary'))

        self.assertIn('must not choose export paths', str(caught.exception))

    def test_missing_report_and_adapter_errors_are_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp) / 'job'
            _write_manifest(job)
            core = CalculationCore(job, plugin_runtime=_runtime(FailingReportAdapter()))

            with self.assertRaises(ReportError) as missing:
                core.render_report(ReportRequest('unknown'))
            with self.assertRaises(ReportError) as failed:
                core.render_report(ReportRequest('summary'))

        self.assertIn('unsupported report id: unknown', str(missing.exception))
        self.assertIn('plugin report render failed', str(failed.exception))
        self.assertNotIn('abc123', str(failed.exception))


def _runtime(adapter) -> PluginRuntimeSet:
    return PluginRuntimeSet(
        active_owner_ids=('plugin.reports',),
        environment=object(),
        capabilities={
            CapabilityKey('report', 'summary'): CapabilityRecord(
                key=CapabilityKey('report', 'summary'),
                capability=adapter,
                owner='plugin.reports',
            ),
        },
    )


def _write_manifest(job: Path) -> Path:
    manifest_path = job / '.calcchain' / 'manifest.json'
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                'schema_version': '1.0',
                'job': {'id': 'case-1', 'status': 'Succeeded', 'job_dir': str(job)},
                'build': {'inputs': []},
            },
        ),
        encoding='utf-8',
    )
    return manifest_path


def _write_lock_files(job: Path) -> tuple[Path, Path]:
    build_lock_path = job / 'build.lock.toml'
    publish_lock_path = job / 'publish.lock.toml'
    build_lock_path.parent.mkdir(parents=True, exist_ok=True)
    build_lock_path.write_text('build = "unchanged"\n', encoding='utf-8')
    publish_lock_path.write_text('publish = "unchanged"\n', encoding='utf-8')
    return build_lock_path, publish_lock_path


if __name__ == '__main__':
    unittest.main()
