from __future__ import annotations

import os
import shlex
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from calcchain_backend.schemas.catalog import BlockDescriptor, CatalogResponse
from calcchain_backend.schemas.common import Diagnostic
from calcchain_backend.schemas.graph import GraphDocument, GraphEdge, GraphNode
from calcchain_backend.services.secret_service import secret_ref_for_graph_node


SECRET_REF_FIELDS = {"credential_ref", "secret_ref"}
SECRET_METADATA_KEYS = ("x-calcchain-secret", "x-secret", "secret")
PUBLIC_METADATA_KEYS = ("x-calcchain-public-credential", "public_credential")


@dataclass(frozen=True)
class CoreCompileResult:
    build_config: dict[str, Any] | None
    run_config: dict[str, Any] | None
    publish_config: dict[str, Any] | None
    rules_config: dict[str, Any] | None
    diagnostics: list[Diagnostic]
    warnings: list[Diagnostic]

    @property
    def valid(self) -> bool:
        return not self.diagnostics


class CoreConfigCompiler:
    def __init__(self, catalog: CatalogResponse) -> None:
        self._catalog = catalog
        self._descriptors = {block.type: block for block in catalog.blocks}

    def compile(self, graph: GraphDocument, compile_options: dict[str, Any] | None = None) -> CoreCompileResult:
        compile_options = compile_options or {}
        state = _GraphState(graph)
        diagnostics: list[Diagnostic] = []
        warnings: list[Diagnostic] = []

        calculation = self._single_calculation_node(graph, diagnostics)
        if calculation is None:
            return CoreCompileResult(None, None, None, None, diagnostics, warnings)

        code_node = self._single_source_for_port(state, calculation, "code", diagnostics)
        if code_node is None:
            return CoreCompileResult(None, None, None, None, diagnostics, warnings)

        build_config = {
            "schema_version": "1.0",
            "build": {"name": graph.name or calculation.title or "Untitled CalcChain run"},
            "code": {
                "name": _node_name(code_node, default="code"),
                "version": _string_config(code_node, "version"),
                "source": self._source_ref(state, code_node),
            },
            "inputs": [],
        }

        rules = _RulesBuilder()
        used_input_names: set[str] = set()
        for input_edge in state.incoming(calculation.id, "input"):
            input_node = state.node(input_edge.source.node_id)
            if input_node is None:
                continue
            source_node = input_node
            rule_set_name = None
            if input_node.type == "rule-set":
                source_node = self._single_source_for_port(state, input_node, "source", diagnostics)
                if source_node is None:
                    continue
                rule_set_name = rules.add_from_rule_node(input_node, rule_type="input")

            input_config = {
                "name": _unique_input_name(source_node, used_input_names),
                "source": self._source_ref(state, source_node),
            }
            if rule_set_name is not None:
                input_config["rule_set"] = rule_set_name
            build_config["inputs"].append(input_config)

        run_config = self._run_config(state, calculation, diagnostics)
        publish_config = self._publish_config(state, graph, compile_options, rules, diagnostics)
        rules_config = rules.to_dict()

        return CoreCompileResult(
            build_config=build_config,
            run_config=run_config,
            publish_config=publish_config,
            rules_config=rules_config,
            diagnostics=diagnostics,
            warnings=warnings,
        )

    def _single_calculation_node(
        self,
        graph: GraphDocument,
        diagnostics: list[Diagnostic],
    ) -> GraphNode | None:
        calculations = [node for node in graph.nodes if node.type == "calculation"]
        if not calculations:
            diagnostics.append(Diagnostic(code="compile_missing_calculation", message="Graph has no calculation node"))
            return None
        if len(calculations) > 1:
            diagnostics.append(Diagnostic(code="compile_multiple_calculations", message="Only one calculation node is supported for now"))
            return None
        return calculations[0]

    def _single_source_for_port(
        self,
        state: "_GraphState",
        node: GraphNode,
        port_id: str,
        diagnostics: list[Diagnostic],
    ) -> GraphNode | None:
        edges = state.incoming(node.id, port_id)
        if not edges:
            diagnostics.append(
                Diagnostic(
                    code="compile_missing_connection",
                    message=f"Missing connection for {node.type}.{port_id}",
                    node_id=node.id,
                    port_id=port_id,
                ),
            )
            return None
        if len(edges) > 1:
            diagnostics.append(
                Diagnostic(
                    code="compile_too_many_connections",
                    message=f"Expected one connection for {node.type}.{port_id}",
                    node_id=node.id,
                    port_id=port_id,
                ),
            )
            return None
        return state.node(edges[0].source.node_id)

    def _source_ref(self, state: "_GraphState", node: GraphNode) -> dict[str, Any]:
        config = node.config
        if node.type in {"source.local.input", "source.local.code"}:
            ref: dict[str, Any] = {"type": "local", "path": str(config.get("path", ""))}
        elif node.type in {"source.svn.input", "source.svn.code"}:
            ref = {
                "type": "svn",
                "location": str(config.get("location", "")),
                "path": str(config.get("path", "")),
            }
            revision = config.get("revision")
            if revision not in (None, ""):
                ref["revision"] = str(revision)
        else:
            ref = {"type": node.type}
            ref.update({key: value for key, value in config.items() if key not in SECRET_REF_FIELDS})
        return _with_credentials(ref, self._credentials_for_node(state, node))

    def _target_ref(self, state: "_GraphState", node: GraphNode) -> dict[str, Any]:
        config = node.config
        if node.type == "target.local":
            ref: dict[str, Any] = {"type": "local", "path": str(config.get("path", ""))}
        elif node.type == "target.svn":
            ref = {
                "type": "svn",
                "location": str(config.get("location", "")),
                "path": str(config.get("path", "")),
            }
        else:
            ref = {"type": node.type}
            ref.update({key: value for key, value in config.items() if key not in SECRET_REF_FIELDS})
        return _with_credentials(ref, self._credentials_for_node(state, node))

    def _credentials_for_node(self, state: "_GraphState", node: GraphNode) -> dict[str, Any] | None:
        auth_edges = state.incoming(node.id, "auth")
        if not auth_edges:
            return None
        auth_node = state.node(auth_edges[0].source.node_id)
        if auth_node is None:
            return None
        descriptor = self._descriptors.get(auth_node.type)
        fields = _credential_fields_from_descriptor(descriptor)
        if not fields and auth_node.type in {"auth.login-password", "auth.login_password"}:
            fields = {"username": False, "password": True}
        secret_ref = secret_ref_for_graph_node(auth_node)
        public: dict[str, str] = {}
        secrets: dict[str, str] = {}
        for name, is_secret in fields.items():
            if is_secret:
                secrets[name] = secret_ref
            else:
                value = auth_node.config.get(name)
                if value not in (None, ""):
                    public[name] = str(value)
        if not public and not secrets:
            return None
        result: dict[str, Any] = {}
        if public:
            result["public"] = public
        if secrets:
            result["secrets"] = secrets
        return result

    def _run_config(self, state: "_GraphState", calculation: GraphNode, diagnostics: list[Diagnostic]) -> dict[str, Any] | None:
        config = calculation.config
        executable = config.get("executable")
        args = config.get("args")
        if executable not in (None, ""):
            command = [str(executable), *_string_list(args)]
        else:
            command = _split_command(config.get("command"))
        if not command:
            diagnostics.append(
                Diagnostic(
                    code="compile_missing_command",
                    message="Calculation command is required",
                    node_id=calculation.id,
                ),
            )
            return None

        run: dict[str, Any] = {
            "executable": command[0],
            "args": command[1:],
            "cwd": str(config.get("working_directory") or config.get("cwd") or "."),
            "timeout_seconds": _optional_timeout_seconds(config.get("timeout_seconds"), calculation, diagnostics),
            "encoding": str(config.get("encoding") or "utf-8"),
            "stdin_mode": str(config.get("stdin_mode") or "none"),
            "stdin_text": str(config.get("stdin_text") or ""),
        }
        env = self._run_env(state, calculation, config, diagnostics)
        if env:
            run["env"] = env
        return {"schema_version": "1.0", "run": run}

    def _run_env(
        self,
        state: "_GraphState",
        calculation: GraphNode,
        calculation_config: dict[str, Any],
        diagnostics: list[Diagnostic],
    ) -> dict[str, Any]:
        public = _string_dict(calculation_config.get("env") or calculation_config.get("public_env") or {})
        secrets = _string_dict(calculation_config.get("secret_env") or {})

        for env_edge in state.incoming(calculation.id, "env"):
            env_node = state.node(env_edge.source.node_id)
            if env_node is None:
                continue
            name = _string_config(env_node, "name")
            if not name:
                diagnostics.append(
                    Diagnostic(
                        code="compile_missing_env_name",
                        message="Environment variable name is required",
                        node_id=env_node.id,
                    ),
                )
                continue
            if env_node.type in {"env.secret", "env.secure"}:
                secrets[name] = secret_ref_for_graph_node(env_node)
                continue
            value = env_node.config.get("value")
            if value in (None, ""):
                diagnostics.append(
                    Diagnostic(
                        code="compile_missing_env_value",
                        message=f"Environment variable value is required: {name}",
                        node_id=env_node.id,
                    ),
                )
                continue
            public[name] = str(value)

        result: dict[str, Any] = {}
        if public:
            result["public"] = public
        if secrets:
            result["secrets"] = secrets
        return result

    def _publish_config(
        self,
        state: "_GraphState",
        graph: GraphDocument,
        compile_options: dict[str, Any],
        rules: "_RulesBuilder",
        diagnostics: list[Diagnostic],
    ) -> dict[str, Any] | None:
        targets = []
        for node in graph.nodes:
            if not node.type.startswith("target."):
                continue
            if not state.incoming(node.id, "artifact"):
                continue
            rule_sets = _target_rule_sets(state, node, rules)
            target_ref = self._target_ref(state, node)
            targets.append(
                {
                    "name": _node_name(node, default="target"),
                    **target_ref,
                    "rule_sets": rule_sets,
                },
            )

        if not targets:
            return None

        service_target = _service_target(compile_options, graph)
        if service_target is None:
            diagnostics.append(
                Diagnostic(
                    code="compile_missing_service_target",
                    message="Publish targets require service_target or service_target_path in compile options or graph metadata",
                ),
            )
            return None

        return {
            "schema_version": "1.0",
            "publish": {"message": str(compile_options.get("message") or "")},
            "service_target": service_target,
            "targets": targets,
        }


class _RulesBuilder:
    def __init__(self) -> None:
        self._rule_sets: dict[str, dict[str, Any]] = {}

    def add_from_rule_node(self, node: GraphNode, *, rule_type: str) -> str:
        name = _rule_set_name(node, default=f"{rule_type}_{node.id}")
        self._rule_sets.setdefault(name, _rule_set_from_config(node.config, rule_type=rule_type))
        return name

    def add_output_rule_set(self, name: str, config: dict[str, Any] | None = None) -> str:
        self._rule_sets.setdefault(name, _rule_set_from_config(config or {}, rule_type="output"))
        return name

    def to_dict(self) -> dict[str, Any] | None:
        if not self._rule_sets:
            return None
        return {
            "schema_version": "1.0",
            "rules_file": {},
            "rule_sets": self._rule_sets,
        }


class _GraphState:
    def __init__(self, graph: GraphDocument) -> None:
        self._nodes = {node.id: node for node in graph.nodes}
        self._incoming: dict[tuple[str, str], list[GraphEdge]] = defaultdict(list)
        for edge in graph.edges:
            self._incoming[(edge.target.node_id, edge.target.port_id)].append(edge)

    def node(self, node_id: str) -> GraphNode | None:
        return self._nodes.get(node_id)

    def incoming(self, node_id: str, port_id: str) -> list[GraphEdge]:
        return list(self._incoming.get((node_id, port_id), []))


def _with_credentials(ref: dict[str, Any], credentials: dict[str, Any] | None) -> dict[str, Any]:
    if credentials is not None:
        ref["credentials"] = credentials
    return ref


def _credential_fields_from_descriptor(descriptor: BlockDescriptor | None) -> dict[str, bool]:
    schema = descriptor.config_schema if descriptor is not None else {}
    properties = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(properties, dict):
        return {}
    result: dict[str, bool] = {}
    for name, raw_property in properties.items():
        if name in SECRET_REF_FIELDS or not isinstance(name, str) or not isinstance(raw_property, dict):
            continue
        if _is_secret_property(raw_property):
            result[name] = True
        elif _is_public_credential_property(raw_property):
            result[name] = False
    return result


def _is_secret_property(data: dict[str, Any]) -> bool:
    if any(data.get(key) is True for key in SECRET_METADATA_KEYS):
        return True
    if data.get("x-calcchain-credential") == "secret":
        return True
    return data.get("format") == "password" or data.get("writeOnly") is True


def _is_public_credential_property(data: dict[str, Any]) -> bool:
    if any(data.get(key) is True for key in PUBLIC_METADATA_KEYS):
        return True
    return data.get("x-calcchain-credential") == "public"


def _split_command(value: Any) -> list[str]:
    if isinstance(value, list):
        return _string_list(value)
    if not isinstance(value, str) or not value.strip():
        return []
    return shlex.split(value, posix=os.name != "nt")


def _optional_timeout_seconds(value: Any, node: GraphNode, diagnostics: list[Diagnostic]) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        diagnostics.append(
            Diagnostic(
                code="compile_invalid_timeout_seconds",
                message="Timeout seconds must be an integer or empty",
                node_id=node.id,
                details={"field": "timeout_seconds"},
            ),
        )
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            diagnostics.append(
                Diagnostic(
                    code="compile_invalid_timeout_seconds",
                    message="Timeout seconds must be an integer or empty",
                    node_id=node.id,
                    details={"field": "timeout_seconds"},
                ),
            )
            return None
    diagnostics.append(
        Diagnostic(
            code="compile_invalid_timeout_seconds",
            message="Timeout seconds must be an integer or empty",
            node_id=node.id,
            details={"field": "timeout_seconds"},
        ),
    )
    return None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _string_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items() if item is not None}


def _node_name(node: GraphNode, *, default: str) -> str:
    raw = node.config.get("name") or node.title or node.id or default
    return str(raw)


def _unique_input_name(node: GraphNode, used_names: set[str]) -> str:
    raw = node.config.get("name") or node.id or "input"
    base = _safe_input_name(str(raw), fallback="input")
    name = base
    index = 2
    while name in used_names:
        name = f"{base}_{index}"
        index += 1
    used_names.add(name)
    return name


def _safe_input_name(value: str, *, fallback: str) -> str:
    normalized = "".join(char if char.isalnum() or char in {"_", "-"} else "_" for char in value).strip("_")
    return normalized or fallback


def _string_config(node: GraphNode, key: str) -> str:
    value = node.config.get(key)
    return "" if value is None else str(value)


def _rule_set_name(node: GraphNode, *, default: str) -> str:
    raw = node.config.get("rule_set") or node.config.get("name") or node.title or default
    return _safe_rule_set_name(str(raw))


def _safe_rule_set_name(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"_", "-"} else "_" for char in value).strip("_") or "rules"


def _rule_set_from_config(config: dict[str, Any], *, rule_type: str) -> dict[str, Any]:
    raw_rules = config.get("rules")
    if not isinstance(raw_rules, list) or not raw_rules:
        raw_rules = [{"source": ".*", "destination": "<>"}]
    rules = []
    for item in raw_rules:
        if not isinstance(item, dict):
            continue
        source = item.get("source")
        destination = item.get("destination") or item.get("target") or item.get("work_path")
        if source not in (None, "") and destination not in (None, ""):
            rules.append({"source": str(source), "destination": str(destination)})
    if not rules:
        rules.append({"source": ".*", "destination": "<>"})
    return {
        "type": str(config.get("type") or rule_type),
        "status": str(config.get("status") or ""),
        "description": str(config.get("description") or ""),
        "ensure_all_files": bool(config.get("ensure_all_files", True)),
        "rules": rules,
    }


def _target_rule_sets(state: _GraphState, target: GraphNode, rules: _RulesBuilder) -> list[str]:
    raw_rule_sets = target.config.get("rule_sets")
    if isinstance(raw_rule_sets, list) and raw_rule_sets:
        for name in raw_rule_sets:
            rules.add_output_rule_set(str(name), target.config)
        return [str(name) for name in raw_rule_sets]
    raw_rule_set = target.config.get("rule_set")
    if isinstance(raw_rule_set, str) and raw_rule_set:
        return [rules.add_output_rule_set(raw_rule_set, target.config)]

    for edge in state.incoming(target.id, "artifact"):
        artifact = state.node(edge.source.node_id)
        if artifact is None:
            continue
        raw_artifact_rule_set = artifact.config.get("rule_set")
        if isinstance(raw_artifact_rule_set, str) and raw_artifact_rule_set:
            return [rules.add_output_rule_set(raw_artifact_rule_set, artifact.config)]

    return [rules.add_output_rule_set("outputs")]


def _service_target(compile_options: dict[str, Any], graph: GraphDocument) -> dict[str, Any] | None:
    option_target = compile_options.get("service_target")
    if isinstance(option_target, dict):
        return dict(option_target)
    option_path = compile_options.get("service_target_path")
    if isinstance(option_path, str) and option_path:
        return {"type": "local", "path": option_path}

    publish_metadata = graph.metadata.get("publish") if isinstance(graph.metadata.get("publish"), dict) else {}
    metadata_target = publish_metadata.get("service_target")
    if isinstance(metadata_target, dict):
        return dict(metadata_target)
    metadata_path = publish_metadata.get("service_target_path") or graph.metadata.get("service_target_path")
    if isinstance(metadata_path, str) and metadata_path:
        return {"type": "local", "path": metadata_path}
    return None
