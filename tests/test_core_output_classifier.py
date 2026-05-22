import tempfile
import unittest
from pathlib import Path

from calcchain_core.build.plan import BuildPlanEntry
from calcchain_core.build.builder import BuildResult
from calcchain_core.workspace.maps import create_file_set_map
from calcchain_core.models import Rule, RuleSet, RuleSetType, RulesFile, SourceRef
from calcchain_core.workspace.output_classifier import classify_files
from calcchain_core.workspace.snapshot import create_snapshot


def _build_result():
    code_source = SourceRef.from_dict({'type': 'local', 'path': 'code'})
    input_source = SourceRef.from_dict({'type': 'local', 'path': 'input'})
    return BuildResult(
        code_set=create_file_set_map(
            [BuildPlanEntry('code', 'solver', code_source, 'solver.py', 'solver.py', 'a' * 64)],
        ),
        input_sets=[
            create_file_set_map(
                [BuildPlanEntry('input', 'mesh', input_source, 'mesh.dat', 'input/mesh.dat', 'b' * 64)],
            ),
        ],
        build_snapshot=create_snapshot(Path('__missing__')),
    )


def _rules():
    return RulesFile(
        schema_version='1.0',
        rules_file={},
        rule_sets={
            'outputs': RuleSet(
                type=RuleSetType.OUTPUT,
                status='stable',
                description='',
                ensure_all_files=False,
                rules=[Rule(source=r'results/.*', destination=r'\g<0>')],
            ),
            'logs': RuleSet(
                type=RuleSetType.LOGS,
                status='stable',
                description='',
                ensure_all_files=False,
                rules=[Rule(source=r'logs/.*', destination=r'\g<0>')],
            ),
            'temp': RuleSet(
                type=RuleSetType.TEMP,
                status='stable',
                description='',
                ensure_all_files=False,
                rules=[Rule(source=r'tmp/.*', destination=r'\g<0>')],
            ),
            'ignore': RuleSet(
                type=RuleSetType.IGNORE,
                status='stable',
                description='',
                ensure_all_files=False,
                rules=[Rule(source=r'cache/.*', destination=r'\g<0>')],
            ),
        },
    )


class TestCoreOutputClassifier(unittest.TestCase):
    def test_without_output_rules_changed_files_become_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            (work / 'solver.py').write_text('code', encoding='utf-8')
            pre = create_snapshot(work)
            (work / 'result.txt').write_text('result', encoding='utf-8')
            post = create_snapshot(work)

            groups = classify_files(_build_result(), pre, post, None)

            self.assertEqual(groups.outputs, ['result.txt'])
            self.assertEqual(groups.unknown, [])
            self.assertEqual(groups.code, ['solver.py'])
            self.assertEqual(groups.inputs, ['input/mesh.dat'])

    def test_typed_rules_classify_outputs_logs_temp_ignore_and_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            (work / 'solver.py').write_text('code', encoding='utf-8')
            pre = create_snapshot(work)
            for relative_path in (
                'results/out.csv',
                'logs/run.log',
                'tmp/scratch.bin',
                'cache/index.db',
                'notes.txt',
            ):
                path = work / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(relative_path, encoding='utf-8')
            post = create_snapshot(work)

            groups = classify_files(_build_result(), pre, post, _rules())

            self.assertEqual(groups.outputs, ['results/out.csv'])
            self.assertEqual(groups.logs, ['logs/run.log'])
            self.assertEqual(groups.temp, ['tmp/scratch.bin'])
            self.assertEqual(groups.ignored, ['cache/index.db'])
            self.assertEqual(groups.unknown, ['notes.txt'])

    def test_deleted_files_are_recorded_separately(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            (work / 'old.txt').write_text('old', encoding='utf-8')
            pre = create_snapshot(work)
            (work / 'old.txt').unlink()
            post = create_snapshot(work)

            groups = classify_files(_build_result(), pre, post, _rules())

            self.assertEqual(groups.deleted, ['old.txt'])


if __name__ == '__main__':
    unittest.main()
