from __future__ import annotations

from dataclasses import dataclass
import json
from json import JSONDecodeError
from pathlib import Path
from typing import Mapping

from calcchain_core.plugins.errors import PluginError


@dataclass(frozen=True)
class PluginSettings:
    enabled_plugins: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: object) -> PluginSettings:
        if not isinstance(data, Mapping):
            raise _settings_error('Plugin settings must be a JSON object')
        enabled = data.get('enabled_plugins', ())
        if not isinstance(enabled, list):
            raise _settings_error('enabled_plugins must be a list of plugin ids')
        plugin_ids: list[str] = []
        for item in enabled:
            if not isinstance(item, str) or not item:
                raise _settings_error('enabled_plugins must contain non-empty plugin id strings')
            plugin_ids.append(item)
        return cls(enabled_plugins=tuple(plugin_ids))

    def to_dict(self) -> dict[str, list[str]]:
        return {'enabled_plugins': list(self.enabled_plugins)}


class PluginSettingsStore:
    def __init__(self, settings_path: Path) -> None:
        self.settings_path = settings_path

    def load(self) -> PluginSettings:
        if not self.settings_path.exists():
            return PluginSettings()
        try:
            with self.settings_path.open('r', encoding='utf-8') as file:
                data = json.load(file)
        except OSError as exc:
            raise _settings_error(
                'Cannot read plugin settings',
                code='plugin_settings_read_failed',
                settings_path=self.settings_path,
            ) from exc
        except JSONDecodeError as exc:
            raise _settings_error(
                'Plugin settings are not valid JSON',
                code='plugin_settings_invalid_json',
                settings_path=self.settings_path,
            ) from exc
        return PluginSettings.from_dict(data)

    def save(self, settings: PluginSettings) -> None:
        try:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            self.settings_path.write_text(
                json.dumps(settings.to_dict(), ensure_ascii=False, indent=2) + '\n',
                encoding='utf-8',
            )
        except OSError as exc:
            raise _settings_error(
                'Cannot write plugin settings',
                code='plugin_settings_write_failed',
                settings_path=self.settings_path,
            ) from exc


def _settings_error(
    message: str,
    *,
    code: str = 'plugin_settings_invalid',
    settings_path: Path | None = None,
) -> PluginError:
    details: dict[str, object] = {}
    if settings_path is not None:
        details['settings_path'] = str(settings_path)
    return PluginError(
        message,
        phase='dependency_plan',
        code=code,
        safe_details=details,
    )


__all__ = ['PluginSettings', 'PluginSettingsStore']
