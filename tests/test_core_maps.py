import unittest

from calcchain_core.build.plan import BuildPlanEntry
from calcchain_core.common.hash import tree_sha256
from calcchain_core.workspace.maps import create_file_set_map
from calcchain_core.models import RuleUse, SourceRef


class TestCoreMaps(unittest.TestCase):
    def test_create_file_set_map_returns_array_and_deterministic_tree_hash(self):
        source = SourceRef.from_dict({'type': 'local', 'path': 'code'})
        entries = [
            BuildPlanEntry(
                role='code',
                source_name='solver',
                source=source,
                source_path='b.py',
                work_path='pkg/b.py',
                sha256='b' * 64,
                rules=RuleUse(set='code_all', status='stable'),
            ),
            BuildPlanEntry(
                role='code',
                source_name='solver',
                source=source,
                source_path='a.py',
                work_path='a.py',
                sha256='a' * 64,
                rules=RuleUse(set='code_all', status='stable'),
            ),
        ]

        file_set = create_file_set_map(list(reversed(entries)))

        self.assertEqual(file_set.name, 'solver')
        self.assertEqual([entry.work_path for entry in file_set.map], ['a.py', 'pkg/b.py'])
        self.assertEqual(
            file_set.tree_sha256,
            tree_sha256([('pkg/b.py', 'b' * 64), ('a.py', 'a' * 64)]),
        )
        self.assertEqual(file_set.to_dict()['map'][0]['source_path'], 'a.py')
        self.assertEqual(file_set.to_dict()['rules']['set'], 'code_all')

    def test_create_file_set_map_rejects_mixed_sets(self):
        source = SourceRef.from_dict({'type': 'local', 'path': 'code'})
        entries = [
            BuildPlanEntry('code', 'solver', source, 'a.py', 'a.py', 'a' * 64),
            BuildPlanEntry('input', 'mesh', source, 'mesh.dat', 'mesh.dat', 'b' * 64),
        ]

        with self.assertRaises(ValueError):
            create_file_set_map(entries)


if __name__ == '__main__':
    unittest.main()
