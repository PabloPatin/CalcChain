import json
import tempfile
import unittest
from pathlib import Path

from calcchain_core.errors import ConfigFormatError, RulesError
from calcchain_core.models import RuleSetType, RulesFile
from calcchain_core.rules import apply_rule_set, get_rule_set, load_rules


def rules_file() -> RulesFile:
    return RulesFile.from_dict(
        {
            'rule_sets': {
                'code_all': {
                    'type': 'code',
                    'status': 'stable',
                    'ensure_all_files': True,
                    'rules': [{'source': '(.*\\.py)', 'destination': '<capt:1>'}],
                },
                'input_mesh': {
                    'type': 'input',
                    'status': 'stable',
                    'ensure_all_files': True,
                    'rules': [{'source': '(.*\\.msh)', 'destination': 'input/mesh/<capt:1>'}],
                },
                'outputs': {
                    'type': 'output',
                    'status': 'stable',
                    'ensure_all_files': False,
                    'rules': [{'source': 'results/(.*)', 'destination': 'results/<capt:1>'}],
                },
            },
        },
    )


class TestCoreRules(unittest.TestCase):
    def test_load_rules_and_apply_typed_rule_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'rules.json'
            path.write_text(json.dumps(rules_file().to_dict()), encoding='utf-8')

            loaded = load_rules(path)
            rule_set = get_rule_set(loaded, 'input_mesh', RuleSetType.INPUT)
            entries = apply_rule_set(['mesh/case.msh'], rule_set)

        self.assertEqual(entries[0].source_path, 'mesh/case.msh')
        self.assertEqual(entries[0].work_path, 'input/mesh/mesh/case.msh')

    def test_missing_and_wrong_rule_type_are_rejected(self):
        rules = rules_file()

        with self.assertRaises(RulesError):
            get_rule_set(rules, 'missing', RuleSetType.INPUT)
        with self.assertRaises(RulesError):
            get_rule_set(rules, 'outputs', RuleSetType.INPUT)

    def test_invalid_regex_is_rejected(self):
        rule_set = RulesFile.from_dict(
            {
                'rule_sets': {
                    'bad': {
                        'type': 'input',
                        'ensure_all_files': False,
                        'rules': [{'source': '(', 'destination': 'out/<capt:1>'}],
                    },
                },
            },
        ).rule_sets['bad']

        with self.assertRaises(RulesError):
            apply_rule_set(['file.txt'], rule_set)

    def test_skipped_required_files_are_rejected(self):
        rule_set = get_rule_set(rules_file(), 'input_mesh', RuleSetType.INPUT)

        with self.assertRaises(RulesError):
            apply_rule_set(['mesh/case.msh', 'mesh/readme.txt'], rule_set)

    def test_duplicate_and_unsafe_destinations_are_rejected(self):
        duplicate = RulesFile.from_dict(
            {
                'rule_sets': {
                    'dup': {
                        'type': 'input',
                        'ensure_all_files': False,
                        'rules': [{'source': '(.*)', 'destination': 'same.txt'}],
                    },
                },
            },
        ).rule_sets['dup']
        traversal = RulesFile.from_dict(
            {
                'rule_sets': {
                    'escape': {
                        'type': 'input',
                        'ensure_all_files': False,
                        'rules': [{'source': '(.*)', 'destination': '../<capt:1>'}],
                    },
                },
            },
        ).rule_sets['escape']
        absolute = RulesFile.from_dict(
            {
                'rule_sets': {
                    'absolute': {
                        'type': 'input',
                        'ensure_all_files': False,
                        'rules': [{'source': '(.*)', 'destination': 'C:/out/<capt:1>'}],
                    },
                },
            },
        ).rule_sets['absolute']

        with self.assertRaises(RulesError):
            apply_rule_set(['a.txt', 'b.txt'], duplicate)
        with self.assertRaises(RulesError):
            apply_rule_set(['a.txt'], traversal)
        with self.assertRaises(RulesError):
            apply_rule_set(['a.txt'], absolute)

    def test_invalid_rules_json_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'rules.json'
            path.write_text('{not json', encoding='utf-8')

            with self.assertRaises(ConfigFormatError):
                load_rules(path)


if __name__ == '__main__':
    unittest.main()
