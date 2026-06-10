from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("pydantic")
pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from calcchain_backend.app import create_app
from calcchain_backend.services.secret_service import session_key_from_token_or_header
from calcchain_backend.settings import BackendSettings, create_settings
from calcchain_core.capabilities import CapabilityKey, CapabilityOwner, CapabilityRecord, RuntimeCapabilities


SESSION_HEADERS = {"x-calcchain-session-id": "backend-api-test"}


def test_api_compile_secrets_run_and_artifacts(tmp_path):
    code_dir = tmp_path / "code"
    code_dir.mkdir()
    (code_dir / "solver.py").write_text(
        "\n".join(
            [
                "import os",
                "from pathlib import Path",
                "token = os.environ['CALCCHAIN_TOKEN']",
                "Path('result.txt').write_text('token=' + token, encoding='utf-8')",
                "print('api-run')",
            ],
        ),
        encoding="utf-8",
    )
    with _client(tmp_path) as client:
        graph = {
            "name": "api secret env",
            "nodes": [
                {"id": "code", "type": "source.local.code", "config": {"path": str(code_dir)}},
                {
                    "id": "calc",
                    "type": "calculation",
                    "config": {
                        "command": "required by catalog",
                        "executable": sys.executable,
                        "args": ["solver.py"],
                    },
                },
                {"id": "token_env", "type": "env.secret", "config": {"name": "CALCCHAIN_TOKEN"}},
            ],
            "edges": [
                _edge("code", "output", "calc", "code"),
                _edge("token_env", "output", "calc", "env"),
            ],
        }
        requirements_response = client.post(
            "/api/secrets/requirements",
            headers=SESSION_HEADERS,
            json={"graph": graph},
        )
        assert requirements_response.status_code == 200, requirements_response.text
        requirements = requirements_response.json()["requirements"]
        assert len(requirements) == 1
        assert requirements[0]["kind"] == "env-secret"

        compiled = _compile_graph(
            client,
            graph,
        )

        secret_response = client.post(
            "/api/secrets/session",
            headers=SESSION_HEADERS,
            json={
                "secret_ref": requirements[0]["secret_ref"],
                "kind": "run-env",
                "ttl_seconds": 60,
                "values": {"value": "secret-from-api"},
            },
        )
        assert secret_response.status_code == 200, secret_response.text

        run_id = _start_run(client, compiled)
        details = _wait_run(client, run_id)

        assert details["status"] == "success", details
        artifacts = _artifact_names(client, run_id)
        assert {"build.lock.toml", "manifest.json", "run.toml", "stdout.txt"}.issubset(artifacts)
        assert _preview_text(client, run_id, "stdout.txt").strip() == "api-run"

        manifest = _preview_json(client, run_id, "manifest.json")
        assert manifest["run"]["status"] == "Succeeded"
        assert manifest["run"]["file_groups"]["outputs"] == ["result.txt"]


def test_api_runs_accepts_compile_response_without_frontend_filtering(tmp_path):
    code_dir = tmp_path / "code"
    code_dir.mkdir()
    (code_dir / "solver.py").write_text("print('whole-compile-response')\n", encoding="utf-8")

    with _client(tmp_path) as client:
        compiled = _compile_graph(
            client,
            {
                "name": "compile response run",
                "nodes": [
                    {"id": "code", "type": "source.local.code", "config": {"path": str(code_dir)}},
                    {
                        "id": "calc",
                        "type": "calculation",
                        "config": {
                            "command": "required by catalog",
                            "executable": sys.executable,
                            "args": ["solver.py"],
                        },
                    },
                ],
                "edges": [_edge("code", "output", "calc", "code")],
            },
        )
        assert {"valid", "diagnostics", "warnings"}.issubset(compiled)

        response = client.post("/api/runs", headers=SESSION_HEADERS, json={**compiled, "run_options": {"name": "whole"}})
        assert response.status_code == 201, response.text
        details = _wait_run(client, response.json()["run_id"])

        assert details["status"] == "success", details
        assert _preview_text(client, response.json()["run_id"], "stdout.txt").strip() == "whole-compile-response"


def test_api_runs_rejects_invalid_compile_response(tmp_path):
    with _client(tmp_path) as client:
        response = client.post(
            "/api/runs",
            headers=SESSION_HEADERS,
            json={
                "valid": False,
                "build_config": {"build": {"name": "invalid"}, "code": {"source": {"type": "local", "path": "missing"}}},
                "diagnostics": [{"code": "compile_error", "message": "bad graph"}],
            },
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Compile response is not valid"


def test_lan_auth_pairing_flow_protects_api(tmp_path):
    app = create_app(create_settings(tmp_path, mode="lan"))
    with TestClient(app) as client:
        state = client.get("/api/auth/state")
        assert state.status_code == 200, state.text
        assert state.json() == {"auth_required": True, "authenticated": False}

        blocked = client.get("/api/catalog")
        assert blocked.status_code == 401

        code = app.state.pairing.generate()
        pair = client.post("/api/auth/pair", json={"code": code})
        assert pair.status_code == 200, pair.text
        token = pair.json()["token"]
        auth_headers = {"Authorization": f"Bearer {token}"}

        authenticated_state = client.get("/api/auth/state", headers=auth_headers)
        assert authenticated_state.json() == {"auth_required": True, "authenticated": True}

        allowed = client.get("/api/catalog", headers=auth_headers)
        assert allowed.status_code == 200, allowed.text

        client.post(
            "/api/secrets/session",
            headers=auth_headers,
            json={
                "secret_ref": "secret:auth:logout",
                "kind": "logout-test",
                "ttl_seconds": 60,
                "values": {"value": "logout-secret"},
            },
        ).raise_for_status()
        session_key = session_key_from_token_or_header(token)
        assert app.state.secret_service.list_session_secrets(session_key).items

        logout = client.post("/api/auth/logout", headers=auth_headers)
        assert logout.status_code == 204
        assert app.state.secret_service.list_session_secrets(session_key).items == []
        assert client.get("/api/catalog", headers=auth_headers).status_code == 401


def test_run_logs_events_errors_and_metadata_redact_session_secrets(tmp_path, monkeypatch):
    with _client(tmp_path) as client:
        client.post(
            "/api/secrets/session",
            headers=SESSION_HEADERS,
            json={
                "secret_ref": "secret:redaction",
                "kind": "redaction-test",
                "ttl_seconds": 60,
                "values": {"value": "redaction-secret"},
            },
        ).raise_for_status()

        def raise_secret(_run, _job_dir):
            raise RuntimeError("backend error leaked redaction-secret")

        monkeypatch.setattr(client.app.state.run_service, "_write_core_configs", raise_secret)
        run_id = _start_run(
            client,
            {
                "build_config": {
                    "schema_version": "1.0",
                    "build": {"name": "redaction"},
                    "code": {"source": {"type": "local", "path": str(tmp_path)}},
                },
                "run_options": {"name": "redaction"},
            },
        )
        details = _wait_run(client, run_id)

        assert details["status"] == "failed"
        assert details["error"] == "backend error leaked [redacted]"
        assert "redaction-secret" not in str(details)

        logs = client.get(f"/api/runs/{run_id}/logs").json()["items"]
        events = [event.data for event in client.app.state.run_service._runs[run_id].events]
        run_metadata = _preview_json(client, run_id, "run.json")

        assert "redaction-secret" not in str(logs)
        assert "redaction-secret" not in str(events)
        assert "redaction-secret" not in str(run_metadata)
        assert "[redacted]" in str(logs)
        assert "[redacted]" in str(events)
        assert "[redacted]" in str(run_metadata)


def test_api_publish_uses_rules_manifest_and_target_credentials(tmp_path):
    code_dir = tmp_path / "code"
    publish_service = tmp_path / "publish_service"
    publish_outputs = tmp_path / "publish_outputs"
    code_dir.mkdir()
    (code_dir / "solver.py").write_text(
        "from pathlib import Path\nPath('result.txt').write_text('published', encoding='utf-8')\n",
        encoding="utf-8",
    )
    with _client(tmp_path) as client:
        _install_runtime(client, _credentialed_target_runtime())

        client.post(
            "/api/secrets/session",
            headers=SESSION_HEADERS,
            json={
                "secret_ref": "secret:target:publish",
                "kind": "target-password",
                "ttl_seconds": 60,
                "values": {"password": "target-secret"},
            },
        ).raise_for_status()

        run_id = _start_run(
            client,
            {
                "build_config": {
                    "schema_version": "1.0",
                    "build": {"name": "api publish"},
                    "code": {"name": "code", "version": "", "source": {"type": "local", "path": str(code_dir)}},
                },
                "run_config": {
                    "schema_version": "1.0",
                    "run": {
                        "executable": sys.executable,
                        "args": ["solver.py"],
                        "cwd": ".",
                        "encoding": "utf-8",
                        "stdin_mode": "none",
                    },
                },
                "publish_config": {
                    "schema_version": "1.0",
                    "publish": {"message": "publish from api test"},
                    "service_target": {"type": "local", "path": str(publish_service)},
                    "targets": [
                        {
                            "name": "secured_outputs",
                            "type": "credentialed-local",
                            "path": str(publish_outputs),
                            "credentials": {"secrets": {"password": "secret:target:publish"}},
                            "rule_sets": ["outputs"],
                        },
                    ],
                },
                "rules_config": {
                    "schema_version": "1.0",
                    "rules_file": {},
                    "rule_sets": {
                        "outputs": {
                            "type": "output",
                            "status": "approved",
                            "ensure_all_files": True,
                            "rules": [{"source": r"result\.txt", "destination": "archive/result.txt"}],
                        },
                    },
                },
                "run_options": {"name": "api publish"},
            },
        )
        details = _wait_run(client, run_id)

        assert details["status"] == "success", details
        assert (publish_outputs / "archive" / "result.txt").read_text(encoding="utf-8") == "published"
        assert (publish_service / "manifest.json").is_file()
        assert (publish_service / "publish.lock.toml").is_file()

        manifest = _preview_json(client, run_id, "manifest.json")
        publication = manifest["publication"]
        assert publication["outputs"][0]["published_sources"]["archive/result.txt"]["type"] == "local"
        assert publication["service_target"] == {"type": "local", "path": str(publish_service)}


def test_api_real_svn_plugin_runtime_compile_and_run(tmp_path):
    if shutil.which("svnadmin") is None or shutil.which("svn") is None:
        pytest.skip("SVN CLI and svnadmin are required for real SVN plugin runtime test")

    repo_root = Path(__file__).resolve().parents[1]
    app = create_app(BackendSettings(project_root=repo_root, state_dir_name=str(tmp_path / "backend_state")))
    with TestClient(app) as client:
        runtime = client.post("/api/plugins/runtime/reload")
        assert runtime.status_code == 200, runtime.text
        runtime_data = runtime.json()
        assert runtime_data["active"], runtime_data
        assert {"namespace": "source", "id": "svn"} in runtime_data["capabilities"]

        svn_repo = _create_svn_repo(tmp_path)
        compiled = _compile_graph(
            client,
            {
                "name": "svn api",
                "nodes": [
                    {
                        "id": "code",
                        "type": "source.svn.code",
                        "config": {"location": svn_repo.as_uri(), "path": "trunk/code", "revision": "HEAD"},
                    },
                    {
                        "id": "calc",
                        "type": "calculation",
                        "config": {
                            "command": "required by catalog",
                            "executable": sys.executable,
                            "args": ["solver.py"],
                        },
                    },
                ],
                "edges": [_edge("code", "output", "calc", "code")],
            },
        )

        run_id = _start_run(client, compiled)
        details = _wait_run(client, run_id, timeout_seconds=15)

        assert details["status"] == "success", details
        assert _preview_text(client, run_id, "stdout.txt").strip() == "svn-run"


def _client(tmp_path: Path) -> TestClient:
    app = create_app(create_settings(tmp_path))
    return TestClient(app)


def _compile_graph(client: TestClient, graph: dict) -> dict:
    response = client.post("/api/graphs/compile", json={"graph": graph})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["valid"], data
    return data


def _start_run(client: TestClient, compiled_or_payload: dict) -> str:
    payload = {
        key: compiled_or_payload.get(key)
        for key in ("build_config", "run_config", "publish_config", "rules_config", "graph_config", "run_options")
        if key in compiled_or_payload
    }
    if "build_config" in payload and payload.get("run_options") is None:
        payload["run_options"] = {"name": payload.get("graph_config", {}).get("name", "api-run")}
    response = client.post("/api/runs", headers=SESSION_HEADERS, json=payload)
    assert response.status_code == 201, response.text
    return response.json()["run_id"]


def _wait_run(client: TestClient, run_id: str, *, timeout_seconds: float = 10) -> dict:
    deadline = time.monotonic() + timeout_seconds
    details = None
    while time.monotonic() < deadline:
        response = client.get(f"/api/runs/{run_id}")
        assert response.status_code == 200, response.text
        details = response.json()
        if details["status"] in {"success", "failed", "cancelled"}:
            return details
        time.sleep(0.05)
    pytest.fail(f"run {run_id} did not finish in {timeout_seconds}s, last details: {details}")


def _artifact_names(client: TestClient, run_id: str) -> set[str]:
    response = client.get(f"/api/runs/{run_id}/artifacts")
    assert response.status_code == 200, response.text
    return {item["name"] for item in response.json()["items"]}


def _preview_text(client: TestClient, run_id: str, artifact_id: str) -> str:
    response = client.get(f"/api/runs/{run_id}/artifacts/{artifact_id}/preview")
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["kind"] == "text", preview
    return preview["content"]


def _preview_json(client: TestClient, run_id: str, artifact_id: str) -> dict:
    response = client.get(f"/api/runs/{run_id}/artifacts/{artifact_id}/preview")
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["kind"] == "json", preview
    return preview["content"]


def _install_runtime(client: TestClient, runtime: RuntimeCapabilities) -> None:
    plugin_service = client.app.state.plugin_service
    plugin_service._runtime = runtime
    plugin_service._runtime_error = None
    plugin_service._runtime_diagnostics = []


def _credentialed_target_runtime() -> RuntimeCapabilities:
    key = CapabilityKey("target", "credentialed-local")
    return RuntimeCapabilities(
        capabilities={
            key: CapabilityRecord(
                key=key,
                adapter=_CredentialedLocalTargetAdapter(),
                owner=CapabilityOwner("backend-test"),
            ),
        },
        active_owner_ids=("backend-test",),
    )


class _CredentialedLocalTargetAdapter:
    def validate_config(self, ref, context) -> None:
        _target_path(ref)

    def resolve_lock_ref(self, ref, context) -> dict:
        self.validate_config(ref, context)
        return dict(ref)

    def validate_lock_ref(self, ref, context) -> None:
        self.validate_config(ref, context)

    def ensure_root(self, ref, context) -> dict:
        path = _target_path(ref)
        path.mkdir(parents=True, exist_ok=True)
        return dict(ref)

    def write_file(self, ref, relative_path: str, data: bytes, context) -> dict:
        if context.credentials.secrets.get("password") != "target-secret":
            raise RuntimeError("target secret was not resolved")
        root = _target_path(ref)
        destination = root.joinpath(*Path(relative_path).parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        return {"source": {"type": "local", "path": str(destination)}, "relative_path": relative_path}

    def is_versionable(self, ref, context) -> bool:
        return False


def _target_path(ref) -> Path:
    if ref.get("type") != "credentialed-local":
        raise RuntimeError("expected credentialed-local target")
    path = ref.get("path")
    if not isinstance(path, str) or not path:
        raise RuntimeError("credentialed-local target requires path")
    return Path(path)


def _create_svn_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "svn_repo"
    subprocess.run(["svnadmin", "create", str(repo)], check=True, capture_output=True, text=True)
    import_root = tmp_path / "svn_import"
    code_dir = import_root / "trunk" / "code"
    code_dir.mkdir(parents=True)
    (code_dir / "solver.py").write_text("print('svn-run')\n", encoding="utf-8")
    subprocess.run(
        ["svn", "import", str(import_root), repo.as_uri(), "-m", "initial import", "--non-interactive"],
        check=True,
        capture_output=True,
        text=True,
    )
    return repo


def _edge(source_node: str, source_port: str, target_node: str, target_port: str) -> dict:
    return {
        "id": f"{source_node}-{target_node}-{target_port}",
        "source": {"node_id": source_node, "port_id": source_port},
        "target": {"node_id": target_node, "port_id": target_port},
    }
