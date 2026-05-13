from __future__ import annotations

from dataclasses import dataclass
import json
from json import JSONDecodeError
from pathlib import Path
from typing import Mapping

from calcchain_core.plugins.dependencies import PluginDependencyPlan, WheelRecord, compute_env_hash
from calcchain_core.plugins.errors import PluginDependencyError

PLUGIN_ENV_LOCK_NAME = 'plugin-env.lock.json'


@dataclass(frozen=True)
class LockedPlugin:
    plugin_id: str
    plugin_version: str

    def to_dict(self) -> dict[str, str]:
        return {'plugin_id': self.plugin_id, 'plugin_version': self.plugin_version}

    @classmethod
    def from_dict(cls, data: object) -> LockedPlugin:
        if not isinstance(data, Mapping):
            raise _env_lock_error('Locked plugin entry must be an object')
        return cls(
            plugin_id=_required_str(data, 'plugin_id'),
            plugin_version=_required_str(data, 'plugin_version'),
        )


@dataclass(frozen=True)
class LockedRequirement:
    plugin_id: str
    sha256: str

    def to_dict(self) -> dict[str, str]:
        return {'plugin_id': self.plugin_id, 'sha256': self.sha256}

    @classmethod
    def from_dict(cls, data: object) -> LockedRequirement:
        if not isinstance(data, Mapping):
            raise _env_lock_error('Locked requirement entry must be an object')
        return cls(
            plugin_id=_required_str(data, 'plugin_id'),
            sha256=_required_sha256(data, 'sha256'),
        )


@dataclass(frozen=True)
class LockedWheel:
    plugin_id: str
    file: str
    sha256: str
    source: str

    def to_dict(self) -> dict[str, str]:
        return {
            'plugin_id': self.plugin_id,
            'file': self.file,
            'sha256': self.sha256,
            'source': self.source,
        }

    @classmethod
    def from_dict(cls, data: object) -> LockedWheel:
        if not isinstance(data, Mapping):
            raise _env_lock_error('Locked wheel entry must be an object')
        return cls(
            plugin_id=_required_str(data, 'plugin_id'),
            file=_required_str(data, 'file'),
            sha256=_required_sha256(data, 'sha256'),
            source=_required_str(data, 'source'),
        )


@dataclass(frozen=True)
class PluginEnvLock:
    env_hash: str
    python_version: str
    plugin_api_version: str
    installer_backend_version: str
    active_plugins: tuple[LockedPlugin, ...]
    requirements: tuple[LockedRequirement, ...]
    resolved_dependencies: tuple[str, ...]
    used_wheels: tuple[LockedWheel, ...]

    @classmethod
    def from_plan(
        cls,
        plan: PluginDependencyPlan,
        *,
        used_wheels: tuple[WheelRecord, ...],
        resolved_dependencies: tuple[str, ...] = (),
    ) -> PluginEnvLock:
        return cls(
            env_hash=compute_env_hash(plan),
            python_version=plan.python_version,
            plugin_api_version=plan.plugin_api_version,
            installer_backend_version=plan.installer_backend_version,
            active_plugins=tuple(
                LockedPlugin(plugin.plugin_id, plugin.plugin_version)
                for plugin in plan.active_plugins
            ),
            requirements=tuple(
                LockedRequirement(requirement.plugin_id, requirement.sha256.lower())
                for requirement in plan.requirements
            ),
            resolved_dependencies=tuple(resolved_dependencies),
            used_wheels=tuple(
                LockedWheel(
                    plugin_id=wheel.plugin_id,
                    file=wheel.file,
                    sha256=wheel.sha256.lower(),
                    source=wheel.source,
                )
                for wheel in used_wheels
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            'env_hash': self.env_hash,
            'python_version': self.python_version,
            'plugin_api_version': self.plugin_api_version,
            'installer_backend_version': self.installer_backend_version,
            'active_plugins': [plugin.to_dict() for plugin in self.active_plugins],
            'requirements': [requirement.to_dict() for requirement in self.requirements],
            'resolved_dependencies': list(self.resolved_dependencies),
            'used_wheels': [wheel.to_dict() for wheel in self.used_wheels],
        }

    @classmethod
    def from_dict(cls, data: object) -> PluginEnvLock:
        if not isinstance(data, Mapping):
            raise _env_lock_error('Plugin environment lock must be a JSON object')
        resolved = data.get('resolved_dependencies', ())
        if not isinstance(resolved, list):
            raise _env_lock_error('resolved_dependencies must be a list')
        if not all(isinstance(item, str) for item in resolved):
            raise _env_lock_error('resolved_dependencies must contain strings')
        return cls(
            env_hash=_required_sha256(data, 'env_hash'),
            python_version=_required_str(data, 'python_version'),
            plugin_api_version=_required_str(data, 'plugin_api_version'),
            installer_backend_version=_required_str(data, 'installer_backend_version'),
            active_plugins=tuple(
                LockedPlugin.from_dict(item) for item in _required_list(data, 'active_plugins')
            ),
            requirements=tuple(
                LockedRequirement.from_dict(item) for item in _required_list(data, 'requirements')
            ),
            resolved_dependencies=tuple(resolved),
            used_wheels=tuple(
                LockedWheel.from_dict(item) for item in _required_list(data, 'used_wheels')
            ),
        )


def write_plugin_env_lock(lock: PluginEnvLock, path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(lock.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + '\n',
            encoding='utf-8',
        )
    except OSError as exc:
        raise _env_lock_error(
            'Cannot write plugin environment lock',
            code='plugin_env_lock_write_failed',
            safe_details={'lock_path': str(path)},
        ) from exc


def read_plugin_env_lock(path: Path) -> PluginEnvLock:
    try:
        with path.open('r', encoding='utf-8') as file:
            data = json.load(file)
    except OSError as exc:
        raise _env_lock_error(
            'Cannot read plugin environment lock',
            code='plugin_env_lock_read_failed',
            safe_details={'lock_path': str(path)},
        ) from exc
    except JSONDecodeError as exc:
        raise _env_lock_error(
            'Plugin environment lock is not valid JSON',
            code='plugin_env_lock_invalid_json',
            safe_details={'lock_path': str(path)},
        ) from exc
    return PluginEnvLock.from_dict(data)


def verify_plugin_env_lock(env_dir: Path, expected_hash: str) -> PluginEnvLock:
    lock = read_plugin_env_lock(env_dir / PLUGIN_ENV_LOCK_NAME)
    if lock.env_hash != expected_hash:
        raise _env_lock_error(
            'Plugin environment lock hash does not match expected environment hash',
            code='plugin_env_lock_hash_mismatch',
            safe_details={'expected_hash': expected_hash, 'actual_hash': lock.env_hash},
        )
    return lock


def _required_str(data: Mapping[str, object], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value:
        raise _env_lock_error(
            'Plugin environment lock field must be a non-empty string',
            safe_details={'field': field},
        )
    return value


def _required_sha256(data: Mapping[str, object], field: str) -> str:
    value = _required_str(data, field)
    if len(value) != 64 or not all(character in '0123456789abcdefABCDEF' for character in value):
        raise _env_lock_error(
            'Plugin environment lock field must be a SHA-256 hex digest',
            safe_details={'field': field},
        )
    return value.lower()


def _required_list(data: Mapping[str, object], field: str) -> list[object]:
    value = data.get(field)
    if not isinstance(value, list):
        raise _env_lock_error(
            'Plugin environment lock field must be a list',
            safe_details={'field': field},
        )
    return value


def _env_lock_error(
    message: str,
    *,
    code: str = 'plugin_env_lock_invalid',
    safe_details: Mapping[str, object] | None = None,
) -> PluginDependencyError:
    return PluginDependencyError(
        message,
        phase='dependency_plan',
        code=code,
        safe_details=safe_details,
    )


__all__ = [
    'LockedPlugin',
    'LockedRequirement',
    'LockedWheel',
    'PLUGIN_ENV_LOCK_NAME',
    'PluginEnvLock',
    'read_plugin_env_lock',
    'verify_plugin_env_lock',
    'write_plugin_env_lock',
]
