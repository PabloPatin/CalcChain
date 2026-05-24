import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from calcchain_core.rules.mapping.search_files import get_files_in_dir
from calcchain_core.run.run_preparation import PreRunPreparer
from calcchain_core.utils.toml import read_toml, write_toml
from calcchain_core.workspace.file_map import FileMapEntry
from calcchain_core.workspace.layout import JobLayout
from calcchain_core.workspace.maps import FileSetMap
from calcchain_core.workspace.snapshot import create_snapshot


class TestCoreCurrentUtilsPreparation(unittest.TestCase):
    def test_toml_roundtrip_and_directory_file_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / 'nested' / 'config.toml'
            write_toml({'section': {'name': 'case', 'count': 2}}, config_path)
            (root / 'files' / 'nested').mkdir(parents=True)
            (root / 'files' / 'a.txt').write_text('a', encoding='utf-8')
            (root / 'files' / 'nested' / 'b.dat').write_text('b', encoding='utf-8')

            self.assertEqual(read_toml(config_path), {'section': {'name': 'case', 'count': 2}})
            self.assertEqual(
                sorted(path.as_posix() for path in get_files_in_dir(root / 'files', base_dir=root)),
                ['files/a.txt', 'files/nested/b.dat'],
            )

    def test_pre_run_preparer_dry_run_reports_blockers_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            layout = JobLayout.from_job_dir(Path(tmp) / 'job')
            layout.work_dir.mkdir(parents=True)
            (layout.work_dir / 'solver.py').write_text('print("ok")\n', encoding='utf-8')
            digest = hashlib.sha256((layout.work_dir / 'solver.py').read_bytes()).hexdigest()
            build_snapshot = create_snapshot(layout.work_dir)
            build_result = SimpleNamespace(
                code_set=FileSetMap(
                    name='code',
                    tree_sha256='tree',
                    map=[FileMapEntry(sha256=digest, work_path='solver.py')],
                ),
                input_sets=[],
                build_snapshot=build_snapshot,
                build_lock_sha256=None,
                rules_artifact=None,
                warnings=['warn'],
            )

            result = PreRunPreparer().prepare(layout, build_result, dry_run=True)

            self.assertTrue(result.dry_run)
            self.assertIn('build lock expected hash is missing before run', result.blockers)
            self.assertFalse((layout.snapshots_dir / 'pre_run_snapshot.json').exists())


if __name__ == '__main__':
    unittest.main()
