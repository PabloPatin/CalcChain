import hashlib
import unittest

from calcchain_core.build_plan import create_build_lock, validate_build_lock
from calcchain_core.errors import BuildPlanError
from calcchain_core.models import (
    BuildConfig,
    BuildInfo,
    BuildLock,
    CodeConfig,
    InputConfig,
    LockMetadata,
    RuleSetType,
    RulesFile,
    SourceRef,
)
from calcchain_core.sources import SourceRegistry


class MemoryAdapter:
    def __init__(self, trees, *, versionable=False, resolved_revision=1842):
        self.trees = trees
        self.versionable = versionable
        self.resolved_revision = resolved_revision

    def list_files(self, source):
        return sorted(self.trees[source.path])

    def read_file(self, source, relative_path):
        return self.trees[source.path][relative_path]

    def resolve_revision(self, source):
        if source.revision == 'HEAD':
            return SourceRef(
                type=source.type,
                location=source.location,
                path=source.path,
                revision=self.resolved_revision,
            )
        return source

    def is_versionable(self, source):
        return self.versionable


class FailIfCalledAdapter:
    def __init__(self):
        self.calls = []

    def list_files(self, source):
        self.calls.append(('list_files', source.path))
        raise AssertionError('adapter must not be called for unsafe source refs')

    def read_file(self, source, relative_path):
        self.calls.append(('read_file', source.path, relative_path))
        raise AssertionError('adapter must not be called for unsafe source refs')

    def resolve_revision(self, source):
        self.calls.append(('resolve_revision', source.path))
        raise AssertionError('adapter must not be called for unsafe source refs')

    def is_versionable(self, source):
        self.calls.append(('is_versionable', source.path))
        raise AssertionError('adapter must not be called for unsafe source refs')


def rules_file(
    *,
    code_destination='<capt:1>',
    input_destination='input/<capt:1>',
    input_type='input',
    input_source='(.*)',
    ensure_input=True,
) -> RulesFile:
    return RulesFile.from_dict(
        {
            'rule_sets': {
                'code_all': {
                    'type': 'code',
                    'status': 'stable',
                    'ensure_all_files': True,
                    'rules': [{'source': '(.*)', 'destination': code_destination}],
                },
                'input_all': {
                    'type': input_type,
                    'status': 'stable',
                    'ensure_all_files': ensure_input,
                    'rules': [{'source': input_source, 'destination': input_destination}],
                },
            },
        },
    )


def build_config(*, code_rule='code_all', input_rule='input_all', input_svn=False) -> BuildConfig:
    input_source = (
        {
            'type': 'svn',
            'location': 'https://svn.example.org/data',
            'path': 'input',
            'revision': 'HEAD',
        }
        if input_svn
        else {'type': 'local', 'path': 'input'}
    )
    data = {
        'build': {'name': 'case'},
        'code': {'source': {'type': 'local', 'path': 'code'}},
        'rules': {'source': {'type': 'local', 'path': 'rules.json'}},
        'inputs': [{'name': 'mesh', 'source': input_source}],
    }
    if code_rule is not None:
        data['code']['rule_set'] = code_rule
    if input_rule is not None:
        data['inputs'][0]['rule_set'] = input_rule
    if code_rule is None and input_rule is None:
        data.pop('rules')
    return BuildConfig.from_dict(data)


def registry(*, input_tree=None, code_tree=None):
    code_tree = code_tree or {'solver.py': b'print("ok")\n', 'lib/math.txt': b'math'}
    input_tree = input_tree or {'mesh.msh': b'mesh'}
    return SourceRegistry(
        {
            'local': MemoryAdapter(
                {
                    'code': code_tree,
                    'input': input_tree,
                    'rules.json': {'rules.json': b'{}'},
                },
            ),
            'svn': MemoryAdapter({'input': input_tree}, versionable=True, resolved_revision=1842),
        },
    )


class TestCoreBuildPlan(unittest.TestCase):
    def test_create_build_lock_resolves_svn_head_and_rules_metadata(self):
        build = build_config(input_svn=True)
        lock = create_build_lock(build, registry(), rules_file())

        self.assertEqual(lock.inputs[0].source.revision, 1842)
        self.assertEqual(lock.lock.created_from, 'build.toml')
        self.assertEqual(len(lock.lock.source_sha256), 64)
        self.assertIsNotNone(lock.rules)
        self.assertEqual(lock.rules.resolved['schema_version'], '1.0')
        self.assertEqual(len(lock.rules.resolved['sha256']), 64)

    def test_validate_build_lock_returns_hashed_plan_entries(self):
        build = build_config()
        rules = rules_file()
        lock = create_build_lock(build, registry(), rules)

        plan = validate_build_lock(lock, registry(), rules)

        by_work_path = {entry.work_path: entry for entry in plan.entries}
        self.assertEqual(sorted(by_work_path), ['input/mesh.msh', 'lib/math.txt', 'solver.py'])
        self.assertEqual(
            by_work_path['solver.py'].sha256,
            hashlib.sha256(b'print("ok")\n').hexdigest(),
        )
        self.assertEqual(by_work_path['input/mesh.msh'].rules.set, 'input_all')
        self.assertEqual(plan.warnings, [])

    def test_validate_build_lock_allows_full_tree_without_rules_source(self):
        build = build_config(code_rule=None, input_rule=None)
        lock = create_build_lock(build, registry(), None)

        plan = validate_build_lock(lock, registry(), None)

        self.assertEqual(sorted(entry.work_path for entry in plan.entries), ['lib/math.txt', 'mesh.msh', 'solver.py'])
        self.assertTrue(all(entry.rules is None for entry in plan.entries))

    def test_validate_build_lock_maps_code_full_tree_when_code_rule_is_absent(self):
        build = build_config(code_rule=None, input_rule='input_all')
        rules = rules_file()
        data_registry = registry()
        lock = create_build_lock(build, data_registry, rules)

        plan = validate_build_lock(lock, data_registry, rules)

        code_entries = [entry for entry in plan.entries if entry.role == 'code']
        input_entries = [entry for entry in plan.entries if entry.role == 'input']
        self.assertEqual(sorted(entry.work_path for entry in code_entries), ['lib/math.txt', 'solver.py'])
        self.assertTrue(all(entry.rules is None for entry in code_entries))
        self.assertEqual([entry.work_path for entry in input_entries], ['input/mesh.msh'])
        self.assertEqual(input_entries[0].rules.set, 'input_all')

    def test_missing_rules_and_wrong_rule_type_fail(self):
        build = build_config()
        lock = create_build_lock(build, registry(), rules_file())

        with self.assertRaises(BuildPlanError):
            validate_build_lock(lock, registry(), None)

        with self.assertRaises(BuildPlanError):
            create_build_lock(build, registry(), None)

        wrong_type_rules = rules_file(input_type=RuleSetType.OUTPUT.value)
        wrong_type_lock = create_build_lock(build, registry(), wrong_type_rules)
        with self.assertRaises(BuildPlanError):
            validate_build_lock(wrong_type_lock, registry(), wrong_type_rules)

        wrong_code_data = rules_file().to_dict()
        wrong_code_data['rule_sets']['code_all']['type'] = RuleSetType.INPUT.value
        wrong_code_rules = RulesFile.from_dict(wrong_code_data)
        wrong_code_lock = create_build_lock(build, registry(), wrong_code_rules)
        with self.assertRaises(BuildPlanError):
            validate_build_lock(wrong_code_lock, registry(), wrong_code_rules)

    def test_skipped_required_files_fail_before_plan(self):
        build = build_config()
        rules = rules_file(input_source='.*\\.msh')
        lock = create_build_lock(build, registry(input_tree={'mesh.msh': b'mesh', 'note.txt': b'note'}), rules)

        with self.assertRaises(BuildPlanError):
            validate_build_lock(
                lock,
                registry(input_tree={'mesh.msh': b'mesh', 'note.txt': b'note'}),
                rules,
            )

    def test_duplicate_work_paths_fail_before_plan(self):
        build = build_config()
        rules = rules_file(code_destination='shared/<capt:1>', input_destination='shared/<capt:1>')
        data_registry = registry(code_tree={'same.dat': b'code'}, input_tree={'same.dat': b'input'})
        lock = create_build_lock(build, data_registry, rules)

        with self.assertRaises(BuildPlanError):
            validate_build_lock(lock, data_registry, rules)

    def test_unsafe_rule_destinations_fail_before_plan(self):
        build = build_config(code_rule=None, input_rule='input_all')
        for destination in ('../<capt:1>', 'C:/out/<capt:1>'):
            with self.subTest(destination=destination):
                rules = rules_file(input_destination=destination)
                data_registry = registry()
                lock = create_build_lock(build, data_registry, rules)

                with self.assertRaises(BuildPlanError):
                    validate_build_lock(lock, data_registry, rules)

    def test_unsafe_default_source_path_and_unresolved_svn_revision_fail(self):
        build = build_config(code_rule=None, input_rule=None)
        unsafe_registry = registry(code_tree={'../escape.py': b'bad'}, input_tree={'mesh.msh': b'mesh'})
        lock = create_build_lock(build, unsafe_registry, None)

        with self.assertRaises(BuildPlanError):
            validate_build_lock(lock, unsafe_registry, None)

        unresolved_lock = BuildLock(
            schema_version='1.0',
            lock=LockMetadata(
                created_at='2026-05-03T00:00:00+00:00',
                created_from='build.toml',
                source_sha256='1' * 64,
                source_sha256_field='build_toml_sha256',
            ),
            build=BuildInfo(name='case'),
            code=CodeConfig(source=SourceRef.from_dict({'type': 'local', 'path': 'code'})),
            inputs=[
                InputConfig(
                    source=SourceRef.from_dict(
                        {
                            'type': 'svn',
                            'location': 'https://svn.example.org/data',
                            'path': 'input',
                            'revision': 'HEAD',
                        },
                    ),
                    name='mesh',
                ),
            ],
        )

        with self.assertRaises(BuildPlanError):
            validate_build_lock(unresolved_lock, registry(), None)

    def test_create_build_lock_rejects_unsafe_svn_refs_before_registry(self):
        svn_adapter = FailIfCalledAdapter()
        data_registry = SourceRegistry({'svn': svn_adapter})
        unsafe_sources = (
            {
                'type': 'svn',
                'location': 'https://svn.example.org/data',
                'path': '../private',
                'revision': 'HEAD',
            },
            {
                'type': 'svn',
                'location': 'https://svn.example.org/data',
                'path': '/private',
                'revision': 'HEAD',
            },
            {
                'type': 'svn',
                'location': 'https://svn.example.org/data',
                'path': 'C:/private',
                'revision': 'HEAD',
            },
            {
                'type': 'svn',
                'location': 'https://user:secret@svn.example.org/data',
                'path': 'input',
                'revision': 'HEAD',
            },
        )

        for source_data in unsafe_sources:
            with self.subTest(source=source_data):
                build = BuildConfig.from_dict(
                    {
                        'build': {'name': 'case'},
                        'code': {'source': {'type': 'local', 'path': 'code'}},
                        'inputs': [{'name': 'mesh', 'source': source_data}],
                    },
                )

                with self.assertRaises(BuildPlanError) as caught:
                    create_build_lock(build, data_registry, None)
                self.assertNotIn('secret', str(caught.exception))

        self.assertEqual(svn_adapter.calls, [])

    def test_validate_build_lock_rejects_unsafe_svn_refs_before_registry(self):
        svn_adapter = FailIfCalledAdapter()
        data_registry = SourceRegistry({'svn': svn_adapter})
        unsafe_sources = (
            {
                'type': 'svn',
                'location': 'https://svn.example.org/data',
                'path': '../private',
                'revision': 1842,
            },
            {
                'type': 'svn',
                'location': 'https://svn.example.org/data',
                'path': '/private',
                'revision': 1842,
            },
            {
                'type': 'svn',
                'location': 'https://svn.example.org/data',
                'path': 'C:/private',
                'revision': 1842,
            },
            {
                'type': 'svn',
                'location': 'https://user:secret@svn.example.org/data',
                'path': 'input',
                'revision': 1842,
            },
        )

        for source_data in unsafe_sources:
            with self.subTest(source=source_data):
                lock = BuildLock(
                    schema_version='1.0',
                    lock=LockMetadata(
                        created_at='2026-05-03T00:00:00+00:00',
                        created_from='build.toml',
                        source_sha256='1' * 64,
                        source_sha256_field='build_toml_sha256',
                    ),
                    build=BuildInfo(name='case'),
                    code=CodeConfig(source=SourceRef.from_dict({'type': 'local', 'path': 'code'})),
                    inputs=[
                        InputConfig(
                            source=SourceRef.from_dict(source_data),
                            name='mesh',
                        ),
                    ],
                )

                with self.assertRaises(BuildPlanError) as caught:
                    validate_build_lock(lock, data_registry, None)

                self.assertNotIn('secret', str(caught.exception))
        self.assertEqual(svn_adapter.calls, [])


if __name__ == '__main__':
    unittest.main()
