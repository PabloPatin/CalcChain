import hashlib
import tempfile
import unittest
from pathlib import Path

from calcchain_core import CalculationCore
from calcchain_core.build import BuildConfig
from calcchain_core.common.hash import tree_sha256
from calcchain_core.manifest_import import ManifestEnvironmentRequest, create_environment_from_manifest
from calcchain_core.publish import PublishConfig
from calcchain_core.rules import RulesFile
from calcchain_core.run import RunConfig
from calcchain_core.utils.json import read_json, write_json
from calcchain_core.utils.toml import read_toml


class TestCoreManifestImport(unittest.TestCase):
    def test_create_environment_from_manifest_writes_configs_and_restores_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, code_source, input_source = _write_manifest_fixture(root)
            target_job = root / 'imported-job'

            result = create_environment_from_manifest(
                ManifestEnvironmentRequest(manifest_path=manifest_path, target_job_dir=target_job),
            )

            self.assertEqual(result.status, 'created')
            self.assertEqual(
                sorted(result.written_files),
                ['build.toml', 'manifest.json', 'publish.toml', 'rules.json', 'run.toml'],
            )
            self.assertEqual(
                sorted(result.restored_files),
                ['input/case.txt', 'solver.py'],
            )
            self.assertEqual((target_job / 'work' / 'solver.py').read_text(encoding='utf-8'), 'print("ok")\n')
            self.assertEqual((target_job / 'work' / 'input' / 'case.txt').read_text(encoding='utf-8'), 'case=42\n')

            build = BuildConfig.from_dict(read_toml(target_job / 'build.toml'))
            self.assertEqual(build.build.name, 'case-42')
            self.assertEqual(build.code.source.data, {'type': 'local', 'path': str(code_source)})
            self.assertEqual(build.inputs[0].source.data, {'type': 'local', 'path': str(input_source)})

            run = RunConfig.from_dict(read_toml(target_job / 'run.toml'))
            self.assertEqual(run.executable, 'python')
            self.assertEqual(run.args, ['solver.py', '--case', 'input'])
            self.assertEqual(run.cwd, '.')
            self.assertEqual(run.stdin_mode, 'script')
            self.assertEqual(run.stdin_text, 'start\n')
            self.assertEqual(run.env.public, {'CALCCHAIN_MODE': 'run', 'OMP_NUM_THREADS': '4'})

            publish = PublishConfig.from_dict(read_toml(target_job / 'publish.toml'))
            self.assertEqual(publish.service_target.data['path'], str(root / 'service'))
            self.assertEqual(publish.targets[0].rule_sets, ['outputs'])

            rules = RulesFile.from_dict(read_json(target_job / 'rules.json'))
            self.assertEqual(rules.rule_sets['outputs'].rules[0].destination, 'report.txt')
            self.assertEqual(read_json(target_job / 'manifest.json')['job']['job_dir'], str(target_job))
            self.assertTrue(result.warnings)
            self.assertIn('LICENSE_TOKEN', result.warnings[0])

    def test_calculation_core_exposes_manifest_environment_builder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, _, _ = _write_manifest_fixture(root)
            target_job = root / 'imported-job'
            core = CalculationCore(root / 'unused-job')

            result = core.create_environment_from_manifest(
                ManifestEnvironmentRequest(manifest_path=manifest_path, target_job_dir=target_job),
            )

            self.assertEqual(result.status, 'created')
            self.assertTrue((target_job / 'build.toml').is_file())

    def test_dry_run_reports_planned_files_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, _, _ = _write_manifest_fixture(root)
            target_job = root / 'imported-job'

            result = create_environment_from_manifest(
                ManifestEnvironmentRequest(
                    manifest_path=manifest_path,
                    target_job_dir=target_job,
                    dry_run=True,
                ),
            )

            self.assertEqual(result.status, 'planned')
            self.assertFalse(target_job.exists())
            self.assertIn('build.toml', result.written_files)
            self.assertEqual(sorted(result.restored_files), ['input/case.txt', 'solver.py'])


def _write_manifest_fixture(root: Path) -> tuple[Path, Path, Path]:
    code_source = root / 'code-source'
    input_source = root / 'input-source'
    code_source.mkdir()
    input_source.mkdir()
    (code_source / 'solver.py').write_text('print("ok")\n', encoding='utf-8')
    (input_source / 'case.txt').write_text('case=42\n', encoding='utf-8')

    code_sha = _sha256(code_source / 'solver.py')
    input_sha = _sha256(input_source / 'case.txt')
    manifest = {
        'schema_version': '1.0',
        'job': {'id': 'case-42', 'status': 'Published', 'job_dir': str(root / 'old-job')},
        'build': {
            'code': {
                'name': 'solver',
                'tree_sha256': tree_sha256([('solver.py', code_sha)]),
                'sources': [{'type': 'local', 'path': str(code_source)}],
                'map': [{'source_path': 'solver.py', 'work_path': 'solver.py', 'sha256': code_sha}],
            },
            'inputs': [
                {
                    'name': 'case',
                    'tree_sha256': tree_sha256([('input/case.txt', input_sha)]),
                    'sources': [{'type': 'local', 'path': str(input_source)}],
                    'map': [{'source_path': 'case.txt', 'work_path': 'input/case.txt', 'sha256': input_sha}],
                },
            ],
        },
        'run': {
            'command': ['python', 'solver.py', '--case', 'input'],
            'cwd': str(root / 'old-job' / 'work'),
            'timeout_seconds': 3600,
            'encoding': 'utf-8',
            'env': {'OMP_NUM_THREADS': '4', 'CALCCHAIN_MODE': 'run'},
            'secret_names': ['LICENSE_TOKEN'],
            'stdin': {'mode': 'script', 'text': 'start\n'},
            'status': 'Succeeded',
            'return_code': 0,
            'file_groups': {
                'outputs': ['results/report.txt'],
                'logs': [],
                'temp': [],
                'ignored': [],
                'unknown': [],
                'deleted': [],
            },
        },
        'publication': {
            'service_target': {'type': 'local', 'path': str(root / 'service')},
            'outputs': [
                {
                    'name': 'published-results',
                    'target': {'type': 'local', 'path': str(root / 'results')},
                    'rules': {'set': 'outputs'},
                    'map': [
                        {
                            'source_path': 'results/report.txt',
                            'work_path': 'results/report.txt',
                            'target_path': 'report.txt',
                            'sha256': 'a' * 64,
                        },
                    ],
                },
            ],
        },
    }
    manifest_path = root / 'manifest.json'
    write_json(manifest, manifest_path)
    return manifest_path, code_source, input_source


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == '__main__':
    unittest.main()
