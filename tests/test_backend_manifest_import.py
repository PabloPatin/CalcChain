import asyncio
import hashlib
import json
from pathlib import Path

import pytest

pytest.importorskip("pydantic")

from calcchain_backend.api.graphs import import_manifest_graph
from calcchain_backend.app import create_app
from calcchain_backend.schemas.graph import GraphDocument
from calcchain_backend.services.catalog_service import CatalogService
from calcchain_backend.services.graph_service import GraphService
from calcchain_backend.services.manifest_import_service import ManifestImportService
from calcchain_backend.services.plugin_service import PluginService
from calcchain_backend.settings import create_settings
from calcchain_core.common.hash import tree_sha256


def test_api_import_manifest_creates_environment_and_returns_graph(tmp_path):
    manifest = _manifest_fixture(tmp_path)
    settings = create_settings(tmp_path, state_dir=tmp_path / "backend_state")
    catalog_service = CatalogService(PluginService(settings))
    service = ManifestImportService(catalog_service)

    response = asyncio.run(
        import_manifest_graph(
            _RequestBody(json.dumps(manifest).encode("utf-8")),
            service,
            settings,
            None,
        ),
    )

    imported = response.model_dump(mode="json")
    assert imported["valid"] is True
    assert imported["build_config"]["build"]["name"] == "manifest-case"
    assert imported["run_config"]["run"]["executable"] == "python"
    assert imported["publish_config"]["targets"][0]["rule_sets"] == ["outputs"]

    environment = imported["environment"]
    target_job_dir = Path(environment["target_job_dir"])
    assert target_job_dir.is_dir()
    assert (target_job_dir / "build.toml").is_file()
    assert (target_job_dir / "work" / "solver.py").read_text(encoding="utf-8") == "print('ok')\n"
    assert sorted(environment["restored_files"]) == ["input/case.txt", "solver.py"]

    graph = imported["graph"]
    node_types = {node["type"] for node in graph["nodes"]}
    assert {"source.local.code", "source.local.input", "calculation", "artifact.output", "target.local"}.issubset(node_types)
    titles_by_type = {node["type"]: node["title"] for node in graph["nodes"]}
    assert titles_by_type["source.local.code"] == "Локальный источник кода"
    assert titles_by_type["source.local.input"] == "Локальный источник данных"
    assert titles_by_type["target.local"] == "Локальная папка результата"
    assert graph["metadata"]["manifest_import"]["import_id"] == environment["import_id"]
    assert graph["metadata"]["publish"]["service_target"] == {"type": "local", "path": str(tmp_path / "service")}

    compiled = GraphService(catalog_service).compile(GraphDocument.model_validate(graph)).model_dump(mode="json")
    assert compiled["valid"] is True
    assert compiled["build_config"]["code"]["name"] == "solver"
    assert compiled["build_config"]["inputs"][0]["name"] == "case"
    assert compiled["build_config"]["code"]["source"] == {"type": "local", "path": str(tmp_path / "code")}
    assert compiled["publish_config"]["service_target"] == {"type": "local", "path": str(tmp_path / "service")}


def test_api_import_manifest_reports_invalid_json(tmp_path):
    settings = create_settings(tmp_path, state_dir=tmp_path / "backend_state")
    service = ManifestImportService(CatalogService(PluginService(settings)))

    response = asyncio.run(import_manifest_graph(_RequestBody(b"{bad json"), service, settings, None))

    payload = response.model_dump(mode="json")
    assert payload["valid"] is False
    assert payload["diagnostics"][0]["code"] == "manifest_invalid_json"


def test_api_import_manifest_route_is_registered(tmp_path):
    app = create_app(create_settings(tmp_path, state_dir=tmp_path / "backend_state"))

    assert any(route.path == "/api/graphs/import/manifest" for route in app.routes)


class _RequestBody:
    def __init__(self, body: bytes) -> None:
        self._body = body

    async def body(self) -> bytes:
        return self._body


def _manifest_fixture(root: Path) -> dict:
    code_source = root / "code"
    input_source = root / "input-source"
    code_source.mkdir()
    input_source.mkdir()
    (code_source / "solver.py").write_text("print('ok')\n", encoding="utf-8")
    (input_source / "case.txt").write_text("case=42\n", encoding="utf-8")
    code_sha = _sha256(code_source / "solver.py")
    input_sha = _sha256(input_source / "case.txt")
    return {
        "schema_version": "1.0",
        "job": {"id": "manifest-case", "status": "Published", "job_dir": str(root / "old-job")},
        "build": {
            "code": {
                "name": "solver",
                "tree_sha256": tree_sha256([("solver.py", code_sha)]),
                "sources": [{"type": "local", "path": str(code_source)}],
                "map": [{"source_path": "solver.py", "work_path": "solver.py", "sha256": code_sha}],
            },
            "inputs": [
                {
                    "name": "case",
                    "tree_sha256": tree_sha256([("input/case.txt", input_sha)]),
                    "sources": [{"type": "local", "path": str(input_source)}],
                    "map": [{"source_path": "case.txt", "work_path": "input/case.txt", "sha256": input_sha}],
                },
            ],
        },
        "run": {
            "command": ["python", "solver.py"],
            "cwd": str(root / "old-job" / "work"),
            "timeout_seconds": 120,
            "encoding": "utf-8",
            "stdin": {"mode": "script", "text": "start\n"},
            "env": {"VISIBLE": "1"},
            "status": "Succeeded",
            "return_code": 0,
            "file_groups": {
                "outputs": ["results/report.txt"],
                "logs": [],
                "temp": [],
                "ignored": [],
                "unknown": [],
                "deleted": [],
            },
        },
        "publication": {
            "service_target": {"type": "local", "path": str(root / "service")},
            "outputs": [
                {
                    "name": "results",
                    "target": {"type": "local", "path": str(root / "published")},
                    "rules": {"set": "outputs"},
                    "map": [
                        {
                            "source_path": "results/report.txt",
                            "work_path": "results/report.txt",
                            "target_path": "report.txt",
                            "sha256": "a" * 64,
                        },
                    ],
                },
            ],
        },
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
