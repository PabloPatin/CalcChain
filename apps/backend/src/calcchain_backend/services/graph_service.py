from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict, deque
from datetime import timezone
from typing import Any

from calcchain_backend.schemas.catalog import BlockDescriptor, ConnectionRule, PortDescriptor
from calcchain_backend.schemas.common import Diagnostic, now_utc
from calcchain_backend.schemas.graph import GraphCompileResponse, GraphDocument, GraphNode, GraphValidateResponse
from calcchain_backend.services.catalog_service import CatalogService
from calcchain_backend.services.core_compiler import CoreConfigCompiler
from calcchain_backend.services.secret_service import secret_ref_for_graph_node


SECRET_REF_FIELDS = {"credential_ref", "secret_ref"}
SECRET_METADATA_KEYS = ("x-calcchain-secret", "x-secret", "secret")


class GraphService:
    def __init__(self, catalog_service: CatalogService) -> None:
        self._catalog_service = catalog_service

    def validate(self, graph: GraphDocument) -> GraphValidateResponse:
        catalog = self._catalog_service.get_catalog()
        blocks_by_type = {block.type: block for block in catalog.blocks}
        rules = catalog.connection_rules
        errors: list[Diagnostic] = []
        warnings: list[Diagnostic] = []

        node_ids = [node.id for node in graph.nodes]
        duplicates = [node_id for node_id, count in Counter(node_ids).items() if count > 1]
        for node_id in duplicates:
            errors.append(Diagnostic(code="duplicate_node_id", message=f"Duplicate node id: {node_id}", node_id=node_id))

        nodes = {node.id: node for node in graph.nodes}
        for node in graph.nodes:
            if node.type not in blocks_by_type:
                errors.append(Diagnostic(code="unknown_block_type", message=f"Unknown block type: {node.type}", node_id=node.id))
                continue
            block = blocks_by_type[node.type]
            required_fields = block.config_schema.get("required", []) if isinstance(block.config_schema, dict) else []
            secret_fields = _secret_fields_from_descriptor(block)
            for field_name in required_fields:
                if field_name in secret_fields:
                    continue
                if field_name not in node.config or node.config.get(field_name) in (None, ""):
                    errors.append(
                        Diagnostic(
                            code="missing_required_config_field",
                            message=f"Required config field is missing: {field_name}",
                            node_id=node.id,
                            details={"field": field_name},
                        ),
                    )

        incoming: dict[tuple[str, str], int] = defaultdict(int)
        outgoing: dict[tuple[str, str], int] = defaultdict(int)
        for edge in graph.edges:
            source_node = nodes.get(edge.source.node_id)
            target_node = nodes.get(edge.target.node_id)
            if source_node is None:
                errors.append(Diagnostic(code="edge_unknown_source_node", message="Edge source node does not exist", edge_id=edge.id, node_id=edge.source.node_id))
                continue
            if target_node is None:
                errors.append(Diagnostic(code="edge_unknown_target_node", message="Edge target node does not exist", edge_id=edge.id, node_id=edge.target.node_id))
                continue
            source_port = self._find_port(blocks_by_type.get(source_node.type), edge.source.port_id)
            target_port = self._find_port(blocks_by_type.get(target_node.type), edge.target.port_id)
            if source_port is None:
                errors.append(Diagnostic(code="edge_unknown_source_port", message="Edge source port does not exist", edge_id=edge.id, node_id=edge.source.node_id, port_id=edge.source.port_id))
                continue
            if target_port is None:
                errors.append(Diagnostic(code="edge_unknown_target_port", message="Edge target port does not exist", edge_id=edge.id, node_id=edge.target.node_id, port_id=edge.target.port_id))
                continue
            if source_port.direction != "output":
                errors.append(Diagnostic(code="edge_source_not_output", message="Edge source port must be output", edge_id=edge.id, node_id=edge.source.node_id, port_id=edge.source.port_id))
            if target_port.direction != "input":
                errors.append(Diagnostic(code="edge_target_not_input", message="Edge target port must be input", edge_id=edge.id, node_id=edge.target.node_id, port_id=edge.target.port_id))
            if not self._allowed(source_port, target_port, rules):
                errors.append(
                    Diagnostic(
                        code="incompatible_ports",
                        message=f"Cannot connect {source_port.kind} to {target_port.kind}",
                        edge_id=edge.id,
                        node_id=edge.target.node_id,
                        port_id=edge.target.port_id,
                    ),
                )
            incoming[(edge.target.node_id, edge.target.port_id)] += 1
            outgoing[(edge.source.node_id, edge.source.port_id)] += 1

        for node in graph.nodes:
            block = blocks_by_type.get(node.type)
            if block is None:
                continue
            for port in block.ports:
                count = incoming[(node.id, port.id)] if port.direction == "input" else outgoing[(node.id, port.id)]
                if port.required and count == 0:
                    errors.append(
                        Diagnostic(
                            code="missing_required_connection",
                            message=f"Required port has no connection: {port.title}",
                            node_id=node.id,
                            port_id=port.id,
                        ),
                    )
                if port.max_connections is not None and count > port.max_connections:
                    errors.append(
                        Diagnostic(
                            code="too_many_connections",
                            message=f"Port accepts at most {port.max_connections} connection(s)",
                            node_id=node.id,
                            port_id=port.id,
                            details={"actual": count, "max": port.max_connections},
                        ),
                    )

        connected_nodes = {edge.source.node_id for edge in graph.edges} | {edge.target.node_id for edge in graph.edges}
        for node in graph.nodes:
            if node.id not in connected_nodes and len(graph.nodes) > 1:
                warnings.append(Diagnostic(code="isolated_node", severity="warning", message="Node is not connected", node_id=node.id))

        return GraphValidateResponse(valid=not errors, errors=errors, warnings=warnings)

    def compile(self, graph: GraphDocument, compile_options: dict[str, Any] | None = None) -> GraphCompileResponse:
        validation = self.validate(graph)
        if not validation.valid:
            return GraphCompileResponse(valid=False, diagnostics=validation.errors, warnings=validation.warnings)
        safe_graph = self.sanitize_graph(graph)
        core = CoreConfigCompiler(self._catalog_service.get_catalog()).compile(safe_graph, compile_options)
        if not core.valid:
            return GraphCompileResponse(
                valid=False,
                diagnostics=core.diagnostics,
                warnings=[*validation.warnings, *core.warnings],
            )
        compiled = {
            "schema_version": "1.0",
            "kind": "calcchain.graph_config",
            "name": safe_graph.name or "Untitled CalcChain run",
            "graph_digest": self._graph_digest(safe_graph),
            "compiled_at": now_utc().astimezone(timezone.utc).isoformat(),
            "compile_options": compile_options or {},
            "catalog_version": self._catalog_service.get_catalog().catalog_version,
            "nodes": [node.model_dump(mode="json") for node in safe_graph.nodes],
            "edges": [edge.model_dump(mode="json") for edge in safe_graph.edges],
            "execution_plan": self._execution_plan(safe_graph),
        }
        return GraphCompileResponse(
            valid=True,
            build_config=core.build_config,
            run_config=core.run_config,
            publish_config=core.publish_config,
            rules_config=core.rules_config,
            graph_config=compiled,
            diagnostics=[],
            warnings=[*validation.warnings, *core.warnings],
        )

    def sanitize_graph(self, graph: GraphDocument) -> GraphDocument:
        """Return graph copy without secret field values in node configs."""
        catalog = self._catalog_service.get_catalog()
        descriptors = {block.type: block for block in catalog.blocks}
        nodes = []
        for node in graph.nodes:
            data = self._compiled_node(node, descriptors.get(node.type))
            nodes.append(GraphNode.model_validate(data))
        return graph.model_copy(update={"nodes": nodes})

    @staticmethod
    def _find_port(block: BlockDescriptor | None, port_id: str) -> PortDescriptor | None:
        if block is None:
            return None
        for port in block.ports:
            if port.id == port_id:
                return port
        return None

    @staticmethod
    def _allowed(source: PortDescriptor, target: PortDescriptor, rules: list[ConnectionRule]) -> bool:
        return any(rule.from_kind == source.kind and rule.to_kind == target.kind for rule in rules)

    @staticmethod
    def _graph_digest(graph: GraphDocument) -> str:
        payload = graph.model_dump(mode="json")
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _compiled_nodes(self, graph: GraphDocument) -> list[dict[str, Any]]:
        catalog = self._catalog_service.get_catalog()
        descriptors = {block.type: block for block in catalog.blocks}
        return [
            self._compiled_node(node, descriptors.get(node.type))
            for node in graph.nodes
        ]

    @staticmethod
    def _compiled_node(node: GraphNode, descriptor: BlockDescriptor | None) -> dict[str, Any]:
        data = node.model_dump(mode="json")
        config = dict(data.get("config") or {})
        secret_fields = _secret_fields_from_descriptor(descriptor)
        if secret_fields:
            for field in secret_fields:
                config.pop(field, None)
            if not isinstance(config.get("credential_ref"), str) or not config.get("credential_ref"):
                config["credential_ref"] = secret_ref_for_graph_node(node)
        data["config"] = config
        return data

    @staticmethod
    def _execution_plan(graph: GraphDocument) -> list[str]:
        node_ids = [node.id for node in graph.nodes]
        incoming_count = {node_id: 0 for node_id in node_ids}
        outgoing: dict[str, list[str]] = defaultdict(list)
        for edge in graph.edges:
            if edge.source.node_id in incoming_count and edge.target.node_id in incoming_count:
                outgoing[edge.source.node_id].append(edge.target.node_id)
                incoming_count[edge.target.node_id] += 1
        queue = deque([node_id for node_id, count in incoming_count.items() if count == 0])
        result: list[str] = []
        while queue:
            node_id = queue.popleft()
            result.append(node_id)
            for target in outgoing[node_id]:
                incoming_count[target] -= 1
                if incoming_count[target] == 0:
                    queue.append(target)
        # If a cycle exists, append remaining nodes in stable order. Cycle validation
        # can be tightened later when CalcChain's final graph semantics are fixed.
        for node_id in node_ids:
            if node_id not in result:
                result.append(node_id)
        return result


def _secret_fields_from_descriptor(descriptor: BlockDescriptor | None) -> set[str]:
    if descriptor is None:
        return set()
    schema = descriptor.config_schema
    properties = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(properties, dict):
        return set()
    result: set[str] = set()
    for name, raw_property in properties.items():
        if name in SECRET_REF_FIELDS or not isinstance(name, str) or not isinstance(raw_property, dict):
            continue
        if any(raw_property.get(key) is True for key in SECRET_METADATA_KEYS):
            result.add(name)
        elif raw_property.get("x-calcchain-credential") == "secret":
            result.add(name)
        elif raw_property.get("format") == "password" or raw_property.get("writeOnly") is True:
            result.add(name)
    return result
