from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import tomlkit

from calcchain_core.api import CalculationCore
from calcchain_core.models import RuleSetType
from calcchain_core.restore.restore import RestoreRequest


class TestCoreEndToEnd(unittest.TestCase):
    def test_local_build_run_publish_restore_cleanup_via_public_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job = root / 'job'
            code = root / 'code'
            input_dir = root / 'input'
            service_target = root / 'published_service'
            output_target = root / 'published_outputs'
            log_target = root / 'published_logs'
            restored = root / 'restored'
            job.mkdir()
            code.mkdir()
            input_dir.mkdir()
            (code / 'solver.py').write_text(
                'from pathlib import Path\n'
                'mesh = Path("input/mesh.txt").read_text(encoding="utf-8")\n'
                'Path("results").mkdir(exist_ok=True)\n'
                'Path("logs").mkdir(exist_ok=True)\n'
                'Path("results/value.txt").write_text(mesh.upper(), encoding="utf-8")\n'
                'Path("logs/solver.log").write_text("done", encoding="utf-8")\n',
                encoding='utf-8',
            )
            (input_dir / 'input').mkdir()
            (input_dir / 'input' / 'mesh.txt').write_text('mesh\n', encoding='utf-8')
            _write_toml(
                job / 'build.toml',
                {
                    'build': {'name': 'case'},
                    'code': {'source': {'type': 'local', 'path': str(code)}},
                    'inputs': [{'name': 'input', 'source': {'type': 'local', 'path': str(input_dir)}}],
                },
            )
            _write_toml(
                job / 'run.toml',
                {'run': {'executable': sys.executable, 'args': ['solver.py'], 'cwd': '.', 'timeout_seconds': 10}},
            )
            _write_toml(
                job / 'publish.toml',
                {
                    'publish': {'message': 'publish'},
                    'service_target': {'type': 'local', 'path': str(service_target)},
                    'targets': [
                        {'name': 'outputs', 'type': 'local', 'path': str(output_target), 'rule_sets': ['standard_outputs']},
                        {'name': 'logs', 'type': 'local', 'path': str(log_target), 'rule_sets': ['standard_logs']},
                    ],
                },
            )
            (job / 'rules.json').write_text(
                json.dumps(
                    {
                        'rule_sets': {
                            'standard_outputs': {
                                'type': RuleSetType.OUTPUT.value,
                                'status': 'stable',
                                'ensure_all_files': True,
                                'rules': [{'source': 'results/(.*)', 'destination': '<capt:1>'}],
                            },
                            'standard_logs': {
                                'type': RuleSetType.LOGS.value,
                                'status': 'stable',
                                'ensure_all_files': True,
                                'rules': [{'source': 'logs/(.*)', 'destination': '<capt:1>'}],
                            },
                        },
                    },
                ),
                encoding='utf-8',
            )
            core = CalculationCore(job)

            lock = core.create_build_lock()
            plan = core.validate_build()
            build_result = core.build()
            manifest = core.run()
            dry_publish_result = core.publish(dry_run=True)
            self.assertFalse((service_target / 'manifest.json').exists())
            self.assertFalse((output_target / 'value.txt').exists())
            publish_result = core.publish()
            dry_restore_result = core.restore(RestoreRequest(service_target / 'manifest.json', restored, dry_run=True))
            self.assertFalse((restored / 'work').exists())
            restore_result = core.restore(RestoreRequest(service_target / 'manifest.json', restored))
            dry_cleanup_result = core.cleanup(dry_run=True)
            cleanup_result = core.cleanup()

            self.assertEqual(lock.build.name, 'case')
            self.assertTrue(plan.entries)
            self.assertFalse(build_result.dry_run)
            self.assertEqual(manifest.to_dict()['run']['status'], 'Succeeded')
            self.assertTrue(dry_publish_result.dry_run)
            self.assertEqual(publish_result.updated_manifest.to_dict()['job']['status'], 'Published')
            self.assertEqual((output_target / 'value.txt').read_text(encoding='utf-8'), 'MESH\n')
            self.assertEqual((log_target / 'solver.log').read_text(encoding='utf-8'), 'done')
            self.assertEqual(dry_restore_result.status, 'planned')
            self.assertEqual((restored / 'work' / 'results' / 'value.txt').read_text(encoding='utf-8'), 'MESH\n')
            self.assertEqual(restore_result.status, 'restored')
            self.assertEqual(dry_cleanup_result.status, 'planned')
            self.assertTrue(dry_cleanup_result.dry_run)
            self.assertEqual(cleanup_result.status, 'cleaned')
            self.assertTrue((job / '.calcchain' / 'manifest.json').is_file())
            self.assertEqual(list((job / 'work').iterdir()), [])


def _write_toml(path: Path, data: dict) -> None:
    path.write_text(tomlkit.dumps(data), encoding='utf-8')


if __name__ == '__main__':
    unittest.main()
