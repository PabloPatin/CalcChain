import hashlib
import tempfile
import unittest
from pathlib import Path

from calcchain_core.build_plan import BuildPlan, BuildPlanEntry
from calcchain_core.builder import EnvironmentBuilder
from calcchain_core.frozen_inputs import freeze_effective_inputs
from calcchain_core.layout import JobLayout
from calcchain_core.models import (
    BuildInfo,
    BuildLock,
    CodeConfig,
    InputConfig,
    LockMetadata,
    SourceRef,
)
from calcchain_core.snapshot import create_snapshot
from calcchain_core.sources import SourceRegistry


class MemoryAdapter:
    def __init__(self, trees):
        self.trees = trees

    def list_files(self, source):
        return sorted(self.trees[source.path])

    def read_file(self, source, relative_path):
        return self.trees[source.path][relative_path]

    def validate_config(self, source):
        pass

    def resolve_lock_ref(self, source):
        return self.resolve_revision(source)

    def validate_lock_ref(self, source):
        pass

    def resolve_revision(self, source):
        return source

    def is_versionable(self, source):
        return getattr(source.type, 'value', source.type) == 'svn'


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _source_registry(**adapters):
    registry = SourceRegistry()
    for source_type, adapter in adapters.items():
        registry.register(source_type, adapter, override=source_type == 'local')
    return registry


def _plan(input_source):
    code_source = SourceRef.from_dict({'type': 'local', 'path': 'code'})
    lock = BuildLock(
        schema_version='1.0',
        lock=LockMetadata('2026-05-03T00:00:00+00:00', 'build.toml', '1' * 64, 'build_toml_sha256'),
        build=BuildInfo(name='case'),
        code=CodeConfig(source=code_source, name='solver'),
        inputs=[InputConfig(source=input_source, name='mesh')],
    )
    return BuildPlan(
        lock=lock,
        entries=[
            BuildPlanEntry('code', 'solver', code_source, 'solver.py', 'solver.py', _sha(b'code')),
            BuildPlanEntry('input', 'mesh', input_source, 'mesh.dat', 'mesh.dat', _sha(b'mesh')),
        ],
        warnings=[],
    )


class TestCoreFrozenInputs(unittest.TestCase):
    def test_freeze_non_versionable_input_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            layout = JobLayout.from_job_dir(root / 'job')
            input_source = SourceRef.from_dict({'type': 'local', 'path': 'input'})
            registry = _source_registry(local=MemoryAdapter({'code': {'solver.py': b'code'}, 'input': {'mesh.dat': b'mesh'}}))
            build_result = EnvironmentBuilder(registry).build(layout, _plan(input_source))

            frozen = freeze_effective_inputs(layout, build_result, create_snapshot(layout.work_dir))

            self.assertIsNotNone(frozen)
            self.assertEqual(frozen.name, 'frozen_inputs')
            self.assertEqual([entry.source_path for entry in frozen.map], ['mesh.dat'])
            self.assertEqual((layout.frozen_inputs_dir / 'mesh.dat').read_bytes(), b'mesh')
            self.assertTrue((layout.frozen_inputs_dir / 'frozen_inputs.json').is_file())

    def test_freeze_changed_versionable_input_uses_pre_run_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            layout = JobLayout.from_job_dir(root / 'job')
            input_source = SourceRef.from_dict(
                {
                    'type': 'svn',
                    'location': 'https://svn.example.org/data',
                    'path': 'input',
                    'revision': 1842,
                },
            )
            registry = _source_registry(
                local=MemoryAdapter({'code': {'solver.py': b'code'}}),
                svn=MemoryAdapter({'input': {'mesh.dat': b'mesh'}}),
            )
            build_result = EnvironmentBuilder(registry).build(layout, _plan(input_source))
            (layout.work_dir / 'mesh.dat').write_bytes(b'changed mesh')
            pre_run_snapshot = create_snapshot(layout.work_dir)

            frozen = freeze_effective_inputs(layout, build_result, pre_run_snapshot, registry=registry)

            self.assertIsNotNone(frozen)
            self.assertEqual((layout.frozen_inputs_dir / 'mesh.dat').read_bytes(), b'changed mesh')
            self.assertEqual(frozen.map[0].sha256, _sha(b'changed mesh'))

    def test_versionable_unchanged_input_is_not_frozen_when_not_requested(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            layout = JobLayout.from_job_dir(root / 'job')
            input_source = SourceRef.from_dict(
                {
                    'type': 'svn',
                    'location': 'https://svn.example.org/data',
                    'path': 'input',
                    'revision': 1842,
                },
            )
            registry = _source_registry(
                local=MemoryAdapter({'code': {'solver.py': b'code'}}),
                svn=MemoryAdapter({'input': {'mesh.dat': b'mesh'}}),
            )
            build_result = EnvironmentBuilder(registry).build(layout, _plan(input_source))

            frozen = freeze_effective_inputs(
                layout,
                build_result,
                create_snapshot(layout.work_dir),
                freeze_non_versionable=False,
            )

            self.assertIsNone(frozen)


if __name__ == '__main__':
    unittest.main()
