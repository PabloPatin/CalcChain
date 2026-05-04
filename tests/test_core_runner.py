import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

from calcchain_core.layout import JobLayout
from calcchain_core.models import RunConfig, RunStatus
from calcchain_core.runner import CancelToken, ProcessRunner
from calcchain_core.run_config import read_run


class _TimedCancelToken(CancelToken):
    def __init__(self, delay_seconds: float) -> None:
        self._cancel_at = time.monotonic() + delay_seconds

    def is_cancelled(self) -> bool:
        return time.monotonic() >= self._cancel_at


class TestCoreRunner(unittest.TestCase):
    def assertHeartbeatStopped(self, heartbeat_path: Path) -> None:
        self.assertTrue(heartbeat_path.exists())
        before = heartbeat_path.read_text(encoding='utf-8') if heartbeat_path.exists() else None
        time.sleep(0.5)
        after = heartbeat_path.read_text(encoding='utf-8') if heartbeat_path.exists() else None
        self.assertEqual(after, before)

    def test_read_run_uses_stage_1_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'run.toml'
            path.write_text(
                'schema_version = "1.0"\n'
                'secret_env = ["TOKEN"]\n'
                '[env]\n'
                'OMP_NUM_THREADS = "2"\n'
                '[run]\n'
                f"executable = '{sys.executable}'\n"
                'args = ["-c", "print(123)"]\n',
                encoding='utf-8',
            )

            config = read_run(path)

            self.assertEqual(config.env, {'OMP_NUM_THREADS': '2'})
            self.assertEqual(config.secret_env, ['TOKEN'])

    def test_success_writes_stdout_stderr_and_post_run_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            layout = JobLayout.from_job_dir(Path(tmp) / 'job')
            layout.work_dir.mkdir(parents=True)
            request = RunConfig.from_dict(
                {
                    'run': {
                        'executable': sys.executable,
                        'args': [
                            '-c',
                            (
                                'from pathlib import Path; '
                                'import sys; '
                                'Path("result.txt").write_text("done", encoding="utf-8"); '
                                'print("привет"); '
                                'print("warn", file=sys.stderr)'
                            ),
                        ],
                        'encoding': 'utf-8',
                    },
                    'env': {'PYTHONIOENCODING': 'utf-8'},
                },
            )

            result = ProcessRunner().run(layout, request)

            self.assertEqual(result.status, RunStatus.SUCCEEDED)
            self.assertEqual(result.return_code, 0)
            self.assertEqual((layout.logs_dir / 'stdout.txt').read_text(encoding='utf-8').strip(), 'привет')
            self.assertEqual((layout.logs_dir / 'stderr.txt').read_text(encoding='utf-8').strip(), 'warn')
            self.assertTrue((layout.snapshots_dir / 'post_run_snapshot.json').is_file())
            self.assertIn('result.txt', [entry.path for entry in result.post_run_snapshot.entries])
            self.assertEqual(
                json.loads((layout.service_dir / 'runtime_status.json').read_text(encoding='utf-8'))['job_status'],
                'Succeeded',
            )

    def test_failed_run_records_failed_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            layout = JobLayout.from_job_dir(Path(tmp) / 'job')
            layout.work_dir.mkdir(parents=True)
            request = RunConfig.from_dict(
                {'run': {'executable': sys.executable, 'args': ['-c', 'import sys; sys.exit(7)']}},
            )

            result = ProcessRunner().run(layout, request)

            self.assertEqual(result.status, RunStatus.FAILED)
            self.assertEqual(result.return_code, 7)

    def test_timeout_records_timeout_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            layout = JobLayout.from_job_dir(Path(tmp) / 'job')
            layout.work_dir.mkdir(parents=True)
            request = RunConfig.from_dict(
                {
                    'run': {
                        'executable': sys.executable,
                        'args': ['-c', 'import time; time.sleep(5)'],
                        'timeout_seconds': 1,
                    },
                },
            )

            result = ProcessRunner().run(layout, request)

            self.assertEqual(result.status, RunStatus.TIMEOUT)

    def test_timeout_terminates_child_process_tree_holding_stdout_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            layout = JobLayout.from_job_dir(Path(tmp) / 'job')
            layout.work_dir.mkdir(parents=True)
            heartbeat_path = Path(tmp) / 'heartbeat.txt'
            child_code = (
                'import pathlib, time\n'
                f'path = pathlib.Path({str(heartbeat_path)!r})\n'
                'for index in range(300):\n'
                '    path.write_text(str(index), encoding="utf-8")\n'
                '    time.sleep(0.1)\n'
            )
            parent_code = (
                'import subprocess, sys; '
                f'subprocess.Popen([sys.executable, "-c", {child_code!r}]); '
                'print("parent-exiting", flush=True)'
            )
            request = RunConfig.from_dict(
                {
                    'run': {
                        'executable': sys.executable,
                        'args': ['-c', parent_code],
                        'timeout_seconds': 1,
                    },
                },
            )

            started = time.monotonic()
            result = ProcessRunner().run(layout, request)
            elapsed = time.monotonic() - started

            self.assertEqual(result.status, RunStatus.TIMEOUT)
            self.assertLess(elapsed, 6)
            self.assertHeartbeatStopped(heartbeat_path)

    def test_cancel_terminates_child_process_tree_holding_stderr_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            layout = JobLayout.from_job_dir(Path(tmp) / 'job')
            layout.work_dir.mkdir(parents=True)
            heartbeat_path = Path(tmp) / 'heartbeat.txt'
            child_code = (
                'import pathlib, sys, time\n'
                'print("child", file=sys.stderr, flush=True)\n'
                f'path = pathlib.Path({str(heartbeat_path)!r})\n'
                'for index in range(300):\n'
                '    path.write_text(str(index), encoding="utf-8")\n'
                '    time.sleep(0.1)\n'
            )
            parent_code = (
                'import subprocess, sys; '
                f'subprocess.Popen([sys.executable, "-c", {child_code!r}]); '
                'print("parent-exiting", flush=True)'
            )
            request = RunConfig.from_dict(
                {
                    'run': {
                        'executable': sys.executable,
                        'args': ['-c', parent_code],
                    },
                },
            )

            started = time.monotonic()
            result = ProcessRunner().run(layout, request, cancel_token=_TimedCancelToken(0.2))
            elapsed = time.monotonic() - started

            self.assertEqual(result.status, RunStatus.CANCELLED)
            self.assertLess(elapsed, 6)
            self.assertHeartbeatStopped(heartbeat_path)

    def test_stdin_script_is_sent_and_logged_as_utf8(self):
        with tempfile.TemporaryDirectory() as tmp:
            layout = JobLayout.from_job_dir(Path(tmp) / 'job')
            layout.work_dir.mkdir(parents=True)
            request = RunConfig.from_dict(
                {
                    'run': {
                        'executable': sys.executable,
                        'args': ['-c', 'import sys; print(sys.stdin.read())'],
                        'stdin_mode': 'script',
                        'stdin_text': 'данные',
                        'encoding': 'utf-8',
                    },
                    'env': {'PYTHONIOENCODING': 'utf-8'},
                },
            )

            result = ProcessRunner().run(layout, request)

            self.assertEqual(result.status, RunStatus.SUCCEEDED)
            self.assertEqual((layout.logs_dir / 'stdin.txt').read_text(encoding='utf-8'), 'данные')
            self.assertEqual((layout.logs_dir / 'stdout.txt').read_text(encoding='utf-8').strip(), 'данные')
            self.assertEqual(result.stdin['log'], '.calcchain/logs/stdin.txt')

    def test_stdin_none_and_manual_do_not_send_or_log_stdin_text(self):
        for mode in ('none', 'manual'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                layout = JobLayout.from_job_dir(Path(tmp) / 'job')
                layout.work_dir.mkdir(parents=True)
                request = RunConfig.from_dict(
                    {
                        'run': {
                            'executable': sys.executable,
                            'args': ['-c', 'import sys; print(sys.stdin.read() or "empty")'],
                            'stdin_mode': mode,
                            'stdin_text': 'must-not-be-sent',
                        },
                    },
                )

                result = ProcessRunner().run(layout, request)

                self.assertEqual(result.status, RunStatus.SUCCEEDED)
                self.assertEqual(result.stdin, {'mode': mode})
                self.assertFalse((layout.logs_dir / 'stdin.txt').exists())
                self.assertEqual((layout.logs_dir / 'stdout.txt').read_text(encoding='utf-8').strip(), 'empty')

    def test_secret_values_are_not_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            layout = JobLayout.from_job_dir(Path(tmp) / 'job')
            layout.work_dir.mkdir(parents=True)
            os.environ['CALCCHAIN_TEST_SECRET'] = 'do-not-record'
            request = RunConfig.from_dict(
                {
                    'secret_env': ['CALCCHAIN_TEST_SECRET'],
                    'run': {
                        'executable': sys.executable,
                        'args': [
                            '-c',
                            'import os; print(os.environ["CALCCHAIN_TEST_SECRET"])',
                        ],
                    },
                },
            )

            result = ProcessRunner().run(layout, request)
            serialized = json.dumps(result.to_dict(), ensure_ascii=False)

            self.assertIn('CALCCHAIN_TEST_SECRET', result.secret_names)
            self.assertNotIn('do-not-record', serialized)
            self.assertEqual((layout.logs_dir / 'stdout.txt').read_text(encoding='utf-8').strip(), '[secret]')


if __name__ == '__main__':
    unittest.main()
