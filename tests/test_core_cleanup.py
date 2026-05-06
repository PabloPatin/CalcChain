from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from calcchain_core.cleanup import cleanup_work_dir
from calcchain_core.errors import CleanupError
from calcchain_core.layout import JobLayout


class TestCoreCleanup(unittest.TestCase):
    def test_cleanup_removes_work_contents_and_preserves_service_area(self):
        with tempfile.TemporaryDirectory() as tmp:
            layout = JobLayout.from_job_dir(Path(tmp) / 'job')
            (layout.work_dir / 'nested').mkdir(parents=True)
            (layout.work_dir / 'nested' / 'value.txt').write_text('value', encoding='utf-8')
            layout.service_dir.mkdir(parents=True)
            (layout.service_dir / 'manifest.json').write_text('{}\n', encoding='utf-8')

            result = cleanup_work_dir(layout)

            self.assertEqual(result.status, 'cleaned')
            self.assertEqual(result.removed_paths, ['nested'])
            self.assertTrue(layout.work_dir.is_dir())
            self.assertEqual(list(layout.work_dir.iterdir()), [])
            self.assertTrue((layout.service_dir / 'manifest.json').is_file())

    def test_cleanup_dry_run_does_not_delete_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            layout = JobLayout.from_job_dir(Path(tmp) / 'job')
            layout.work_dir.mkdir(parents=True)
            (layout.work_dir / 'value.txt').write_text('value', encoding='utf-8')

            result = cleanup_work_dir(layout, dry_run=True)

            self.assertEqual(result.status, 'planned')
            self.assertEqual(result.removed_paths, ['value.txt'])
            self.assertTrue((layout.work_dir / 'value.txt').is_file())

    def test_cleanup_rejects_service_dir_as_work_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            layout = JobLayout.from_job_dir(Path(tmp) / 'job')
            bad_layout = JobLayout(
                job_dir=layout.job_dir,
                work_dir=layout.service_dir,
                service_dir=layout.service_dir,
                rules_dir=layout.rules_dir,
                logs_dir=layout.logs_dir,
                frozen_inputs_dir=layout.frozen_inputs_dir,
                snapshots_dir=layout.snapshots_dir,
                build_artifacts_dir=layout.build_artifacts_dir,
                publication_artifacts_dir=layout.publication_artifacts_dir,
                manifest_path=layout.manifest_path,
            )

            with self.assertRaises(CleanupError):
                cleanup_work_dir(bad_layout)


if __name__ == '__main__':
    unittest.main()
