from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
import os
import signal
import subprocess

from ..common.errors import RunExecutionError
from ..common.logging import write_process_stream, write_stdin_text
from ..common.status import RunStatus, RuntimeStatus, write_runtime_status
from ..secrets import NoSecretsResolver, SecretsResolver
from ..utils.json import write_json
from ..workspace.layout import JobLayout
from ..workspace.snapshot import Snapshot, create_snapshot
from .config import RunConfig


class CancelToken:
    def is_cancelled(self) -> bool:
        return False


@dataclass(frozen=True)
class RunResult:
    command: list[str]
    cwd: str
    timeout_seconds: int | None
    encoding: str
    env: dict[str, str]
    secret_names: list[str]
    stdin: dict[str, str]
    stdout_log: str | None
    stderr_log: str | None
    status: RunStatus
    return_code: int | None
    started_at: str
    finished_at: str
    post_run_snapshot: Snapshot
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            'command': list(self.command),
            'cwd': self.cwd,
            'timeout_seconds': self.timeout_seconds,
            'encoding': self.encoding,
            'env': {
                'values': dict(self.env),
                'secrets': list(self.secret_names),
            },
            'stdin': dict(self.stdin),
            'stdout_log': self.stdout_log,
            'stderr_log': self.stderr_log,
            'status': self.status.value,
            'return_code': self.return_code,
            'started_at': self.started_at,
            'finished_at': self.finished_at,
            'post_run_snapshot': self.post_run_snapshot.to_dict(),
            'warnings': list(self.warnings),
        }


class ProcessRunner:
    def __init__(self, secrets_resolver: SecretsResolver | None = None):
        self._secrets_resolver = secrets_resolver or NoSecretsResolver()

    def run(
        self,
        layout: JobLayout,
        request: RunConfig,
        *,
        cancel_token: CancelToken | None = None,
    ) -> RunResult:
        command = [request.executable, *request.args]
        cwd_path = _resolve_work_cwd(layout.work_dir, request.cwd)
        env = os.environ.copy()
        public_env = dict(request.env.public)
        secret_env = _resolve_secret_env(self._secrets_resolver, request.env.secrets)
        env.update(public_env)
        env.update(secret_env)
        secret_names = list(secret_env)
        secret_values = [value for value in secret_env.values() if value]
        recorded_env = public_env
        stdin_payload, stdin_info = _stdin_payload(layout, request)
        started_at = datetime.now(timezone.utc)

        try:
            process = subprocess.Popen(
                command,
                cwd=str(cwd_path),
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                **_process_isolation_kwargs(),
            )
        except OSError as err:
            raise RunExecutionError(f'failed to start run command: {err.__class__.__name__}') from err

        stdout = b''
        stderr = b''
        try:
            stdout, stderr = _communicate(
                process,
                stdin_payload,
                timeout_seconds=request.timeout_seconds,
                cancel_token=cancel_token,
                started_at=started_at,
            )
        except _RunTimedOut:
            _terminate_process(process)
            stdout, stderr = _communicate_after_termination(process, stdout, stderr)
            status = RunStatus.TIMEOUT
        except _RunCancelled:
            _terminate_process(process)
            stdout, stderr = _communicate_after_termination(process, stdout, stderr)
            status = RunStatus.CANCELLED
        else:
            status = RunStatus.SUCCEEDED if process.returncode == 0 else RunStatus.FAILED

        stdout_log = _relative_log_path(
            layout,
            write_process_stream(
                layout.logs_dir,
                'stdout.txt',
                stdout,
                request.encoding,
                secret_values=secret_values,
            ),
        )
        stderr_log = _relative_log_path(
            layout,
            write_process_stream(
                layout.logs_dir,
                'stderr.txt',
                stderr,
                request.encoding,
                secret_values=secret_values,
            ),
        )
        post_run_snapshot = create_snapshot(layout.work_dir)
        write_json(post_run_snapshot.to_dict(), layout.snapshots_dir / 'post_run_snapshot.json')
        finished_at = datetime.now(timezone.utc)
        runtime_status = RuntimeStatus.from_run_status(status)
        write_runtime_status(layout.service_dir / 'runtime_status.json', runtime_status)

        return RunResult(
            command=command,
            cwd=cwd_path.relative_to(layout.work_dir).as_posix() or '.',
            timeout_seconds=request.timeout_seconds,
            encoding=request.encoding,
            env=recorded_env,
            secret_names=secret_names,
            stdin=stdin_info,
            stdout_log=stdout_log,
            stderr_log=stderr_log,
            status=status,
            return_code=process.returncode,
            started_at=started_at.isoformat(),
            finished_at=finished_at.isoformat(),
            post_run_snapshot=post_run_snapshot,
        )


class _RunTimedOut(Exception):
    pass


class _RunCancelled(Exception):
    pass


def _communicate(
    process: subprocess.Popen,
    stdin_payload: bytes | None,
    *,
    timeout_seconds: int | None,
    cancel_token: CancelToken | None,
    started_at: datetime,
) -> tuple[bytes, bytes]:
    deadline = None
    if timeout_seconds is not None:
        deadline = started_at + timedelta(seconds=timeout_seconds)
    input_payload = stdin_payload
    while True:
        if cancel_token is not None and cancel_token.is_cancelled():
            raise _RunCancelled
        timeout = 0.1
        if deadline is not None:
            remaining = (deadline - datetime.now(timezone.utc)).total_seconds()
            if remaining <= 0:
                raise _RunTimedOut
            timeout = min(timeout, remaining)
        try:
            if input_payload is None:
                return process.communicate(timeout=timeout)
            result = process.communicate(input=input_payload, timeout=timeout)
            input_payload = None
            return result
        except subprocess.TimeoutExpired:
            input_payload = None


def _process_isolation_kwargs() -> dict[str, object]:
    if os.name == 'nt':
        return {'creationflags': getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)}
    return {'start_new_session': True}


def _terminate_process(process: subprocess.Popen) -> None:
    if os.name == 'nt':
        subprocess.run(
            ['taskkill', '/PID', str(process.pid), '/T', '/F'],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            check=False,
        )
        if process.poll() is None:
            process.kill()
        return

    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except OSError:
        process.terminate()
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        except OSError:
            process.kill()


def _communicate_after_termination(
    process: subprocess.Popen,
    stdout: bytes = b'',
    stderr: bytes = b'',
) -> tuple[bytes, bytes]:
    try:
        remaining_stdout, remaining_stderr = process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        if process.poll() is None:
            process.kill()
        remaining_stdout, remaining_stderr = process.communicate()
    return stdout + (remaining_stdout or b''), stderr + (remaining_stderr or b'')


def _stdin_payload(layout: JobLayout, request: RunConfig) -> tuple[bytes | None, dict[str, str]]:
    if request.stdin_mode == 'script':
        log_path = write_stdin_text(layout.logs_dir, request.stdin_text)
        return request.stdin_text.encode(request.encoding), {
            'mode': request.stdin_mode,
            'log': _relative_log_path(layout, log_path),
        }
    return None, {'mode': request.stdin_mode}


def _resolve_secret_env(
    secrets_resolver: SecretsResolver,
    refs: dict[str, str],
) -> dict[str, str]:
    return {
        name: secrets_resolver.resolve(secret_key, context={'kind': 'run.env', 'name': name})
        for name, secret_key in refs.items()
    }


def _resolve_work_cwd(work_dir: Path, cwd: str) -> Path:
    normalized = cwd.replace('\\', '/')
    if normalized.startswith('/') or _has_windows_drive(normalized):
        raise RunExecutionError(f'run cwd must be relative to work dir: {cwd}')
    path = PurePosixPath(normalized)
    if '..' in path.parts:
        raise RunExecutionError(f'run cwd must not contain path traversal: {cwd}')
    target = work_dir.joinpath(*(() if path.as_posix() == '.' else path.parts))
    work_resolved = work_dir.resolve(strict=False)
    try:
        target.resolve(strict=False).relative_to(work_resolved)
    except ValueError as err:
        raise RunExecutionError(f'run cwd escapes work dir: {cwd}') from err
    if not target.is_dir():
        raise RunExecutionError(f'run cwd does not exist: {cwd}')
    return target


def _relative_log_path(layout: JobLayout, path: Path) -> str:
    path = Path(path)
    logs_resolved = layout.logs_dir.resolve(strict=False)
    try:
        path.resolve(strict=False).relative_to(logs_resolved)
    except ValueError as err:
        raise RunExecutionError(f'log path escapes logs dir: {path}') from err
    return path.relative_to(layout.job_dir).as_posix()


def _has_windows_drive(value: str) -> bool:
    return len(value) >= 2 and value[1] == ':' and value[0].isalpha()
