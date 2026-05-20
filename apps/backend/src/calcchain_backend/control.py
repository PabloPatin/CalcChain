from __future__ import annotations

import json
import os
import secrets
import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from calcchain_backend.security.pairing import PairingManager


CONTROL_DIR = Path.home() / ".calcchain"
CONTROL_FILE = CONTROL_DIR / "backend-control.json"


@dataclass(slots=True)
class ControlClientConfig:
    host: str
    port: int
    secret: str
    pid: int


class ControlServer:
    """
    Local-only control socket for trusted CLI operations.

    It is bound to 127.0.0.1 and protected by a random per-process secret stored
    in a user-only control file. This is intentionally not exposed through the
    public LAN HTTP API.
    """

    def __init__(self, pairing: PairingManager) -> None:
        self._pairing = pairing
        self._secret = secrets.token_urlsafe(32)
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind(("127.0.0.1", 0))
        self._socket.listen(5)
        self._host, self._port = self._socket.getsockname()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._stopped = threading.Event()

    def start(self) -> None:
        self._write_control_file()
        self._thread.start()

    def close(self) -> None:
        self._stopped.set()
        try:
            self._socket.close()
        finally:
            try:
                CONTROL_FILE.unlink(missing_ok=True)
            except OSError:
                pass

    def _write_control_file(self) -> None:
        CONTROL_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "host": self._host,
            "port": self._port,
            "secret": self._secret,
            "pid": os.getpid(),
            "created_at": time.time(),
        }
        CONTROL_FILE.write_text(json.dumps(payload), encoding="utf-8")
        try:
            os.chmod(CONTROL_FILE, 0o600)
        except OSError:
            # chmod is best-effort on Windows.
            pass

    def _serve(self) -> None:
        while not self._stopped.is_set():
            try:
                connection, _address = self._socket.accept()
            except OSError:
                return

            with connection:
                self._handle_connection(connection)

    def _handle_connection(self, connection: socket.socket) -> None:
        try:
            raw = connection.recv(8192)
            request = json.loads(raw.decode("utf-8"))
            response = self._dispatch(request)
        except Exception as exc:  # noqa: BLE001 - control socket should always reply.
            response = {"ok": False, "error": str(exc)}

        connection.sendall(json.dumps(response).encode("utf-8"))

    def _dispatch(self, request: dict[str, Any]) -> dict[str, Any]:
        if request.get("secret") != self._secret:
            return {"ok": False, "error": "Unauthorized control request"}

        command = request.get("command")
        if command == "generate_pairing_code":
            code = self._pairing.generate()
            return {"ok": True, "code": code}

        return {"ok": False, "error": f"Unknown command: {command}"}


def read_control_config() -> ControlClientConfig:
    if not CONTROL_FILE.exists():
        raise RuntimeError(
            "CalcChain backend control socket was not found. "
            "Start the backend with `calcchain-backend serve --lan` first."
        )

    payload = json.loads(CONTROL_FILE.read_text(encoding="utf-8"))
    return ControlClientConfig(
        host=str(payload["host"]),
        port=int(payload["port"]),
        secret=str(payload["secret"]),
        pid=int(payload["pid"]),
    )


def request_new_pairing_code() -> str:
    config = read_control_config()
    request = {
        "secret": config.secret,
        "command": "generate_pairing_code",
    }

    with socket.create_connection((config.host, config.port), timeout=3) as connection:
        connection.sendall(json.dumps(request).encode("utf-8"))
        raw = connection.recv(8192)

    response = json.loads(raw.decode("utf-8"))
    if not response.get("ok"):
        raise RuntimeError(response.get("error", "Control request failed"))

    return str(response["code"])
