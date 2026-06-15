from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json
import shlex
import uuid

from calcchain_core import CalculationCore, ManifestEnvironmentError, ManifestEnvironmentRequest
from calcchain_core.common.errors import ConfigFormatError, RestoreError, SourceError
from calcchain_core.utils.json import read_json
from calcchain_core.utils.toml import read_toml

from calcchain_backend.schemas.common import Diagnostic
from calcchain_backend.schemas.graph import (
    GraphDocument,
    GraphEdge,
    GraphEdgeEndpoint,
    GraphManifestImportEnvironment,
    GraphManifestImportResponse,
    GraphNode,
    GraphPosition,
)
from calcchain_backend.services.catalog_service import CatalogService


@dataclass(frozen=True)
class ManifestImportPaths:
    import_id: str
    root_dir: Path
    source_manifest_path: Path
    target_job_dir: Path


class ManifestImportService:
    def __init__(self, catalog_service: CatalogService) -> None:
        self._catalog_service = catalog_service

    def import_manifest(
        self,
        manifest_bytes: bytes,
        *,
        imports_root: Path,
        runtime: Any = None,
    ) -> GraphManifestImportResponse:
        paths = self._new_import_paths(imports_root)
        paths.root_dir.mkdir(parents=True, exist_ok=False)
        try:
            self._write_manifest_bytes(manifest_bytes, paths.source_manifest_path)
            core = CalculationCore(paths.target_job_dir, runtime=runtime)
            environment = core.create_environment_from_manifest(
                ManifestEnvironmentRequest(
                    manifest_path=paths.source_manifest_path,
                    target_job_dir=paths.target_job_dir,
                ),
            )
            build_config = read_toml(paths.target_job_dir / "build.toml")
            run_config = _read_optional_toml(paths.target_job_dir / "run.toml")
            publish_config = _read_optional_toml(paths.target_job_dir / "publish.toml")
            rules_config = _read_optional_json(paths.target_job_dir / "rules.json")
            graph = ConfigGraphBuilder(self._catalog_service.get_catalog().catalog_version).build(
                build_config=build_config,
                run_config=run_config,
                publish_config=publish_config,
                rules_config=rules_config,
                environment=environment,
                import_id=paths.import_id,
            )
            return GraphManifestImportResponse(
                valid=True,
                graph=graph,
                build_config=build_config,
                run_config=run_config,
                publish_config=publish_config,
                rules_config=rules_config,
                environment=GraphManifestImportEnvironment(
                    import_id=paths.import_id,
                    target_job_dir=str(paths.target_job_dir),
                    manifest_path=str(paths.source_manifest_path),
                    written_files=list(environment.written_files),
                    restored_files=list(environment.restored_files),
                ),
                warnings=[
                    Diagnostic(code="manifest_import_warning", severity="warning", message=message)
                    for message in environment.warnings
                ],
            )
        except json.JSONDecodeError as err:
            return _invalid_response("manifest_invalid_json", f"Invalid manifest JSON: {err}", paths)
        except (ConfigFormatError, ManifestEnvironmentError, RestoreError, SourceError, OSError, ValueError) as err:
            return _invalid_response("manifest_import_failed", str(err), paths)

    @staticmethod
    def _new_import_paths(imports_root: Path) -> ManifestImportPaths:
        import_id = f"manifest_{uuid.uuid4().hex[:16]}"
        root_dir = Path(imports_root) / import_id
        return ManifestImportPaths(
            import_id=import_id,
            root_dir=root_dir,
            source_manifest_path=root_dir / "source_manifest.json",
            target_job_dir=root_dir / "job",
        )

    @staticmethod
    def _write_manifest_bytes(manifest_bytes: bytes, path: Path) -> None:
        if not manifest_bytes.strip():
            raise ValueError("manifest file is empty")
        json.loads(manifest_bytes.decode("utf-8"))
        path.write_bytes(manifest_bytes)


class ConfigGraphBuilder:
    def __init__(self, catalog_version: str) -> None:
        self._catalog_version = catalog_version
        self._nodes: list[GraphNode] = []
        self._edges: list[GraphEdge] = []
        self._used_ids: set[str] = set()

    def build(
        self,
        *,
        build_config: dict[str, Any],
        run_config: dict[str, Any] | None,
        publish_config: dict[str, Any] | None,
        rules_config: dict[str, Any] | None,
        environment: Any,
        import_id: str,
    ) -> GraphDocument:
        build = _mapping(build_config.get("build"))
        code = _mapping(build_config.get("code"))
        graph_name = str(build.get("name") or "Импортированный manifest")

        code_node = self._add_source_node(
            "code",
            _mapping(code.get("source")),
            "code",
            0,
            0,
            extra_config={
                "name": str(code.get("name") or "code"),
                "version": str(code.get("version") or ""),
            },
        )
        calc_node = self._add_calculation_node(run_config, 360, 0)
        self._add_edge(code_node.id, "output", calc_node.id, "code")

        input_y = 150
        for index, raw_input in enumerate(_list(build_config.get("inputs")), start=1):
            input_config = _mapping(raw_input)
            source_node = self._add_source_node(
                str(input_config.get("name") or f"input_{index}"),
                _mapping(input_config.get("source")),
                "input",
                0,
                input_y,
                extra_config={"name": str(input_config.get("name") or f"input_{index}")},
            )
            rule_set_name = input_config.get("rule_set")
            if isinstance(rule_set_name, str) and rule_set_name:
                rule_node = self._add_rule_node(rule_set_name, rules_config, 180, input_y)
                self._add_edge(source_node.id, "output", rule_node.id, "source")
                self._add_edge(rule_node.id, "mapped", calc_node.id, "input")
            else:
                self._add_edge(source_node.id, "output", calc_node.id, "input")
            input_y += 130

        self._add_env_nodes(run_config, calc_node, 360, -150)
        self._add_publish_nodes(publish_config, rules_config, calc_node, 720, 0)

        metadata: dict[str, Any] = {
            "manifest_import": {
                "import_id": import_id,
                "target_job_dir": str(environment.target_job_dir),
                "written_files": list(environment.written_files),
                "restored_files": list(environment.restored_files),
            },
            "catalog_version": self._catalog_version,
        }
        if publish_config is not None and isinstance(publish_config.get("service_target"), dict):
            metadata["publish"] = {"service_target": dict(publish_config["service_target"])}

        return GraphDocument(
            name=graph_name,
            nodes=self._nodes,
            edges=self._edges,
            metadata=metadata,
        )

    def _add_source_node(
        self,
        name: str,
        source: dict[str, Any],
        kind: str,
        x: float,
        y: float,
        extra_config: dict[str, Any] | None = None,
    ) -> GraphNode:
        ref = dict(source)
        credentials = _optional_mapping(ref.pop("credentials", None))
        source_type = str(ref.pop("type", "local") or "local")
        node_type = f"source.{source_type}.{kind}"
        node = self._add_node(
            _safe_id(f"{kind}_{name}"),
            node_type,
            _source_node_title(source_type, kind),
            {**_ref_config(ref), **(extra_config or {})},
            x,
            y,
        )
        self._add_auth_node_if_needed(node, credentials, x - 180, y)
        return node

    def _add_calculation_node(self, run_config: dict[str, Any] | None, x: float, y: float) -> GraphNode:
        run = _mapping(run_config.get("run")) if run_config is not None else {}
        executable = str(run.get("executable") or "")
        args = [str(item) for item in _list(run.get("args"))]
        command = shlex.join([executable, *args]) if executable else ""
        config = {
            "command": command,
            "working_directory": str(run.get("cwd") or "."),
            "timeout_seconds": run.get("timeout_seconds"),
            "encoding": str(run.get("encoding") or "utf-8"),
            "stdin_mode": str(run.get("stdin_mode") or "none"),
            "stdin_text": str(run.get("stdin_text") or ""),
        }
        return self._add_node("calculation", "calculation", "Расчёт", config, x, y)

    def _add_rule_node(self, rule_set_name: str, rules_config: dict[str, Any] | None, x: float, y: float) -> GraphNode:
        rule_set = _mapping(_mapping(rules_config.get("rule_sets") if rules_config else {}).get(rule_set_name))
        config = {
            "name": rule_set_name,
            "rule_set": rule_set_name,
            "type": str(rule_set.get("type") or "input"),
            "status": str(rule_set.get("status") or ""),
            "description": str(rule_set.get("description") or ""),
            "ensure_all_files": bool(rule_set.get("ensure_all_files", True)),
            "rules": [dict(_mapping(item)) for item in _list(rule_set.get("rules"))],
        }
        return self._add_node(_safe_id(f"rules_{rule_set_name}"), "rule-set", "Набор правил", config, x, y)

    def _add_env_nodes(self, run_config: dict[str, Any] | None, calc_node: GraphNode, x: float, y: float) -> None:
        if run_config is None:
            return
        env = _mapping(_mapping(run_config.get("run")).get("env"))
        public = _mapping(env.get("public"))
        secrets = _mapping(env.get("secrets"))
        offset = 0
        for name, value in public.items():
            node = self._add_node(
                _safe_id(f"env_{name}"),
                "env.public",
                "Переменная окружения",
                {"name": str(name), "value": str(value)},
                x,
                y + offset,
            )
            self._add_edge(node.id, "output", calc_node.id, "env")
            offset -= 110
        for name, secret_ref in secrets.items():
            config = {"name": str(name)}
            if isinstance(secret_ref, str) and secret_ref:
                config["credential_ref"] = secret_ref
            node = self._add_node(_safe_id(f"secret_env_{name}"), "env.secret", "Секретная переменная окружения", config, x, y + offset)
            self._add_edge(node.id, "output", calc_node.id, "env")
            offset -= 110

    def _add_publish_nodes(
        self,
        publish_config: dict[str, Any] | None,
        rules_config: dict[str, Any] | None,
        calc_node: GraphNode,
        x: float,
        y: float,
    ) -> None:
        if publish_config is None:
            return
        for index, raw_target in enumerate(_list(publish_config.get("targets")), start=1):
            target = dict(_mapping(raw_target))
            name = str(target.pop("name", "") or f"target_{index}")
            rule_sets = [str(item) for item in _list(target.pop("rule_sets", []))]
            target.pop("message", None)
            credentials = _optional_mapping(target.pop("credentials", None))
            target_type = str(target.pop("type", "local") or "local")
            rules = _rules_for_target(rule_sets, rules_config)

            artifact_node = self._add_node(
                _safe_id(f"artifact_{name}"),
                "artifact.output",
                "Выходной артефакт",
                {"name": name, "rule_sets": rule_sets, "rules": rules},
                x,
                y + (index - 1) * 140,
            )
            target_node = self._add_node(
                _safe_id(f"target_{name}"),
                f"target.{target_type}",
                _target_node_title(target_type),
                {"path": str(target.get("path", "")), "rule_sets": rule_sets, "rules": rules, **_ref_config(target)},
                x + 260,
                y + (index - 1) * 140,
            )
            self._add_edge(calc_node.id, "output", artifact_node.id, "source")
            self._add_edge(artifact_node.id, "artifact", target_node.id, "artifact")
            self._add_auth_node_if_needed(target_node, credentials, x + 80, y + (index - 1) * 140)

    def _add_auth_node_if_needed(
        self,
        target_node: GraphNode,
        credentials: dict[str, Any] | None,
        x: float,
        y: float,
    ) -> None:
        if not credentials or not target_node.type.endswith(".svn"):
            return
        public = _mapping(credentials.get("public"))
        secrets = _mapping(credentials.get("secrets"))
        config = {str(key): str(value) for key, value in public.items()}
        if secrets:
            first_secret = next(iter(secrets.values()))
            if isinstance(first_secret, str) and first_secret:
                config["credential_ref"] = first_secret
        auth_node = self._add_node(
            _safe_id(f"auth_{target_node.id}"),
            "auth.login-password",
            "Логин и пароль",
            config,
            x,
            y,
        )
        self._add_edge(auth_node.id, "auth", target_node.id, "auth")

    def _add_node(
        self,
        node_id: str,
        node_type: str,
        title: str,
        config: dict[str, Any],
        x: float,
        y: float,
    ) -> GraphNode:
        unique_id = _unique_id(node_id, self._used_ids)
        self._used_ids.add(unique_id)
        node = GraphNode(
            id=unique_id,
            type=node_type,
            title=title,
            position=GraphPosition(x=x, y=y),
            config=config,
        )
        self._nodes.append(node)
        return node

    def _add_edge(self, source_node: str, source_port: str, target_node: str, target_port: str) -> None:
        self._edges.append(
            GraphEdge(
                id=_unique_id(f"edge_{source_node}_{target_node}_{target_port}", {edge.id for edge in self._edges}),
                source=GraphEdgeEndpoint(node_id=source_node, port_id=source_port),
                target=GraphEdgeEndpoint(node_id=target_node, port_id=target_port),
            ),
        )


def _invalid_response(code: str, message: str, paths: ManifestImportPaths) -> GraphManifestImportResponse:
    return GraphManifestImportResponse(
        valid=False,
        diagnostics=[Diagnostic(code=code, message=message)],
        environment=GraphManifestImportEnvironment(
            import_id=paths.import_id,
            target_job_dir=str(paths.target_job_dir),
            manifest_path=str(paths.source_manifest_path),
            written_files=[],
            restored_files=[],
        ),
    )


def _read_optional_toml(path: Path) -> dict[str, Any] | None:
    return read_toml(path) if path.is_file() else None


def _read_optional_json(path: Path) -> dict[str, Any] | None:
    return read_json(path) if path.is_file() else None


def _rules_for_target(rule_sets: list[str], rules_config: dict[str, Any] | None) -> list[dict[str, Any]]:
    all_rule_sets = _mapping(rules_config.get("rule_sets") if rules_config else {})
    result: list[dict[str, Any]] = []
    for name in rule_sets:
        rule_set = _mapping(all_rule_sets.get(name))
        result.extend(dict(_mapping(rule)) for rule in _list(rule_set.get("rules")))
    return result


def _ref_config(ref: dict[str, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in ref.items() if key not in {"credentials"}}


def _source_node_title(source_type: str, kind: str) -> str:
    if source_type == "local":
        return "Локальный источник кода" if kind == "code" else "Локальный источник данных"
    if source_type == "svn":
        return "SVN-источник кода" if kind == "code" else "SVN-источник данных"
    return f"{_capability_title(source_type)}: {'код' if kind == 'code' else 'данные'}"


def _target_node_title(target_type: str) -> str:
    if target_type == "local":
        return "Локальная папка результата"
    if target_type == "svn":
        return "SVN-папка результата"
    return f"{_capability_title(target_type)}: папка результата"


def _capability_title(value: str) -> str:
    return " ".join(part.upper() if part.lower() == "svn" else part.capitalize() for part in value.replace("_", "-").split("-"))


def _safe_id(value: str) -> str:
    normalized = "".join(char.lower() if char.isalnum() else "_" for char in value).strip("_")
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    return normalized or "node"


def _unique_id(value: str, used: set[str]) -> str:
    candidate = value
    index = 2
    while candidate in used:
        candidate = f"{value}_{index}"
        index += 1
    return candidate


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _optional_mapping(value: Any) -> dict[str, Any] | None:
    return dict(value) if isinstance(value, dict) else None


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []
