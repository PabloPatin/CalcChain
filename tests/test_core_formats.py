import json
import tempfile
import unittest
from pathlib import Path

import tomllib

from calcchain_core.config import (
    read_build,
    read_build_lock,
    read_publish,
    read_rules,
    read_run,
    write_build_lock,
    write_manifest,
    write_publish_lock,
)
from calcchain_core.errors import ConfigFormatError
from calcchain_core.hash import sha256_file, tree_sha256
from calcchain_core.layout import JobLayout, PublicationServiceLayout
from calcchain_core.models import (
    BuildConfig,
    BuildLock,
    Manifest,
    PublishConfig,
    PublishLock,
    RunConfig,
    SourceRef,
    SourceType,
    TargetRef,
)

EXAMPLES_DIR = (
    Path(__file__).resolve().parents[1]
    / '.ai_workspace'
    / 'runs'
    / 'run-20260501-183759'
    / 'packets'
    / 'format_examples'
)


class TestCoreFormats(unittest.TestCase):
    def test_format_examples_parse(self):
        build = read_build(EXAMPLES_DIR / 'build.toml')
        build_lock = read_build_lock(EXAMPLES_DIR / 'build.lock.toml')
        run = read_run(EXAMPLES_DIR / 'run.toml')
        publish = read_publish(EXAMPLES_DIR / 'publish.toml')
        rules = read_rules(EXAMPLES_DIR / 'rules.json')

        with (EXAMPLES_DIR / 'publish.lock.toml').open('rb') as file:
            publish_lock = PublishLock.from_dict(tomllib.load(file))
        with (EXAMPLES_DIR / 'manifest.json').open('r', encoding='utf-8') as file:
            manifest = Manifest.from_dict(json.load(file))

        self.assertIsInstance(build, BuildConfig)
        self.assertIsInstance(build_lock, BuildLock)
        self.assertIsInstance(run, RunConfig)
        self.assertIsInstance(publish, PublishConfig)
        self.assertEqual(run.env['OMP_NUM_THREADS'], '4')
        self.assertEqual(run.secret_env, ['LICENSE_TOKEN'])
        self.assertIn('standard_outputs', rules.rule_sets)
        self.assertEqual(publish_lock.service_target.revision, 2910)
        self.assertEqual(manifest.data['job']['status'], 'Published')

    def test_defaults_are_applied(self):
        config = BuildConfig.from_dict(
            {
                'code': {'source': {'type': 'local', 'path': 'D:/solver'}},
                'inputs': [{'source': {'type': 'local', 'path': 'D:/input'}}],
            },
        )

        self.assertEqual(config.schema_version, '1.0')
        self.assertEqual(config.build.description, '')
        self.assertEqual(config.code.name, 'solver')
        self.assertEqual(config.code.version, '')
        self.assertEqual(config.inputs[0].name, 'input_1')
        self.assertIsNone(config.inputs[0].rule_set)

        run = RunConfig.from_dict({'run': {'executable': 'solver.exe'}})

        self.assertEqual(run.schema_version, '1.0')
        self.assertEqual(run.args, [])
        self.assertEqual(run.cwd, '.')
        self.assertIsNone(run.timeout_seconds)
        self.assertEqual(run.encoding, 'utf-8')
        self.assertEqual(run.stdin_mode, 'none')
        self.assertEqual(run.secret_env, [])

        with tempfile.TemporaryDirectory() as tmp:
            build_path = Path(tmp) / 'job-from-dir' / 'build.toml'
            build_path.parent.mkdir()
            build_path.write_text(
                '[code]\n'
                '  [code.source]\n'
                '  type = "local"\n'
                '  path = "D:/solver"\n'
                '[[inputs]]\n'
                '  [inputs.source]\n'
                '  type = "local"\n'
                '  path = "D:/input"\n',
                encoding='utf-8',
            )

            self.assertEqual(read_build(build_path).build.name, 'job-from-dir')

    def test_invalid_local_and_svn_shapes_are_rejected(self):
        with self.assertRaises(ConfigFormatError):
            SourceRef.from_dict({'type': 'local', 'revision': 10})
        with self.assertRaises(ConfigFormatError):
            SourceRef.from_dict({'type': 'local', 'location': 'D:/source', 'path': 'solver'})
        with self.assertRaises(ConfigFormatError):
            SourceRef.from_dict({'type': 'local'})
        with self.assertRaises(ConfigFormatError):
            SourceRef.from_dict({'type': 'svn', 'path': 'trunk'})
        with self.assertRaises(ConfigFormatError):
            SourceRef.from_dict({'type': 'svn', 'location': 'https://svn.example/repo'})
        with self.assertRaises(ConfigFormatError):
            SourceRef.from_dict(
                {'type': 'svn', 'location': 'https://svn.example/repo', 'path': 'trunk', 'revision': 'HEAD'},
                resolved_revision=True,
            )
        with self.assertRaises(ConfigFormatError):
            TargetRef.from_dict({'type': 'local', 'location': 'D:/target', 'path': 'out'})
        with self.assertRaises(ConfigFormatError):
            TargetRef.from_dict({'type': 'local', 'path': 'out', 'revision': 10})
        with self.assertRaises(ConfigFormatError):
            TargetRef.from_dict({'type': 'svn', 'path': 'out'})

    def test_plugin_source_and_target_refs_preserve_dynamic_fields(self):
        source = SourceRef.from_dict(
            {
                'type': 'git',
                'url': 'https://git.example/repo.git',
                'branch': 'main',
                'depth': 1,
                'plugin': {'id': 'calcchain.git', 'version': '1.2.0'},
            },
        )
        target = TargetRef.from_dict(
            {
                'type': 'release-store',
                'bucket': 'results',
                'prefix': 'case-1',
                'plugin': {'id': 'calcchain.release', 'version': '2.0.0'},
            },
        )

        self.assertEqual(source.type, 'git')
        self.assertEqual(source.plugin.id, 'calcchain.git')
        self.assertEqual(source.extra['branch'], 'main')
        self.assertEqual(
            source.to_dict(),
            {
                'type': 'git',
                'plugin': {'id': 'calcchain.git', 'version': '1.2.0'},
                'url': 'https://git.example/repo.git',
                'branch': 'main',
                'depth': 1,
            },
        )
        self.assertEqual(
            target.to_dict(),
            {
                'type': 'release-store',
                'plugin': {'id': 'calcchain.release', 'version': '2.0.0'},
                'bucket': 'results',
                'prefix': 'case-1',
            },
        )

    def test_plugin_ref_metadata_and_extra_fields_are_validated(self):
        with self.assertRaises(ConfigFormatError):
            SourceRef.from_dict({'type': '', 'path': 'repo'})
        with self.assertRaises(ConfigFormatError):
            SourceRef.from_dict({'type': 'git', 'plugin': {'id': 10, 'version': '1.0.0'}})
        with self.assertRaises(ConfigFormatError):
            SourceRef.from_dict({'type': 'git', 'plugin': {'id': 'calcchain.git', 'version': 10}})
        with self.assertRaises(ConfigFormatError):
            TargetRef.from_dict({'type': 'release-store', 'runtime': object()})
        with self.assertRaises(ConfigFormatError):
            SourceRef.from_dict({'type': 'git', 'revision': object()})

    def test_svn_refs_reject_embedded_userinfo_at_parse_and_serialize_boundaries(self):
        source_data = {
            'type': 'svn',
            'location': 'https://user:secret@svn.example/repo',
            'path': 'trunk',
            'revision': 12,
        }
        target_data = {
            'type': 'svn',
            'location': 'https://user:secret@svn.example/repo',
            'path': 'out',
            'revision': 12,
        }

        with self.assertRaises(ConfigFormatError):
            SourceRef.from_dict(source_data, reject_userinfo=True)
        with self.assertRaises(ConfigFormatError):
            TargetRef.from_dict(target_data, reject_userinfo=True)
        with self.assertRaises(ConfigFormatError):
            SourceRef.from_dict(source_data).to_dict()
        with self.assertRaises(ConfigFormatError):
            TargetRef.from_dict(target_data).to_dict()

    def test_run_toml_has_no_output_rule_set(self):
        with self.assertRaises(ConfigFormatError):
            RunConfig.from_dict(
                {'run': {'executable': 'solver.exe', 'output_rule_set': 'standard_outputs'}},
            )

    def test_secret_env_models_names_only(self):
        run = RunConfig.from_dict(
            {'run': {'executable': 'solver.exe'}, 'secret_env': ['LICENSE_TOKEN', 'API_KEY']},
        )

        self.assertEqual(run.secret_env, ['LICENSE_TOKEN', 'API_KEY'])
        self.assertEqual(run.to_dict()['secret_env'], ['LICENSE_TOKEN', 'API_KEY'])

        with self.assertRaises(ConfigFormatError):
            RunConfig.from_dict({'run': {'executable': 'solver.exe'}, 'secret_env': {'API_KEY': 'value'}})
        with self.assertRaises(ConfigFormatError):
            RunConfig.from_dict(
                {'run': {'executable': 'solver.exe', 'secret_env': ['API_KEY']}},
            )

    def test_publish_supports_multiple_targets_and_one_service_target(self):
        publish = read_publish(EXAMPLES_DIR / 'publish.toml')

        self.assertEqual(publish.service_target.type, SourceType.SVN)
        self.assertEqual(len(publish.targets), 2)
        self.assertEqual(publish.targets[0].rule_sets, ['standard_outputs'])
        self.assertEqual(publish.targets[1].target.type, SourceType.LOCAL)

        with self.assertRaises(ConfigFormatError):
            PublishConfig.from_dict(
                {
                    'service_target': {'type': 'local', 'path': 'D:/service'},
                    'service_layout': {'manifest': 'user-controlled.json'},
                },
            )

    def test_manifest_shape_matches_example(self):
        with (EXAMPLES_DIR / 'manifest.json').open('r', encoding='utf-8') as file:
            manifest = Manifest.from_dict(json.load(file))

        self.assertEqual(manifest.schema_version, '1.0')
        self.assertEqual(manifest.data['run']['status'], 'Succeeded')
        self.assertEqual(
            manifest.data['publication']['outputs'][0]['map'][0]['work_path'],
            'results/temperature.csv',
        )

    def test_manifest_secrets_are_names_only(self):
        manifest = Manifest.from_dict(
            {
                'job': {'status': 'Succeeded'},
                'build': {},
                'run': {'env': {'secrets': ['LICENSE_TOKEN', 'API_KEY']}},
            },
        )

        self.assertEqual(manifest.data['run']['env']['secrets'], ['LICENSE_TOKEN', 'API_KEY'])

        invalid_secrets = (
            {'API_KEY': 'secret-value'},
            'API_KEY=secret-value',
            ['API_KEY', {'name': 'LICENSE_TOKEN'}],
            ['API_KEY', 10],
        )
        for secrets in invalid_secrets:
            with self.subTest(secrets=secrets):
                with self.assertRaises(ConfigFormatError):
                    Manifest.from_dict(
                        {
                            'job': {'status': 'Succeeded'},
                            'build': {},
                            'run': {'env': {'secrets': secrets}},
                        },
                    )

    def test_examples_use_path_only_local_refs_and_secret_names(self):
        example_data = []
        for name in ('build.toml', 'build.lock.toml', 'publish.toml', 'publish.lock.toml'):
            with (EXAMPLES_DIR / name).open('rb') as file:
                example_data.append(tomllib.load(file))
        with (EXAMPLES_DIR / 'manifest.json').open('r', encoding='utf-8') as file:
            manifest_data = json.load(file)
            example_data.append(manifest_data)
        with (EXAMPLES_DIR / 'run.toml').open('rb') as file:
            run_data = tomllib.load(file)

        for data in example_data:
            self._assert_local_refs_are_path_only(data)

        self.assertEqual(run_data['secret_env'], ['LICENSE_TOKEN'])
        self.assertNotIn('secret_env', run_data['run'])
        self.assertEqual(manifest_data['run']['env']['secrets'], ['LICENSE_TOKEN'])
        self.assertNotIsInstance(manifest_data['run']['env']['secrets'], dict)

    def test_toml_and_json_writers_use_supported_shape(self):
        build_lock = read_build_lock(EXAMPLES_DIR / 'build.lock.toml')
        with (EXAMPLES_DIR / 'publish.lock.toml').open('rb') as file:
            publish_lock = PublishLock.from_dict(tomllib.load(file))
        with (EXAMPLES_DIR / 'manifest.json').open('r', encoding='utf-8') as file:
            manifest = Manifest.from_dict(json.load(file))

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            build_lock_path = tmp_path / 'build.lock.toml'
            publish_lock_path = tmp_path / 'publish.lock.toml'
            manifest_path = tmp_path / 'manifest.json'

            write_build_lock(build_lock, build_lock_path)
            write_publish_lock(publish_lock, publish_lock_path)
            write_manifest(manifest, manifest_path)

            self.assertIsInstance(read_build_lock(build_lock_path), BuildLock)
            with publish_lock_path.open('rb') as file:
                self.assertIsInstance(PublishLock.from_dict(tomllib.load(file)), PublishLock)
            with manifest_path.open('r', encoding='utf-8') as file:
                self.assertEqual(json.load(file)['schema_version'], '1.0')

    def test_layout_is_app_controlled(self):
        layout = JobLayout.from_job_dir(Path('D:/jobs/case'))
        service_layout = PublicationServiceLayout()

        self.assertEqual(layout.job_dir, Path('D:/jobs/case'))
        self.assertEqual(layout.work_dir, Path('D:/jobs/case/work'))
        self.assertEqual(layout.service_dir, Path('D:/jobs/case/.calcchain'))
        self.assertEqual(layout.rules_dir, Path('D:/jobs/case/.calcchain/rules'))
        self.assertEqual(layout.logs_dir, Path('D:/jobs/case/.calcchain/logs'))
        self.assertEqual(layout.frozen_inputs_dir, Path('D:/jobs/case/.calcchain/frozen_inputs'))
        self.assertEqual(layout.snapshots_dir, Path('D:/jobs/case/.calcchain/snapshots'))
        self.assertEqual(layout.build_artifacts_dir, Path('D:/jobs/case/.calcchain/build'))
        self.assertEqual(layout.publication_artifacts_dir, Path('D:/jobs/case/.calcchain/publication'))
        self.assertEqual(layout.manifest_path, Path('D:/jobs/case/.calcchain/manifest.json'))
        self.assertEqual(service_layout.manifest_path, Path('_calcchain/manifest.json'))
        self.assertEqual(service_layout.frozen_inputs_path, Path('_calcchain/frozen_inputs'))
        self.assertEqual(service_layout.logs_path, Path('_calcchain/logs'))
        self.assertEqual(service_layout.rules_path, Path('_calcchain/rules'))
        self.assertEqual(service_layout.snapshots_path, Path('_calcchain/snapshots'))
        self.assertEqual(service_layout.publication_path, Path('_calcchain/publication'))

    def test_hash_helpers_are_deterministic_and_normalized(self):
        first = tree_sha256([('b\\file.txt', 'b' * 64), ('a/file.txt', 'a' * 64)])
        second = tree_sha256([('a/file.txt', 'a' * 64), ('b/file.txt', 'b' * 64)])
        normalized = tree_sha256([('/b/file.txt', 'B' * 64), ('a/file.txt', 'A' * 64)])

        self.assertEqual(first, second)
        self.assertEqual(first, normalized)

        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / 'payload.txt'
            file_path.write_bytes(b'CalcChain\n')

            self.assertEqual(
                sha256_file(file_path),
                '7d91d22114b93012cbe11d8cccafacdaabd922a671bbd09d8b55655e43fe6a54',
            )

    def _assert_local_refs_are_path_only(self, value):
        if isinstance(value, dict):
            if value.get('type') == 'local':
                self.assertIn('path', value)
                self.assertNotIn('location', value)
                self.assertNotIn('revision', value)
            for item in value.values():
                self._assert_local_refs_are_path_only(item)
        elif isinstance(value, list):
            for item in value:
                self._assert_local_refs_are_path_only(item)


if __name__ == '__main__':
    unittest.main()
