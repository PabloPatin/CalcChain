import tempfile
import unittest
from pathlib import Path, PurePosixPath

from calcchain_core.cleanup import cleanup_work_dir
from calcchain_core.common.errors import CleanupError, RulesError
from calcchain_core.rules import Rule, RuleSet, RuleSetType, RulesFile, get_rule_set
from calcchain_core.rules.mapping.trans_map import create_file_translation_map
from calcchain_core.workspace.file_map import apply_rule_set, full_tree_map
from calcchain_core.workspace.layout import JobLayout


class TestCoreCurrentRulesCleanup(unittest.TestCase):
    def test_rules_file_roundtrip_and_rule_application(self):
        rules = RulesFile.from_dict(
            {
                'rule_sets': {
                    'code': {
                        'type': 'code',
                        'status': 'approved',
                        'ensure_all_files': True,
                        'rules': [
                            {
                                'source': r'src/(.*)\.py',
                                'destination': r'app/<capt:1>.py',
                            },
                        ],
                    },
                },
            },
        )

        rule_set = get_rule_set(rules, 'code', RuleSetType.CODE)
        entries = apply_rule_set(['src/main.py'], rule_set)

        self.assertEqual(rules, RulesFile.from_dict(rules.to_dict()))
        self.assertEqual(entries[0].source_path, 'src/main.py')
        self.assertEqual(entries[0].work_path, 'app/main.py')

    def test_rules_reject_uncovered_files_when_requested(self):
        rule_set = RuleSet(
            type=RuleSetType.CODE,
            status='',
            description='',
            ensure_all_files=True,
            rules=[Rule(source=r'covered/.*', destination='<>')],
        )

        with self.assertRaises(RulesError):
            apply_rule_set(['covered/a.txt', 'skipped/b.txt'], rule_set)

    def test_translation_rules_match_backslash_paths_with_posix_patterns(self):
        translation_map = create_file_translation_map(
            files=[PurePosixPath('logs\\solver.log')],
            rules=[[r'^logs/solver\.log$', 'solver.log']],
            additional_markers={},
            check_skipped_files=True,
        )

        self.assertEqual(translation_map[PurePosixPath('logs\\solver.log')].as_posix(), 'solver.log')

    def test_full_tree_map_normalizes_and_rejects_unsafe_paths(self):
        entries = full_tree_map(['b.txt', 'dir\\a.txt'])

        self.assertEqual([entry.work_path for entry in entries], ['b.txt', 'dir/a.txt'])
        with self.assertRaises(RulesError):
            full_tree_map(['../escape.txt'])

    def test_cleanup_work_dir_dry_run_and_real_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            layout = JobLayout.from_job_dir(Path(tmp) / 'job')
            (layout.work_dir / 'nested').mkdir(parents=True)
            (layout.work_dir / 'nested' / 'file.txt').write_text('data', encoding='utf-8')
            (layout.work_dir / 'top.txt').write_text('data', encoding='utf-8')

            planned = cleanup_work_dir(layout, dry_run=True)

            self.assertEqual(planned.status, 'planned')
            self.assertEqual(planned.removed_paths, ['nested', 'top.txt'])
            self.assertTrue((layout.work_dir / 'top.txt').exists())

            cleaned = cleanup_work_dir(layout)

            self.assertEqual(cleaned.status, 'cleaned')
            self.assertEqual(list(layout.work_dir.iterdir()), [])

    def test_cleanup_rejects_work_dir_equal_to_service_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            layout = JobLayout.from_job_dir(Path(tmp) / 'job')
            unsafe = JobLayout(
                job_dir=layout.job_dir,
                work_dir=layout.service_dir,
                service_dir=layout.service_dir,
                logs_dir=layout.logs_dir,
                snapshots_dir=layout.snapshots_dir,
                rules_dir=layout.rules_dir,
                build_artifacts_dir=layout.build_artifacts_dir,
                publish_artifacts_dir=layout.publish_artifacts_dir,
                frozen_inputs_dir=layout.frozen_inputs_dir,
                reports_dir=layout.reports_dir,
                manifest_path=layout.manifest_path,
            )

            with self.assertRaises(CleanupError):
                cleanup_work_dir(unsafe)


if __name__ == '__main__':
    unittest.main()
