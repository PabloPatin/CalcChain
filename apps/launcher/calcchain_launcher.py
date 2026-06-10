from __future__ import annotations

import os
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from tkinter import BOTH, BOTTOM, CENTER, LEFT, TOP, BooleanVar, StringVar, Tk, messagebox, ttk


BACKEND_PORT = 8765
HTTPS_PORT = 8443
STARTUP_TIMEOUT_SECONDS = 40


@dataclass(frozen=True)
class RuntimePaths:
    app_root: Path
    python_exe: Path
    state_dir: Path
    projects_dir: Path
    plugin_root: Path
    static_dir: Path
    caddy_exe: Path
    caddyfile: Path
    caddy_storage: Path
    log_dir: Path


class CalcChainProcessManager:
    def __init__(self, paths: RuntimePaths) -> None:
        self.paths = paths
        self.backend: subprocess.Popen[bytes] | None = None
        self.caddy: subprocess.Popen[bytes] | None = None
        self.mode: str | None = None
        self.pairing_code: str | None = None
        self.lan_ip = resolve_lan_ip()

    @property
    def local_url(self) -> str:
        return f"http://127.0.0.1:{BACKEND_PORT}/"

    @property
    def lan_url(self) -> str:
        return f"https://{self.lan_ip}:{HTTPS_PORT}/"

    def start(self, mode: str) -> str | None:
        if self.is_running():
            raise RuntimeError("CalcChain is already running.")

        existing_mode = current_backend_mode(self.local_url)
        if existing_mode is not None:
            if existing_mode != mode:
                raise RuntimeError(
                    f"CalcChain is already running in {existing_mode.upper()} mode on port {BACKEND_PORT}. "
                    "Stop it before starting another mode."
                )
            self.mode = mode
            if mode == "local":
                webbrowser.open(self.local_url)
                return None
            self.pairing_code = self.generate_pairing_code()
            webbrowser.open(self.lan_url)
            return self.pairing_code

        ensure_runtime_dirs(self.paths)
        self.mode = mode
        self.pairing_code = None

        if mode == "local":
            self.backend = self._start_backend(local=True)
            wait_for_http_ok(f"{self.local_url}api/server/info", expected_mode="local")
            webbrowser.open(self.local_url)
            return None

        self.backend = self._start_backend(local=False)
        wait_for_http_ok(f"{self.local_url}api/server/info", expected_mode="lan")
        self.caddy = self._start_caddy()
        wait_for_https_ok(self.lan_url)
        self.pairing_code = self.generate_pairing_code()
        webbrowser.open(self.lan_url)
        return self.pairing_code

    def stop(self) -> None:
        for process in (self.caddy, self.backend):
            stop_process(process)
        stop_processes_on_ports((HTTPS_PORT, BACKEND_PORT))
        self.caddy = None
        self.backend = None
        self.mode = None
        self.pairing_code = None

    def is_running(self) -> bool:
        return process_running(self.backend) or process_running(self.caddy)

    def generate_pairing_code(self) -> str:
        if self.mode != "lan" or not process_running(self.backend):
            raise RuntimeError("LAN backend is not running.")

        result = subprocess.run(
            [str(self.paths.python_exe), "-m", "calcchain_backend.cli", "pair"],
            cwd=self.paths.app_root,
            env=self._backend_env(),
            capture_output=True,
            text=True,
            creationflags=creation_flags(),
            check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise RuntimeError(detail or "Could not generate pairing code.")
        code = result.stdout.strip().splitlines()[-1].strip()
        if not code:
            raise RuntimeError("Pairing code command returned an empty response.")
        self.pairing_code = code
        return code

    def _start_backend(self, *, local: bool) -> subprocess.Popen[bytes]:
        args = [
            str(self.paths.python_exe),
            "-m",
            "calcchain_backend.cli",
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            str(BACKEND_PORT),
            "--app-root",
            str(self.paths.app_root),
            "--state-dir",
            str(self.paths.state_dir),
            "--projects-dir",
            str(self.paths.projects_dir),
            "--plugin-root",
            str(self.paths.plugin_root),
            "--static-dir",
            str(self.paths.static_dir),
        ]
        if not local:
            args.extend(["--lan", "--lan-bind-local"])

        log_prefix = "backend-local" if local else "backend-lan"
        return open_hidden_process(
            args,
            cwd=self.paths.app_root,
            env=self._backend_env(),
            stdout_path=self.paths.log_dir / f"{log_prefix}.out.log",
            stderr_path=self.paths.log_dir / f"{log_prefix}.err.log",
        )

    def _start_caddy(self) -> subprocess.Popen[bytes]:
        if not self.paths.caddy_exe.is_file():
            raise RuntimeError(f"Caddy was not found: {self.paths.caddy_exe}")
        if not self.paths.caddyfile.is_file():
            raise RuntimeError(f"Caddyfile was not found: {self.paths.caddyfile}")

        env = os.environ.copy()
        env.update(
            {
                "CALCCHAIN_LAN_HOST": self.lan_ip,
                "CALCCHAIN_HTTPS_PORT": str(HTTPS_PORT),
                "CALCCHAIN_BACKEND_PORT": str(BACKEND_PORT),
                "CALCCHAIN_CADDY_STORAGE": str(self.paths.caddy_storage),
            }
        )
        return open_hidden_process(
            [
                str(self.paths.caddy_exe),
                "run",
                "--config",
                str(self.paths.caddyfile),
                "--adapter",
                "caddyfile",
            ],
            cwd=self.paths.app_root,
            env=env,
            stdout_path=self.paths.log_dir / "caddy.out.log",
            stderr_path=self.paths.log_dir / "caddy.err.log",
        )

    def _backend_env(self) -> dict[str, str]:
        env = os.environ.copy()
        dev_paths = [
            self.paths.app_root / "apps" / "backend" / "src",
            self.paths.app_root / "packages" / "core" / "src",
            self.paths.app_root / "packages" / "plugin_system" / "src",
        ]
        existing = env.get("PYTHONPATH")
        items = [str(path) for path in dev_paths if path.is_dir()]
        if existing:
            items.append(existing)
        if items:
            env["PYTHONPATH"] = os.pathsep.join(items)
        return env


class CalcChainLauncherApp:
    def __init__(self, root: Tk, manager: CalcChainProcessManager) -> None:
        self.root = root
        self.manager = manager
        self.mode = StringVar(value="local")
        self.running = BooleanVar(value=False)
        self.status = StringVar(value="Stopped")
        self.pairing = StringVar(value="")
        self.notice = StringVar(value="")

        root.title("CalcChain")
        root.geometry("360x430")
        root.minsize(340, 400)
        root.protocol("WM_DELETE_WINDOW", self.close)

        self._build_ui()

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=20)
        outer.pack(fill=BOTH, expand=True)

        mode_frame = ttk.Frame(outer)
        mode_frame.pack(side=TOP, pady=(0, 28))
        ttk.Radiobutton(mode_frame, text="Local", value="local", variable=self.mode, command=self._mode_changed).pack(
            side=LEFT, padx=8
        )
        ttk.Radiobutton(mode_frame, text="LAN", value="lan", variable=self.mode, command=self._mode_changed).pack(
            side=LEFT, padx=8
        )

        self.power_button = ttk.Button(outer, text="START", command=self.toggle)
        self.power_button.pack(anchor=CENTER, ipadx=56, ipady=42, pady=(8, 24))

        ttk.Label(outer, textvariable=self.status, anchor=CENTER).pack(fill=BOTH, pady=(0, 12))
        ttk.Label(outer, textvariable=self.pairing, anchor=CENTER, font=("Segoe UI", 14, "bold")).pack(fill=BOTH)
        ttk.Label(outer, textvariable=self.notice, anchor=CENTER).pack(fill=BOTH, pady=(8, 0))

        bottom = ttk.Frame(outer)
        bottom.pack(side=BOTTOM, fill=BOTH)
        self.pair_button = ttk.Button(bottom, text="Show pairing code", command=self.show_pairing_code)
        self.pair_button.pack(fill=BOTH)
        self._mode_changed()

    def _mode_changed(self) -> None:
        is_lan = self.mode.get() == "lan"
        state = "normal" if is_lan and self.running.get() else "disabled"
        self.pair_button.configure(state=state)

    def toggle(self) -> None:
        if self.running.get():
            self.stop()
            return
        self.start()

    def start(self) -> None:
        selected_mode = self.mode.get()
        self._set_busy(f"Starting {selected_mode.upper()}...")

        def worker() -> None:
            try:
                code = self.manager.start(selected_mode)
            except Exception as exc:  # noqa: BLE001 - UI should show any startup failure.
                self.root.after(0, lambda error=exc: self._startup_failed(error))
                return
            self.root.after(0, lambda: self._startup_finished(code))

        threading.Thread(target=worker, daemon=True).start()

    def stop(self) -> None:
        self._set_busy("Stopping...")

        def worker() -> None:
            self.manager.stop()
            self.root.after(0, self._stopped)

        threading.Thread(target=worker, daemon=True).start()

    def show_pairing_code(self) -> None:
        if self.mode.get() != "lan" or not self.running.get():
            return
        self._set_busy("Generating pairing code...")

        def worker() -> None:
            try:
                code = self.manager.generate_pairing_code()
            except Exception as exc:  # noqa: BLE001
                self.root.after(0, lambda error=exc: self._action_failed(error))
                return
            self.root.after(0, lambda: self._pairing_ready(code))

        threading.Thread(target=worker, daemon=True).start()

    def close(self) -> None:
        if self.running.get() and not messagebox.askyesno("CalcChain", "Stop CalcChain and close?"):
            return
        if self.running.get():
            self.manager.stop()
        self.root.destroy()

    def _set_busy(self, text: str) -> None:
        self.status.set(text)
        self.power_button.configure(state="disabled")
        self.pair_button.configure(state="disabled")

    def _startup_finished(self, code: str | None) -> None:
        self.running.set(True)
        self.power_button.configure(text="STOP", state="normal")
        if self.mode.get() == "lan":
            self.status.set(f"Running: {self.manager.lan_url}")
            self.pairing.set(f"Pairing code: {code}")
            if code is not None:
                self._copy_pairing_code(code)
        else:
            self.status.set(f"Running: {self.manager.local_url}")
            self.pairing.set("")
            self.notice.set("")
        self._mode_changed()

    def _startup_failed(self, exc: Exception) -> None:
        self.manager.stop()
        self.running.set(False)
        self.power_button.configure(text="START", state="normal")
        self.status.set("Stopped")
        self.pairing.set("")
        self.notice.set("")
        self._mode_changed()
        messagebox.showerror("CalcChain startup failed", str(exc))

    def _stopped(self) -> None:
        self.running.set(False)
        self.power_button.configure(text="START", state="normal")
        self.status.set("Stopped")
        self.pairing.set("")
        self.notice.set("")
        self._mode_changed()

    def _pairing_ready(self, code: str) -> None:
        self.power_button.configure(state="normal")
        self.status.set(f"Running: {self.manager.lan_url}")
        self.pairing.set(f"Pairing code: {code}")
        self._copy_pairing_code(code)
        self._mode_changed()

    def _action_failed(self, exc: Exception) -> None:
        self.power_button.configure(state="normal")
        self.status.set(f"Running: {self.manager.lan_url}")
        self._mode_changed()
        messagebox.showerror("CalcChain", str(exc))

    def _copy_pairing_code(self, code: str) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(code)
        self.root.update()
        self.notice.set("Код скопирован в буфер обмена.")


def discover_paths() -> RuntimePaths:
    app_root = discover_app_root()
    state_dir = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "CalcChain"
    projects_dir = Path.home() / "Documents" / "CalcChainProjects"
    python_exe = discover_python(app_root)
    return RuntimePaths(
        app_root=app_root,
        python_exe=python_exe,
        state_dir=state_dir,
        projects_dir=projects_dir,
        plugin_root=app_root / "plugins",
        static_dir=app_root / "web",
        caddy_exe=app_root / "caddy" / "caddy.exe",
        caddyfile=app_root / "caddy" / "Caddyfile.lan",
        caddy_storage=state_dir / "caddy",
        log_dir=state_dir / "logs",
    )


def discover_app_root() -> Path:
    override = os.environ.get("CALCCHAIN_APP_ROOT")
    if override:
        return Path(override).resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def discover_python(app_root: Path) -> Path:
    packaged = app_root / "python" / "python.exe"
    if packaged.is_file():
        return packaged
    dev_venv = app_root / ".venv" / "Scripts" / "python.exe"
    if dev_venv.is_file():
        return dev_venv
    return Path(sys.executable).resolve()


def ensure_runtime_dirs(paths: RuntimePaths) -> None:
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    paths.projects_dir.mkdir(parents=True, exist_ok=True)
    paths.caddy_storage.mkdir(parents=True, exist_ok=True)
    paths.log_dir.mkdir(parents=True, exist_ok=True)


def open_hidden_process(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    stdout_path: Path,
    stderr_path: Path,
) -> subprocess.Popen[bytes]:
    stdout = stdout_path.open("ab")
    stderr = stderr_path.open("ab")
    return subprocess.Popen(
        args,
        cwd=cwd,
        env=env,
        stdout=stdout,
        stderr=stderr,
        creationflags=creation_flags(),
    )


def creation_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def process_running(process: subprocess.Popen[bytes] | None) -> bool:
    return process is not None and process.poll() is None


def stop_process(process: subprocess.Popen[bytes] | None) -> None:
    if not process_running(process):
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def stop_processes_on_ports(ports: tuple[int, ...]) -> None:
    if os.name != "nt":
        return
    port_list = ",".join(str(port) for port in ports)
    subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            (
                f"foreach ($port in @({port_list})) {{ "
                "Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | "
                "Select-Object -ExpandProperty OwningProcess -Unique | "
                "Where-Object { $_ -gt 0 } | "
                "ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue } "
                "}"
            ),
        ],
        capture_output=True,
        creationflags=creation_flags(),
        check=False,
    )


def wait_for_http_ok(url: str, *, expected_mode: str) -> None:
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                body = response.read().decode("utf-8", errors="replace")
            if f'"mode":"{expected_mode}"' in body or f'"mode": "{expected_mode}"' in body:
                return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        time.sleep(1)
    raise RuntimeError(f"Backend did not start in {expected_mode} mode: {last_error}")


def current_backend_mode(base_url: str) -> str | None:
    try:
        with urllib.request.urlopen(f"{base_url}api/server/info", timeout=1) as response:
            body = response.read().decode("utf-8", errors="replace")
    except Exception:
        return None
    if '"mode":"local"' in body or '"mode": "local"' in body:
        return "local"
    if '"mode":"lan"' in body or '"mode": "lan"' in body:
        return "lan"
    return "unknown"


def wait_for_https_ok(url: str) -> None:
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    context = ssl._create_unverified_context()
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1, context=context) as response:
                if response.status == 200:
                    return
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                return
            last_error = exc
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        time.sleep(1)
    raise RuntimeError(f"HTTPS proxy did not start: {last_error}")


def resolve_lan_ip() -> str:
    override = os.environ.get("CALCCHAIN_LAN_IP")
    if override:
        return override
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 65530))
        ip = sock.getsockname()[0]
        if not ip.startswith(("127.", "169.254.")):
            return ip
    except OSError:
        pass
    finally:
        sock.close()

    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = item[4][0]
            if not ip.startswith(("127.", "169.254.")):
                return ip
    except OSError:
        pass
    return "127.0.0.1"


def main() -> None:
    root = Tk()
    style = ttk.Style(root)
    if "vista" in style.theme_names():
        style.theme_use("vista")
    CalcChainLauncherApp(root, CalcChainProcessManager(discover_paths()))
    root.mainloop()


if __name__ == "__main__":
    main()
