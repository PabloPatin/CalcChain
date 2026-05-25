from pathlib import Path
import asyncio
import sys

import pytest

pytest.importorskip("pydantic")

from calcchain_backend.schemas.graph import GraphDocument, GraphEdge, GraphEdgeEndpoint, GraphNode
from calcchain_backend.services.artifact_service import ArtifactService
from calcchain_backend.services.catalog_service import CatalogService
from calcchain_backend.services.graph_service import GraphService
from calcchain_backend.services.plugin_service import PluginService
from calcchain_backend.services.run_service import RunService
from calcchain_backend.settings import create_settings
from calcchain_core.build import BuildConfig
from calcchain_core.secrets import RuntimeSecretsResolver, SecretPersistencePolicy
from calcchain_core.publish import PublishConfig
from calcchain_core.rules import RulesFile
from calcchain_core.run import RunConfig

from calcchain_backend.services.secret_service import SecretService, session_key_from_token_or_header
from calcchain_backend.services.secrets_adapter import runtime_with_backend_secrets


def test_graph_compile_returns_core_build_and_run_configs():
    result = _service().compile(
        GraphDocument(
            name="case",
            nodes=[
                GraphNode(id="code", type="source.local.code", config={"path": "code"}),
                GraphNode(id="data", type="source.local.input", config={"path": "data"}),
                GraphNode(id="calc", type="calculation", config={"command": "python solver.py"}),
            ],
            edges=[
                _edge("code", "output", "calc", "code"),
                _edge("data", "output", "calc", "input"),
            ],
        ),
    )

    assert result.valid
    assert result.build_config == {
        "schema_version": "1.0",
        "build": {"name": "case"},
        "code": {"name": "code", "version": "", "source": {"type": "local", "path": "code"}},
        "inputs": [{"name": "data", "source": {"type": "local", "path": "data"}}],
    }
    assert result.run_config["run"]["executable"] == "python"
    assert result.run_config["run"]["args"] == ["solver.py"]
    assert result.graph_config["kind"] == "calcchain.graph_config"

    BuildConfig.from_dict(result.build_config)
    RunConfig.from_dict(result.run_config)


def test_graph_compile_strips_secret_values_and_uses_secret_refs():
    result = _service().compile(
        GraphDocument(
            name="secure",
            nodes=[
                GraphNode(id="auth", type="auth.login-password", config={"username": "user", "password": "plain"}),
                GraphNode(id="code", type="source.svn.code", config={"location": "svn://repo", "path": "/code"}),
                GraphNode(id="calc", type="calculation", config={"command": "solver.exe"}),
            ],
            edges=[
                _edge("auth", "auth", "code", "auth"),
                _edge("code", "output", "calc", "code"),
            ],
        ),
    )

    source = result.build_config["code"]["source"]
    secret_ref = source["credentials"]["secrets"]["password"]

    assert result.valid
    assert source["credentials"]["public"] == {"username": "user"}
    assert secret_ref.startswith("secret:graph:")
    assert result.graph_config["nodes"][0]["config"] == {"username": "user", "credential_ref": secret_ref}
    assert "plain" not in str(result.model_dump(mode="json"))


def test_graph_compile_returns_publish_and_rules_configs_for_targets():
    result = _service().compile(
        GraphDocument(
            name="publish",
            nodes=[
                GraphNode(id="code", type="source.local.code", config={"path": "code"}),
                GraphNode(id="calc", type="calculation", config={"command": "solver.exe"}),
                GraphNode(id="artifact", type="artifact.output", config={}),
                GraphNode(id="target", type="target.local", config={"path": "out"}),
            ],
            edges=[
                _edge("code", "output", "calc", "code"),
                _edge("calc", "output", "artifact", "source"),
                _edge("artifact", "artifact", "target", "artifact"),
            ],
        ),
        {"service_target_path": "service"},
    )

    assert result.valid
    assert result.publish_config["service_target"] == {"type": "local", "path": "service"}
    assert result.publish_config["targets"][0]["rule_sets"] == ["outputs"]
    assert result.rules_config["rule_sets"]["outputs"]["type"] == "output"

    PublishConfig.from_dict(result.publish_config)
    RulesFile.from_dict(result.rules_config)


def test_backend_secret_service_is_core_secrets_adapter():
    service = SecretService()
    session_key = session_key_from_token_or_header("session")
    service.put_session_secret(
        session_key,
        "secret:graph:abc",
        "login-password",
        {"password": "plain-secret"},
        ttl_seconds=60,
    )
    runtime = runtime_with_backend_secrets(service, session_key)
    resolver = RuntimeSecretsResolver.from_runtime(
        runtime,
        policy=SecretPersistencePolicy(allow_memory=False, allow_store=False),
    )

    value = resolver.resolve(
        "secret:graph:abc",
        context={"kind": "source.credentials", "name": "password"},
    )

    assert value == "plain-secret"


def test_plugin_service_runtime_empty_and_combined_with_backend_secrets(tmp_path):
    service = PluginService(create_settings(tmp_path))

    status = service.reload_runtime()
    runtime = service.runtime_or_empty()
    combined = runtime_with_backend_secrets(SecretService(), "session", base_runtime=runtime)

    assert status.active
    assert status.plugin_ids == []
    assert status.capabilities == []
    assert [key.qualified_id for key in combined.capabilities] == ["secrets:backend-session"]


def test_run_service_executes_core_pipeline(tmp_path):
    asyncio.run(_run_service_core_pipeline(tmp_path))


async def _run_service_core_pipeline(tmp_path):
    code_dir = tmp_path / "code"
    code_dir.mkdir()
    (code_dir / "solver.py").write_text(
        "from pathlib import Path\nPath('result.txt').write_text('ok', encoding='utf-8')\nprint('done')\n",
        encoding="utf-8",
    )
    settings = create_settings(tmp_path)
    artifact_service = ArtifactService(settings.runs_dir)
    service = RunService(artifact_service, SecretService(), PluginService(settings))

    run = await service.create_run(
        {
            "schema_version": "1.0",
            "build": {"name": "backend-run"},
            "code": {"name": "code", "version": "", "source": {"type": "local", "path": str(code_dir)}},
        },
        {"name": "backend-run"},
        run_config={
            "schema_version": "1.0",
            "run": {
                "executable": sys.executable,
                "args": ["solver.py"],
                "cwd": ".",
                "encoding": "utf-8",
                "stdin_mode": "none",
                "timeout_seconds": None,
            },
        },
        session_key=session_key_from_token_or_header("backend-run"),
    )

    details = service.get_run(run.id)
    for _ in range(100):
        if details is not None and details.status in {"success", "failed", "cancelled"}:
            break
        await asyncio.sleep(0.05)
        details = service.get_run(run.id)

    assert details is not None
    assert details.status == "success"
    assert artifact_service.artifact_path(run.id, "manifest.json") is not None
    assert artifact_service.artifact_path(run.id, "stdout.txt").read_text(encoding="utf-8").strip() == "done"


def _service() -> GraphService:
    settings = create_settings(Path("."))
    return GraphService(CatalogService(PluginService(settings)))


def _edge(source_node: str, source_port: str, target_node: str, target_port: str) -> GraphEdge:
    return GraphEdge(
        id=f"{source_node}-{target_node}-{target_port}",
        source=GraphEdgeEndpoint(node_id=source_node, port_id=source_port),
        target=GraphEdgeEndpoint(node_id=target_node, port_id=target_port),
    )
