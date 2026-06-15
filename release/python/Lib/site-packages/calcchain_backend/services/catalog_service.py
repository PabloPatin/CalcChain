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
            ConnectionRule(id="auth-to-auth", from_kind="auth", to_kind="auth", description="Блок доступа к входу доступа"),
            ConnectionRule(id="input-to-rule-set", from_kind="input", to_kind="rule-set", description="Источник данных к набору правил"),
            ConnectionRule(id="mapped-to-calc-input", from_kind="mapped", to_kind="calculation.input", description="Данные после правил к входу расчёта"),
            ConnectionRule(id="input-to-calc-input", from_kind="input", to_kind="calculation.input", description="Исходные данные к входу расчёта"),
            ConnectionRule(id="code-to-calc-code", from_kind="code", to_kind="calculation.code", description="Источник кода к коду расчёта"),
            ConnectionRule(id="env-to-calc-env", from_kind="env", to_kind="calculation.env", description="Окружение к расчёту"),
            ConnectionRule(id="output-to-artifact", from_kind="calculation.output", to_kind="artifact", description="Результат расчёта к артефакту"),
            ConnectionRule(id="artifact-to-target", from_kind="artifact", to_kind="target", description="Артефакт к папке результата"),
            ConnectionRule(id="artifact-to-calc-input", from_kind="artifact", to_kind="calculation.input", description="Предыдущий артефакт как вход следующего расчёта"),
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
                title="Локальный источник данных",
                category="Источники",
                description="Входные данные из локальной папки или файла.",
                ports=[PortDescriptor(id="output", title="Данные", direction="output", kind="input")],
                config_schema={"type": "object", "properties": {"path": {"type": "string", "title": "Путь"}}, "required": ["path"]},
            ),
            BlockDescriptor(
                type="source.local.code",
                title="Локальный источник кода",
                category="Код",
                description="Код расчёта из локальной папки.",
                ports=[PortDescriptor(id="output", title="Код", direction="output", kind="code")],
                config_schema={"type": "object", "properties": {"path": {"type": "string", "title": "Путь"}}, "required": ["path"]},
            ),
            BlockDescriptor(
                type="rule-set",
                title="Набор правил",
                category="Правила",
                description="Правила сопоставления для входных файлов.",
                ports=[
                    PortDescriptor(id="source", title="Источник", direction="input", kind="rule-set", required=True, max_connections=1),
                    PortDescriptor(id="mapped", title="После правил", direction="output", kind="mapped"),
                ],
                config_schema={"type": "object", "properties": {"rules_path": {"type": "string", "title": "Файл правил"}}},
            ),
            BlockDescriptor(
                type="calculation",
                title="Расчёт",
                category="Расчёт",
                description="Исполняемый шаг расчёта.",
                ports=[
                    PortDescriptor(id="input", title="Данные", direction="input", kind="calculation.input"),
                    PortDescriptor(id="code", title="Код", direction="input", kind="calculation.code", required=True, max_connections=1),
                    PortDescriptor(id="env", title="Окружение", direction="input", kind="calculation.env"),
                    PortDescriptor(id="output", title="Результат", direction="output", kind="calculation.output"),
                ],
                config_schema={
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "title": "Команда"},
                        "working_directory": {"type": "string", "title": "Рабочая папка"},
                        "stdin_mode": {
                            "type": "string",
                            "title": "Режим stdin",
                            "enum": ["none", "script"],
                            "default": "none",
                        },
                        "stdin_text": {
                            "type": "string",
                            "title": "Текст stdin",
                            "default": "",
                            "format": "textarea",
                        },
                        "encoding": {"type": "string", "title": "Кодировка", "default": "utf-8"},
                        "timeout_seconds": {"type": ["integer", "null"], "title": "Тайм-аут, сек", "default": None},
                    },
                    "required": ["command"],
                },
            ),
            BlockDescriptor(
                type="env.public",
                title="Переменная окружения",
                category="Окружение",
                description="Обычная переменная окружения для запуска.",
                ports=[PortDescriptor(id="output", title="Окружение", direction="output", kind="env")],
                config_schema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "title": "Имя"},
                        "value": {"type": "string", "title": "Значение"},
                    },
                    "required": ["name", "value"],
                },
            ),
            BlockDescriptor(
                type="env.secret",
                title="Секретная переменная окружения",
                category="Окружение",
                description="Секретная переменная окружения из хранилища сессии.",
                ports=[PortDescriptor(id="output", title="Окружение", direction="output", kind="env")],
                config_schema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "title": "Имя"},
                        "value": {
                            "type": "string",
                            "title": "Значение",
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
                title="Выходной артефакт",
                category="Результаты",
                description="Описание артефакта, созданного расчётом.",
                ports=[
                    PortDescriptor(id="source", title="Источник", direction="input", kind="artifact", required=True),
                    PortDescriptor(id="artifact", title="Артефакт", direction="output", kind="artifact"),
                ],
                config_schema={"type": "object", "properties": {"name": {"type": "string", "title": "Имя"}}},
            ),
            BlockDescriptor(
                type="target.local",
                title="Локальная папка результата",
                category="Назначения",
                description="Публикация артефакта в локальную папку.",
                ports=[PortDescriptor(id="artifact", title="Артефакт", direction="input", kind="target", required=True)],
                config_schema={"type": "object", "properties": {"path": {"type": "string", "title": "Путь"}}, "required": ["path"]},
            ),
            BlockDescriptor(
                type="auth.login-password",
                title="Логин и пароль",
                category="Доступ",
                description="Блок учётных данных. Секреты хранятся через API backend.",
                ports=[PortDescriptor(id="auth", title="Доступ", direction="output", kind="auth")],
                config_schema={
                    "type": "object",
                    "properties": {
                        "username": {
                            "type": "string",
                            "title": "Логин",
                            "x-calcchain-credential": "public",
                        },
                        "password": {
                            "type": "string",
                            "title": "Пароль",
                            "format": "password",
                            "writeOnly": True,
                            "x-calcchain-credential": "secret",
                            "x-calcchain-secret": True,
                        },
                        "credential_ref": {"type": "string", "title": "Ссылка на секрет"},
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
                title="SVN-источник данных",
                category="Источники",
                description="Входные данные из SVN.",
                plugin_id="calcchain.svn",
                ports=[
                    PortDescriptor(id="auth", title="Доступ", direction="input", kind="auth", max_connections=1),
                    PortDescriptor(id="output", title="Данные", direction="output", kind="input"),
                ],
                config_schema={
                    "type": "object",
                    "properties": {
                        "location": {"type": "string", "title": "SVN URL"},
                        "path": {"type": "string", "title": "Путь"},
                        "revision": {"type": "string", "title": "Ревизия"},
                    },
                    "required": ["location", "path"],
                },
            ),
            BlockDescriptor(
                type="source.svn.code",
                title="SVN-источник кода",
                category="Код",
                description="Код расчёта из SVN.",
                plugin_id="calcchain.svn",
                ports=[
                    PortDescriptor(id="auth", title="Доступ", direction="input", kind="auth", max_connections=1),
                    PortDescriptor(id="output", title="Код", direction="output", kind="code"),
                ],
                config_schema={
                    "type": "object",
                    "properties": {
                        "location": {"type": "string", "title": "SVN URL"},
                        "path": {"type": "string", "title": "Путь"},
                        "revision": {"type": "string", "title": "Ревизия"},
                    },
                    "required": ["location", "path"],
                },
            ),
            BlockDescriptor(
                type="target.svn",
                title="SVN-папка результата",
                category="Назначения",
                description="Публикация артефакта в SVN.",
                plugin_id="calcchain.svn",
                ports=[
                    PortDescriptor(id="auth", title="Доступ", direction="input", kind="auth", max_connections=1),
                    PortDescriptor(id="artifact", title="Артефакт", direction="input", kind="target", required=True),
                ],
                config_schema={
                    "type": "object",
                    "properties": {
                        "location": {"type": "string", "title": "SVN URL"},
                        "path": {"type": "string", "title": "Путь"},
                    },
                    "required": ["location", "path"],
                },
            ),
        ]
