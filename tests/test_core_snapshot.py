import tempfile
import unittest
from pathlib import Path

from calcchain_core.workspace.snapshot import create_snapshot, diff_snapshots


class TestCoreSnapshot(unittest.TestCase):
    def test_create_snapshot_hashes_relative_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'nested').mkdir()
            (root / 'nested' / 'a.txt').write_text('alpha', encoding='utf-8')
            (root / 'b.txt').write_bytes(b'beta')

            snapshot = create_snapshot(root)

            self.assertEqual([entry.path for entry in snapshot.entries], ['b.txt', 'nested/a.txt'])
            self.assertTrue(all(entry.kind == 'file' for entry in snapshot.entries))
            self.assertTrue(all(len(entry.sha256) == 64 for entry in snapshot.entries))
            self.assertEqual(snapshot.schema_version, '1.0')

    def test_diff_snapshots_reports_added_modified_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'same.txt').write_text('same', encoding='utf-8')
            (root / 'changed.txt').write_text('old', encoding='utf-8')
            (root / 'deleted.txt').write_text('delete', encoding='utf-8')
            before = create_snapshot(root)

            (root / 'changed.txt').write_text('new', encoding='utf-8')
            (root / 'deleted.txt').unlink()
            (root / 'added.txt').write_text('add', encoding='utf-8')
            after = create_snapshot(root)

            diff = diff_snapshots(before, after)

            self.assertEqual([entry.path for entry in diff.added], ['added.txt'])
            self.assertEqual([entry.path for entry in diff.modified], ['changed.txt'])
            self.assertEqual([entry.path for entry in diff.deleted], ['deleted.txt'])
            self.assertEqual([entry.path for entry in diff.unchanged], ['same.txt'])


if __name__ == '__main__':
    unittest.main()
