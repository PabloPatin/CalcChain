from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path, PurePosixPath
import signal
import subprocess

from calcchain_core.common.errors import RunExecutionError
from calcchain_core.workspace.layout import JobLayout
from calcchain_core.common.logging import write_process_stream, write_stdin_text
from calcchain_core.models import JobStatus, RunConfig, RunStatus
from calcchain_core.workspace.snapshot import Snapshot, create_snapshot
from calcchain_core.common.status import RuntimeStatus, write_runtime_status


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
        env.update(request.env)
        secret_names = list(request.secret_env)
        secret_values = [env[name] for name in secret_names if env.get(name)]
        recorded_env = {name: value for name, value in request.env.items() if name not in set(secret_names)}
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
        containment = _ProcessContainment(process)
        stdout = b''
        stderr = b''
        status: RunStatus
        try:
            stdout, stderr = _communicate(
                process,
                stdin_payload,
                timeout_seconds=request.timeout_seconds,
                cancel_token=cancel_token,
                started_at=started_at,
            )
        except _RunTimedOut:
            containment.terminate()
            stdout, stderr = _communicate_after_termination(process)
            status = RunStatus.TIMEOUT
        except _RunCancelled:
            containment.terminate()
            stdout, stderr = _communicate_after_termination(process)
            status = RunStatus.CANCELLED
        else:
            status = RunStatus.SUCCEEDED if process.returncode == 0 else RunStatus.FAILED
        finally:
            containment.close()

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
        _write_json(layout.snapshots_dir / 'post_run_snapshot.json', post_run_snapshot.to_dict())
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


class _ProcessContainment:
    def __init__(self, process: subprocess.Popen) -> None:
        self._process = process
        self._windows_job = _WindowsJob(process) if os.name == 'nt' else None

    def terminate(self) -> None:
        if self._windows_job is not None and self._windows_job.terminate():
            return
        if os.name == 'nt':
            _terminate_windows_process_tree(self._process)
            return
        _terminate_posix_process_group(self._process)

    def close(self) -> None:
        if self._windows_job is not None:
            self._windows_job.close()


def _terminate_windows_process_tree(process: subprocess.Popen) -> None:
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


def _terminate_posix_process_group(process: subprocess.Popen) -> None:
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


def _communicate_after_termination(process: subprocess.Popen) -> tuple[bytes, bytes]:
    _close_process_pipes(process)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if process.poll() is None:
            process.kill()
    return b'', b''


def _close_process_pipes(process: subprocess.Popen) -> None:
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is not None:
            stream.close()


class _WindowsJob:
    def __init__(self, process: subprocess.Popen) -> None:
        self._handle = None
        self._kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        self._configure_api()
        handle = self._kernel32.CreateJobObjectW(None, None)
        if not handle:
            return
        self._handle = handle
        limits = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self._kernel32.SetInformationJobObject(
            self._handle,
            _JobObjectExtendedLimitInformation,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            self.close()
            return
        if not self._kernel32.AssignProcessToJobObject(self._handle, int(process._handle)):
            self.close()

    def terminate(self) -> bool:
        if self._handle is None:
            return False
        handle = self._handle
        self._handle = None
        self._kernel32.CloseHandle(handle)
        return True

    def close(self) -> None:
        if self._handle is not None:
            handle = self._handle
            self._handle = None
            self._kernel32.CloseHandle(handle)

    def _configure_api(self) -> None:
        self._kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        self._kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        self._kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        ]
        self._kernel32.SetInformationJobObject.restype = wintypes.BOOL
        self._kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self._kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel32.CloseHandle.restype = wintypes.BOOL


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ('PerProcessUserTimeLimit', ctypes.c_int64),
        ('PerJobUserTimeLimit', ctypes.c_int64),
        ('LimitFlags', wintypes.DWORD),
        ('MinimumWorkingSetSize', ctypes.c_size_t),
        ('MaximumWorkingSetSize', ctypes.c_size_t),
        ('ActiveProcessLimit', wintypes.DWORD),
        ('Affinity', ctypes.c_size_t),
        ('PriorityClass', wintypes.DWORD),
        ('SchedulingClass', wintypes.DWORD),
    ]


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ('ReadOperationCount', ctypes.c_uint64),
        ('WriteOperationCount', ctypes.c_uint64),
        ('OtherOperationCount', ctypes.c_uint64),
        ('ReadTransferCount', ctypes.c_uint64),
        ('WriteTransferCount', ctypes.c_uint64),
        ('OtherTransferCount', ctypes.c_uint64),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ('BasicLimitInformation', _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ('IoInfo', _IO_COUNTERS),
        ('ProcessMemoryLimit', ctypes.c_size_t),
        ('JobMemoryLimit', ctypes.c_size_t),
        ('PeakProcessMemoryUsed', ctypes.c_size_t),
        ('PeakJobMemoryUsed', ctypes.c_size_t),
    ]


_JobObjectExtendedLimitInformation = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000


def _stdin_payload(layout: JobLayout, request: RunConfig) -> tuple[bytes | None, dict[str, str]]:
    if request.stdin_mode == 'script':
        log_path = write_stdin_text(layout.logs_dir, request.stdin_text)
        return request.stdin_text.encode(request.encoding), {
            'mode': request.stdin_mode,
            'log': _relative_log_path(layout, log_path),
        }
    return None, {'mode': request.stdin_mode}


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


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def _has_windows_drive(value: str) -> bool:
    return len(value) >= 2 and value[1] == ':' and value[0].isalpha()
