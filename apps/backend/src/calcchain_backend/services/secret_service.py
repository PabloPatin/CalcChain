from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from calcchain_backend.schemas.catalog import BlockDescriptor
from calcchain_backend.schemas.common import now_utc
from calcchain_backend.schemas.graph import GraphDocument, GraphEdge, GraphNode
from calcchain_backend.schemas.secrets import (
    ClearSessionSecretsResponse,
    DeleteSessionSecretResponse,
    SecretFieldRequirement,
    SecretFieldStatus,
    SecretRequirement,
    SecretRequirementStatus,
    SecretRequirementsResponse,
    SecretUsage,
    SessionSecretListResponse,
    SessionSecretStatus,
    StoreSessionSecretResponse,
)
from calcchain_backend.services.catalog_service import CatalogService


SECRET_REF_FIELDS = {"credential_ref", "secret_ref"}
SECRET_METADATA_KEYS = ("x-calcchain-secret", "x-secret", "secret")
PUBLIC_METADATA_KEYS = ("x-calcchain-public-credential", "public_credential")


@dataclass(frozen=True)
class StoredSecret:
    secret_ref: str
    kind: str
    values: dict[str, str]
    created_at: datetime
    expires_at: datetime | None

    def expired(self, at: datetime | None = None) -> bool:
        if self.expires_at is None:
            return False
        return self.expires_at <= (at or now_utc())


class SecretNotFoundError(KeyError):
    pass


class SecretExpiredError(KeyError):
    pass


class SecretFieldNotFoundError(KeyError):
    pass


class SecretService:
    """Transient secret store scoped by backend session.

    The service stores only values that the frontend explicitly sends to
    `/api/secrets/session`. Public graph config stays in the graph/project. API
    responses expose only secret keys and presence flags, never stored values.
    """

    def __init__(self, catalog_service: CatalogService | None = None) -> None:
        self._catalog_service = catalog_service
        self._items: dict[str, dict[str, StoredSecret]] = {}

    def get_requirements_for_graph(self, session_key: str, graph: GraphDocument) -> SecretRequirementsResponse:
        requirements = self._requirements_from_nodes_and_edges(session_key, list(graph.nodes), list(graph.edges))
        return SecretRequirementsResponse(requirements=requirements)

    def get_requirements_for_build_config(self, session_key: str, build_config: dict[str, Any]) -> SecretRequirementsResponse:
        nodes = self._nodes_from_build_config(build_config)
        edges = self._edges_from_build_config(build_config)
        requirements = self._requirements_from_nodes_and_edges(session_key, nodes, edges)
        return SecretRequirementsResponse(requirements=requirements)

    def list_session_secrets(self, session_key: str) -> SessionSecretListResponse:
        self._cleanup_session(session_key)
        items = [self._to_status(item) for item in self._items.get(session_key, {}).values()]
        items.sort(key=lambda item: item.secret_ref)
        return SessionSecretListResponse(items=items)

    def put_session_secret(
        self,
        session_key: str,
        secret_ref: str,
        kind: str,
        values: dict[str, str],
        ttl_seconds: int | None,
    ) -> StoreSessionSecretResponse:
        self._cleanup_session(session_key)
        now = now_utc()
        expires_at = now + timedelta(seconds=ttl_seconds) if ttl_seconds is not None else None
        item = StoredSecret(
            secret_ref=secret_ref,
            kind=kind,
            values={name: value for name, value in values.items() if value != ""},
            created_at=now,
            expires_at=expires_at,
        )
        self._items.setdefault(session_key, {})[secret_ref] = item
        return StoreSessionSecretResponse(secret_ref=secret_ref, item=self._to_status(item))

    def delete_session_secret(self, session_key: str, secret_ref: str) -> DeleteSessionSecretResponse:
        self._cleanup_session(session_key)
        deleted = self._items.get(session_key, {}).pop(secret_ref, None) is not None
        return DeleteSessionSecretResponse(secret_ref=secret_ref, status="deleted" if deleted else "not_found")

    def clear_session_secrets(self, session_key: str) -> ClearSessionSecretsResponse:
        deleted_count = len(self._items.get(session_key, {}))
        self._items.pop(session_key, None)
        return ClearSessionSecretsResponse(deleted_count=deleted_count)

    def secret_values_for_session(self, session_key: str) -> list[str]:
        self._cleanup_session(session_key)
        values: list[str] = []
        for item in self._items.get(session_key, {}).values():
            values.extend(value for value in item.values.values() if value)
        return sorted(set(values), key=len, reverse=True)

    def resolve_values(self, session_key: str, secret_ref: str) -> dict[str, str]:
        """Return real values for runtime-only backend code."""
        return dict(self._get_live_secret(session_key, secret_ref).values)

    def resolve_value(self, session_key: str, secret_ref: str, field_name: str) -> str:
        """Resolve one field for a core SecretsAdapter request."""
        values = self.resolve_values(session_key, secret_ref)
        try:
            return values[field_name]
        except KeyError as err:
            raise SecretFieldNotFoundError(f"{secret_ref}:{field_name}") from err

    def has_secret(self, session_key: str, secret_ref: str, field_name: str | None = None) -> bool:
        try:
            values = self.resolve_values(session_key, secret_ref)
        except (SecretExpiredError, SecretNotFoundError):
            return False
        if field_name is None:
            return bool(values)
        return field_name in values and values[field_name] != ""

    def _requirements_from_nodes_and_edges(
        self,
        session_key: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> list[SecretRequirement]:
        self._cleanup_session(session_key)
        nodes_by_id = {node.id: node for node in nodes}
        targets_by_auth_node_id = self._auth_targets(edges)
        targets_by_env_node_id = self._env_targets(edges)
        requirements_by_ref: dict[str, SecretRequirement] = {}

        for node in nodes:
            fields = self._credential_fields_for_node(node)
            if not fields:
                continue

            secret_ref = secret_ref_for_graph_node(node)
            if node.type.startswith("env."):
                target_usages = targets_by_env_node_id.get(node.id, [])
                if not target_usages:
                    continue
            else:
                target_usages = targets_by_auth_node_id.get(node.id, [])

            used_by = [self._usage_for_node(node)]
            for target_node_id, target_port_id in target_usages:
                target_node = nodes_by_id.get(target_node_id)
                if target_node is not None:
                    used_by.append(self._usage_for_node(target_node, port_id=target_port_id))

            requirement = requirements_by_ref.get(secret_ref)
            if requirement is None:
                requirement = SecretRequirement(
                    secret_ref=secret_ref,
                    kind=self._credential_kind_for_node(node),
                    title=node.title or self._title_for_node(node),
                    description=self._description_for_node(node),
                    fields=fields,
                    used_by=[],
                    status="missing",
                )
                requirements_by_ref[secret_ref] = requirement

            existing_usage_keys = {(usage.node_id, usage.port_id) for usage in requirement.used_by}
            for usage in used_by:
                key = (usage.node_id, usage.port_id)
                if key not in existing_usage_keys:
                    requirement.used_by.append(usage)
                    existing_usage_keys.add(key)

            requirement.status = self._requirement_status(session_key, requirement, node.config)

        return sorted(requirements_by_ref.values(), key=lambda item: item.secret_ref)

    def _credential_fields_for_node(self, node: GraphNode) -> list[SecretFieldRequirement]:
        descriptor = self._descriptor_for_node(node)
        if descriptor is not None:
            fields = _fields_from_descriptor(descriptor)
            if fields:
                return fields

        if node.type in {"auth.login-password", "auth.login_password"}:
            return [
                SecretFieldRequirement(name="username", title="Username", secret=False, required=True, config_path="username"),
                SecretFieldRequirement(name="password", title="Password", secret=True, required=True, config_path="password"),
            ]
        if node.type == "auth.token":
            return [SecretFieldRequirement(name="token", title="Token", secret=True, required=True, config_path="token")]
        return []

    def _descriptor_for_node(self, node: GraphNode) -> BlockDescriptor | None:
        if self._catalog_service is None:
            return None
        for block in self._catalog_service.get_catalog().blocks:
            if block.type == node.type:
                return block
        return None

    def _credential_kind_for_node(self, node: GraphNode) -> str:
        if node.type.startswith("auth."):
            return node.type.removeprefix("auth.").replace("_", "-")
        return node.type.replace(".", "-").replace("_", "-")

    def _title_for_node(self, node: GraphNode) -> str:
        descriptor = self._descriptor_for_node(node)
        return descriptor.title if descriptor is not None else node.type

    def _description_for_node(self, node: GraphNode) -> str | None:
        descriptor = self._descriptor_for_node(node)
        return descriptor.description if descriptor is not None else None

    def _get_live_secret(self, session_key: str, secret_ref: str) -> StoredSecret:
        item = self._items.get(session_key, {}).get(secret_ref)
        if item is None:
            raise SecretNotFoundError(secret_ref)
        if item.expired():
            self._items.get(session_key, {}).pop(secret_ref, None)
            raise SecretExpiredError(secret_ref)
        return item

    @staticmethod
    def _usage_for_node(node: GraphNode, port_id: str | None = None) -> SecretUsage:
        return SecretUsage(node_id=node.id, node_title=node.title, node_type=node.type, port_id=port_id)

    @staticmethod
    def _auth_targets(edges: list[GraphEdge]) -> dict[str, list[tuple[str, str]]]:
        result: dict[str, list[tuple[str, str]]] = {}
        for edge in edges:
            if edge.source.port_id == "auth":
                result.setdefault(edge.source.node_id, []).append((edge.target.node_id, edge.target.port_id))
        return result

    @staticmethod
    def _env_targets(edges: list[GraphEdge]) -> dict[str, list[tuple[str, str]]]:
        result: dict[str, list[tuple[str, str]]] = {}
        for edge in edges:
            if edge.target.port_id == "env":
                result.setdefault(edge.source.node_id, []).append((edge.target.node_id, edge.target.port_id))
        return result

    def _requirement_status(
        self,
        session_key: str,
        requirement: SecretRequirement,
        auth_node_config: Mapping[str, Any],
    ) -> SecretRequirementStatus:
        stored = self._items.get(session_key, {}).get(requirement.secret_ref)
        available_fields = set(stored.values) if stored is not None and not stored.expired() else set()
        for field in requirement.fields:
            if not field.secret and auth_node_config.get(field.name) not in (None, ""):
                available_fields.add(field.name)
        required_fields = {field.name for field in requirement.fields if field.required}
        if required_fields.issubset(available_fields):
            return "satisfied"
        if available_fields.intersection(required_fields):
            return "partial"
        return "missing"

    def _to_status(self, item: StoredSecret) -> SessionSecretStatus:
        fields = [
            SecretFieldStatus(
                name=name,
                secret=True,
                has_value=value != "",
            )
            for name, value in sorted(item.values.items())
        ]
        return SessionSecretStatus(
            secret_ref=item.secret_ref,
            kind=item.kind,
            fields=fields,
            created_at=item.created_at,
            expires_at=item.expires_at,
        )

    @staticmethod
    def _nodes_from_build_config(build_config: dict[str, Any]) -> list[GraphNode]:
        raw_nodes = build_config.get("nodes", [])
        nodes: list[GraphNode] = []
        if not isinstance(raw_nodes, Iterable) or isinstance(raw_nodes, (str, bytes, dict)):
            return nodes
        for raw_node in raw_nodes:
            if not isinstance(raw_node, dict):
                continue
            try:
                nodes.append(GraphNode.model_validate(raw_node))
            except Exception:
                continue
        return nodes

    @staticmethod
    def _edges_from_build_config(build_config: dict[str, Any]) -> list[GraphEdge]:
        raw_edges = build_config.get("edges", [])
        edges: list[GraphEdge] = []
        if not isinstance(raw_edges, Iterable) or isinstance(raw_edges, (str, bytes, dict)):
            return edges
        for raw_edge in raw_edges:
            if not isinstance(raw_edge, dict):
                continue
            try:
                edges.append(GraphEdge.model_validate(raw_edge))
            except Exception:
                continue
        return edges

    def _cleanup_session(self, session_key: str) -> None:
        session_items = self._items.get(session_key)
        if not session_items:
            return
        now = now_utc()
        expired_refs = [secret_ref for secret_ref, item in session_items.items() if item.expired(now)]
        for secret_ref in expired_refs:
            session_items.pop(secret_ref, None)
        if not session_items:
            self._items.pop(session_key, None)


def _fields_from_descriptor(descriptor: BlockDescriptor) -> list[SecretFieldRequirement]:
    schema = descriptor.config_schema
    properties = schema.get("properties") if isinstance(schema, Mapping) else None
    if not isinstance(properties, Mapping):
        return []
    required = set(schema.get("required", [])) if isinstance(schema.get("required"), list) else set()
    result: list[SecretFieldRequirement] = []
    for name, raw_property in properties.items():
        if name in SECRET_REF_FIELDS or not isinstance(name, str) or not isinstance(raw_property, Mapping):
            continue
        secret = _is_secret_property(raw_property)
        public_credential = _is_public_credential_property(raw_property)
        if not secret and not public_credential:
            continue
        title = raw_property.get("title")
        description = raw_property.get("description")
        result.append(
            SecretFieldRequirement(
                name=name,
                title=title if isinstance(title, str) else None,
                description=description if isinstance(description, str) else None,
                secret=secret,
                required=name in required,
                config_path=name,
            ),
        )
    return result


def _is_secret_property(data: Mapping[str, Any]) -> bool:
    if any(data.get(key) is True for key in SECRET_METADATA_KEYS):
        return True
    if data.get("x-calcchain-credential") == "secret":
        return True
    return data.get("format") == "password" or data.get("writeOnly") is True


def _is_public_credential_property(data: Mapping[str, Any]) -> bool:
    if any(data.get(key) is True for key in PUBLIC_METADATA_KEYS):
        return True
    return data.get("x-calcchain-credential") == "public"


def secret_ref_for_graph_node(node: GraphNode) -> str:
    raw_value = node.config.get("credential_ref") or node.config.get("secret_ref")
    if isinstance(raw_value, str) and raw_value:
        return raw_value
    payload = {"node_id": node.id, "node_type": node.type}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return f"secret:graph:{digest[:24]}"


def session_key_from_token_or_header(raw_value: str | None) -> str:
    if not raw_value:
        raw_value = "local-dev-session"
    return hashlib.sha256(raw_value.encode("utf-8")).hexdigest()
