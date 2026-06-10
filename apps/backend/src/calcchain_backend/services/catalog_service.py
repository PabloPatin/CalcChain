from __future__ import annotations

from calcchain_backend.schemas.catalog import BlockDescriptor, CatalogResponse, ConnectionRule, PortDescriptor
from calcchain_backend.services.plugin_service import PluginService


class CatalogService:
    """Builds the frontend catalog from built-in descriptors and enabled plugins."""

    def __init__(self, plugin_service: PluginService) -> None:
        self._plugin_service = plugin_service

    def get_catalog(self) -> CatalogResponse:
        plugins = self._plugin_service.list_plugins()
        enabled_plugin_ids = [plugin.id for plugin in plugins if plugin.enabled]
        blocks = self._base_blocks()

        if "calcchain.svn" in enabled_plugin_ids:
            blocks.extend(self._svn_blocks())

        return CatalogResponse(
            catalog_version=self._catalog_version(enabled_plugin_ids),
            port_kinds=["auth", "input", "rule-set", "mapped", "code", "env", "artifact", "target"],
            blocks=blocks,
            connection_rules=self.get_connection_rules(),
            plugins=enabled_plugin_ids,
        )

    def get_connection_rules(self) -> list[ConnectionRule]:
        return [
            ConnectionRule(id="auth-to-auth", from_kind="auth", to_kind="auth", description="Auth block to auth input"),
            ConnectionRule(id="input-to-rule-set", from_kind="input", to_kind="rule-set", description="Input source to rule set"),
            ConnectionRule(id="mapped-to-calc-input", from_kind="mapped", to_kind="calculation.input", description="Mapped inputs to calculation input"),
            ConnectionRule(id="input-to-calc-input", from_kind="input", to_kind="calculation.input", description="Raw input source to calculation input"),
            ConnectionRule(id="code-to-calc-code", from_kind="code", to_kind="calculation.code", description="Code source to calculation code"),
            ConnectionRule(id="env-to-calc-env", from_kind="env", to_kind="calculation.env", description="Environment to calculation"),
            ConnectionRule(id="output-to-artifact", from_kind="calculation.output", to_kind="artifact", description="Calculation output to artifact"),
            ConnectionRule(id="artifact-to-target", from_kind="artifact", to_kind="target", description="Artifact to target output"),
            ConnectionRule(id="artifact-to-calc-input", from_kind="artifact", to_kind="calculation.input", description="Previous artifact as next calculation input"),
        ]

    @staticmethod
    def _catalog_version(enabled_plugin_ids: list[str]) -> str:
        plugins_part = "+".join(sorted(enabled_plugin_ids)) or "no-plugins"
        return f"builtin-2026-05-24:{plugins_part}"

    @staticmethod
    def _base_blocks() -> list[BlockDescriptor]:
        return [
            BlockDescriptor(
                type="source.local.input",
                title="Local Input Source",
                category="Input",
                description="Input data from a local directory or file.",
                ports=[PortDescriptor(id="output", title="Input", direction="output", kind="input")],
                config_schema={"type": "object", "properties": {"path": {"type": "string", "title": "Path"}}, "required": ["path"]},
            ),
            BlockDescriptor(
                type="source.local.code",
                title="Local Code Source",
                category="Code",
                description="Calculation code from a local directory.",
                ports=[PortDescriptor(id="output", title="Code", direction="output", kind="code")],
                config_schema={"type": "object", "properties": {"path": {"type": "string", "title": "Path"}}, "required": ["path"]},
            ),
            BlockDescriptor(
                type="rule-set",
                title="Rule Set",
                category="Transform",
                description="Mapping rules applied to input files.",
                ports=[
                    PortDescriptor(id="source", title="Source", direction="input", kind="rule-set", required=True, max_connections=1),
                    PortDescriptor(id="mapped", title="Mapped", direction="output", kind="mapped"),
                ],
                config_schema={"type": "object", "properties": {"rules_path": {"type": "string", "title": "Rules file"}}},
            ),
            BlockDescriptor(
                type="calculation",
                title="Calculation",
                category="Run",
                description="Executable calculation step.",
                ports=[
                    PortDescriptor(id="input", title="Input", direction="input", kind="calculation.input"),
                    PortDescriptor(id="code", title="Code", direction="input", kind="calculation.code", required=True, max_connections=1),
                    PortDescriptor(id="env", title="Env", direction="input", kind="calculation.env"),
                    PortDescriptor(id="output", title="Output", direction="output", kind="calculation.output"),
                ],
                config_schema={
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "title": "Command"},
                        "working_directory": {"type": "string", "title": "Working directory"},
                        "stdin_mode": {
                            "type": "string",
                            "title": "Stdin mode",
                            "enum": ["none", "script"],
                            "default": "none",
                        },
                        "stdin_text": {
                            "type": "string",
                            "title": "Stdin text",
                            "default": "",
                            "format": "textarea",
                        },
                        "encoding": {"type": "string", "title": "Encoding", "default": "utf-8"},
                        "timeout_seconds": {"type": ["integer", "null"], "title": "Timeout seconds", "default": None},
                    },
                    "required": ["command"],
                },
            ),
            BlockDescriptor(
                type="env.public",
                title="Public Env",
                category="Environment",
                description="Plain runtime environment variable.",
                ports=[PortDescriptor(id="output", title="Env", direction="output", kind="env")],
                config_schema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "title": "Name"},
                        "value": {"type": "string", "title": "Value"},
                    },
                    "required": ["name", "value"],
                },
            ),
            BlockDescriptor(
                type="env.secret",
                title="Secret Env",
                category="Environment",
                description="Secret runtime environment variable resolved through backend session secrets.",
                ports=[PortDescriptor(id="output", title="Env", direction="output", kind="env")],
                config_schema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "title": "Name"},
                        "value": {
                            "type": "string",
                            "title": "Value",
                            "format": "password",
                            "writeOnly": True,
                            "x-calcchain-credential": "secret",
                            "x-calcchain-secret": True,
                        },
                    },
                    "required": ["name", "value"],
                },
            ),
            BlockDescriptor(
                type="artifact.output",
                title="Artifact Output",
                category="Output",
                description="Produced artifact declaration.",
                ports=[
                    PortDescriptor(id="source", title="Source", direction="input", kind="artifact", required=True),
                    PortDescriptor(id="artifact", title="Artifact", direction="output", kind="artifact"),
                ],
                config_schema={"type": "object", "properties": {"name": {"type": "string", "title": "Name"}}},
            ),
            BlockDescriptor(
                type="target.local",
                title="Local Target Output",
                category="Target",
                description="Publish artifact to a local target path.",
                ports=[PortDescriptor(id="artifact", title="Artifact", direction="input", kind="target", required=True)],
                config_schema={"type": "object", "properties": {"path": {"type": "string", "title": "Path"}}, "required": ["path"]},
            ),
            BlockDescriptor(
                type="auth.login-password",
                title="Login-Password Auth",
                category="Auth",
                description="Credential reference block. Secret values are stored through the backend secrets API.",
                ports=[PortDescriptor(id="auth", title="Auth", direction="output", kind="auth")],
                config_schema={
                    "type": "object",
                    "properties": {
                        "username": {
                            "type": "string",
                            "title": "Username",
                            "x-calcchain-credential": "public",
                        },
                        "password": {
                            "type": "string",
                            "title": "Password",
                            "format": "password",
                            "writeOnly": True,
                            "x-calcchain-credential": "secret",
                            "x-calcchain-secret": True,
                        },
                        "credential_ref": {"type": "string", "title": "Credential reference"},
                    },
                    "required": ["username", "password"],
                },
            ),
        ]

    @staticmethod
    def _svn_blocks() -> list[BlockDescriptor]:
        return [
            BlockDescriptor(
                type="source.svn.input",
                title="SVN Input Source",
                category="Input",
                description="Input data from SVN.",
                plugin_id="calcchain.svn",
                ports=[
                    PortDescriptor(id="auth", title="Auth", direction="input", kind="auth", max_connections=1),
                    PortDescriptor(id="output", title="Input", direction="output", kind="input"),
                ],
                config_schema={
                    "type": "object",
                    "properties": {
                        "location": {"type": "string", "title": "SVN URL"},
                        "path": {"type": "string", "title": "Path"},
                        "revision": {"type": "string", "title": "Revision"},
                    },
                    "required": ["location", "path"],
                },
            ),
            BlockDescriptor(
                type="source.svn.code",
                title="SVN Code Source",
                category="Code",
                description="Calculation code from SVN.",
                plugin_id="calcchain.svn",
                ports=[
                    PortDescriptor(id="auth", title="Auth", direction="input", kind="auth", max_connections=1),
                    PortDescriptor(id="output", title="Code", direction="output", kind="code"),
                ],
                config_schema={
                    "type": "object",
                    "properties": {
                        "location": {"type": "string", "title": "SVN URL"},
                        "path": {"type": "string", "title": "Path"},
                        "revision": {"type": "string", "title": "Revision"},
                    },
                    "required": ["location", "path"],
                },
            ),
            BlockDescriptor(
                type="target.svn",
                title="SVN Target Output",
                category="Target",
                description="Publish artifact to SVN.",
                plugin_id="calcchain.svn",
                ports=[
                    PortDescriptor(id="auth", title="Auth", direction="input", kind="auth", max_connections=1),
                    PortDescriptor(id="artifact", title="Artifact", direction="input", kind="target", required=True),
                ],
                config_schema={
                    "type": "object",
                    "properties": {
                        "location": {"type": "string", "title": "SVN URL"},
                        "path": {"type": "string", "title": "Path"},
                    },
                    "required": ["location", "path"],
                },
            ),
        ]
