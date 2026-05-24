import sys
import tempfile
import unittest
from pathlib import Path

from calcchain_core.build import BuildConfig, EnvironmentBuilder, create_build_lock, validate_build_lock
from calcchain_core.common.status import RunStatus
from calcchain_core.io import SourceRegistry
from calcchain_core.run import ProcessRunner, RunConfig, RunEnvironment
from calcchain_core.secrets import SecretsResolver
from calcchain_core.workspace.layout import JobLayout


class StaticSecretsResolver(SecretsResolver):
    def __init__(self, values):
        self.values = dict(values)
        self.calls = []

    def resolve(self, key, *, context=None):
        self.calls.append((key, dict(context or {})))
        return self.values[key]


class TestCoreCurrentBuildRun(unittest.TestCase):
    def test_build_config_accepts_missing_inputs(self):
        config = BuildConfig.from_dict(
            {'code': {'source': {'type': 'local', 'path': 'code'}}},
            default_build_name='job-name',
        )

        self.assertEqual(config.build.name, 'job-name')
        self.assertEqual(config.inputs, [])
        self.assertEqual(config.to_dict()['inputs'], [])

    def test_build_lock_plan_and_builder_materialize_local_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code = root / 'code'
            data = root / 'data'
            code.mkdir()
            data.mkdir()
            (code / 'solver.py').write_text('print("ok")\n', encoding='utf-8')
            (data / 'mesh.dat').write_text('mesh\n', encoding='utf-8')
            layout = JobLayout.from_job_dir(root / 'job')

            config = BuildConfig.from_dict(
                {
                    'build': {'name': 'case'},
                    'code': {'source': {'type': 'local', 'path': str(code)}},
                    'inputs': [{'name': 'mesh', 'source': {'type': 'local', 'path': str(data)}}],
                },
            )
            registry = SourceRegistry()
            lock = create_build_lock(config, registry, rules=None)
            plan = validate_build_lock(lock, registry, rules=None)

            result = EnvironmentBuilder(registry).build(layout, plan)

            self.assertEqual(sorted(entry.work_path for entry in plan.entries), ['mesh.dat', 'solver.py'])
            self.assertEqual((layout.work_dir / 'solver.py').read_text(encoding='utf-8'), 'print("ok")\n')
            self.assertEqual((layout.work_dir / 'mesh.dat').read_text(encoding='utf-8'), 'mesh\n')
            self.assertEqual(result.code_set.name, 'code')
            self.assertEqual([item.name for item in result.input_sets], ['mesh'])
            self.assertTrue((layout.build_artifacts_dir / 'build_lock.json').is_file())
            self.assertTrue((layout.snapshots_dir / 'build_snapshot.json').is_file())
            self.assertFalse(result.dry_run)

    def test_environment_builder_dry_run_does_not_write_workdir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code = root / 'code'
            code.mkdir()
            (code / 'solver.py').write_text('print("ok")\n', encoding='utf-8')
            layout = JobLayout.from_job_dir(root / 'job')
            config = BuildConfig.from_dict({'code': {'source': {'type': 'local', 'path': str(code)}}})
            lock = create_build_lock(config, SourceRegistry(), rules=None)
            plan = validate_build_lock(lock, SourceRegistry(), rules=None)

            result = EnvironmentBuilder(SourceRegistry()).build(layout, plan, dry_run=True)

            self.assertTrue(result.dry_run)
            self.assertFalse(layout.work_dir.exists())
            self.assertIn('copy files: 1', result.preview)

    def test_process_runner_script_stdin_secret_env_and_redacted_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            layout = JobLayout.from_job_dir(root / 'job')
            layout.work_dir.mkdir(parents=True)
            resolver = StaticSecretsResolver({'token-key': 'plain-secret'})
            request = RunConfig(
                schema_version='1.0',
                executable=sys.executable,
                args=[
                    '-c',
                    (
                        'import os, pathlib, sys; '
                        'payload = sys.stdin.read(); '
                        'print(os.environ["TOKEN"]); '
                        'pathlib.Path("result.txt").write_text(payload, encoding="utf-8")'
                    ),
                ],
                cwd='.',
                timeout_seconds=10,
                stdin_mode='script',
                stdin_text='payload-data',
                env=RunEnvironment(public={'VISIBLE': '1'}, secrets={'TOKEN': 'token-key'}),
            )

            result = ProcessRunner(resolver).run(layout, request)

            self.assertEqual(result.status, RunStatus.SUCCEEDED)
            self.assertEqual(result.secret_names, ['TOKEN'])
            self.assertEqual(result.env, {'VISIBLE': '1'})
            self.assertEqual((layout.work_dir / 'result.txt').read_text(encoding='utf-8'), 'payload-data')
            stdout = (layout.job_dir / result.stdout_log).read_text(encoding='utf-8')
            self.assertIn('[secret]', stdout)
            self.assertNotIn('plain-secret', stdout)
            self.assertEqual(resolver.calls[0][1], {'kind': 'run.env', 'name': 'TOKEN'})

    def test_process_runner_rejects_cwd_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            layout = JobLayout.from_job_dir(Path(tmp) / 'job')
            layout.work_dir.mkdir(parents=True)
            request = RunConfig(schema_version='1.0', executable=sys.executable, cwd='..')

            with self.assertRaises(Exception) as caught:
                ProcessRunner(StaticSecretsResolver({})).run(layout, request)

            self.assertIn('cwd', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
