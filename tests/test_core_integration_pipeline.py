import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from calcchain_core import CalculationCore
from calcchain_core.restore import RestoreRequest
from calcchain_core.utils.json import write_json
from calcchain_core.utils.toml import write_toml


class TestCoreIntegrationPipeline(unittest.TestCase):
    def test_full_local_pipeline_build_run_publish_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code_source = root / 'code_source'
            input_source = root / 'input_source'
            publish_service = root / 'published_service'
            publish_outputs = root / 'published_outputs'
            job_dir = root / 'job'
            restore_job = root / 'restored_job'

            code_source.mkdir()
            input_source.mkdir()
            job_dir.mkdir()
            (code_source / 'solver.py').write_text('print("solver")\n', encoding='utf-8')
            (input_source / 'mesh.dat').write_text('original-input\n', encoding='utf-8')
            _write_pipeline_configs(job_dir, code_source, input_source, publish_service, publish_outputs)

            core = CalculationCore(job_dir)
            build_lock = core.create_build_lock()
            build_plan = core.validate_build()
            build_result = core.build()

            self.assertEqual(build_lock.build.name, 'integration-job')
            self.assertEqual(sorted(entry.work_path for entry in build_plan.entries), ['mesh.dat', 'solver.py'])
            self.assertTrue((job_dir / 'work' / 'solver.py').is_file())
            self.assertFalse(build_result.dry_run)

            (job_dir / 'work' / 'mesh.dat').write_text('edited-before-run\n', encoding='utf-8')
            manifest_after_run = core.run()

            run_manifest = manifest_after_run.to_dict()
            self.assertEqual(run_manifest['run']['status'], 'Succeeded')
            self.assertEqual(run_manifest['run']['file_groups']['outputs'], ['result.txt'])
            self.assertEqual(
                (job_dir / 'work' / 'result.txt').read_text(encoding='utf-8'),
                'result: edited-before-run\n',
            )
            self.assertTrue((job_dir / '.calcchain' / 'frozen_inputs' / 'mesh.dat').is_file())

            publish_result = core.publish()

            self.assertFalse(publish_result.dry_run)
            self.assertTrue((publish_service / 'publish.lock.toml').is_file())
            self.assertTrue((publish_service / 'manifest.json').is_file())
            self.assertTrue((publish_service / 'frozen_inputs' / 'mesh.dat').is_file())
            self.assertEqual(
                (publish_outputs / 'archive' / 'result.txt').read_text(encoding='utf-8'),
                'result: edited-before-run\n',
            )

            shutil.rmtree(input_source)
            shutil.rmtree(job_dir / '.calcchain' / 'frozen_inputs')
            restore_result = core.restore(
                RestoreRequest(
                    manifest_path=job_dir / '.calcchain' / 'manifest.json',
                    target_job_dir=restore_job,
                ),
            )

            self.assertEqual(restore_result.status, 'restored')
            self.assertEqual(
                (restore_job / 'work' / 'solver.py').read_text(encoding='utf-8'),
                'print("solver")\n',
            )
            self.assertEqual(
                (restore_job / 'work' / 'mesh.dat').read_text(encoding='utf-8'),
                'edited-before-run\n',
            )
            self.assertFalse((restore_job / 'work' / 'result.txt').exists())


def _write_pipeline_configs(
    job_dir: Path,
    code_source: Path,
    input_source: Path,
    publish_service: Path,
    publish_outputs: Path,
) -> None:
    write_toml(
        {
            'build': {'name': 'integration-job'},
            'code': {'source': {'type': 'local', 'path': str(code_source)}},
            'inputs': [
                {
                    'name': 'mesh',
                    'source': {'type': 'local', 'path': str(input_source)},
                },
            ],
        },
        job_dir / 'build.toml',
    )
    write_toml(
        {
            'run': {
                'executable': sys.executable,
                'args': [
                    '-c',
                    (
                        'from pathlib import Path; '
                        'mesh = Path("mesh.dat").read_text(encoding="utf-8"); '
                        'Path("result.txt").write_text("result: " + mesh, encoding="utf-8")'
                    ),
                ],
                'cwd': '.',
                'timeout_seconds': 10,
            },
        },
        job_dir / 'run.toml',
    )
    write_json(
        {
            'rule_sets': {
                'outputs': {
                    'type': 'output',
                    'status': 'approved',
                    'ensure_all_files': True,
                    'rules': [
                        {
                            'source': r'result\.txt',
                            'destination': 'archive/result.txt',
                        },
                    ],
                },
            },
        },
        job_dir / 'rules.json',
    )
    write_toml(
        {
            'publish': {'message': 'integration publish'},
            'service_target': {'type': 'local', 'path': str(publish_service)},
            'targets': [
                {
                    'name': 'local_outputs',
                    'type': 'local',
                    'path': str(publish_outputs),
                    'rule_sets': ['outputs'],
                },
            ],
        },
        job_dir / 'publish.toml',
    )


if __name__ == '__main__':
    unittest.main()
