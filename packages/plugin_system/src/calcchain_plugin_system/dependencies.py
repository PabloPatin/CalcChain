from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from json import JSONDecodeError
from pathlib import Path, PurePosixPath
from typing import Mapping

from calcchain_plugin_system.activation_plan import PluginActivationPlan
from calcchain_capabilities.errors import PluginDependencyError
from calcchain_plugin_system.metadata import PluginPackage


@dataclass(frozen=True)
class PluginIdentity:
    plugin_id: str
    plugin_version: str


@dataclass(frozen=True)
class RequirementRecord:
    plugin_id: str
    path: Path
    sha256: str


@dataclass(frozen=True)
class WheelLockEntry:
    file: str
    sha256: str


@dataclass(frozen=True)
class WheelLock:
    path: Path
    wheels: tuple[WheelLockEntry, ...]


@dataclass(frozen=True)
class PluginWheelLock:
    plugin_id: str
    wheel_dir: Path
    lock: WheelLock


@dataclass(frozen=True)
class WheelRecord:
    plugin_id: str
    file: str
    sha256: str
    path: Path
    source: str


@dataclass(frozen=True)
class PluginDependencyPlan:
    packages: tuple[PluginPackage, ...]
    requirements: tuple[RequirementRecord, ...]
    plugin_wheel_locks: tuple[PluginWheelLock, ...]
    shared_wheelhouse: Path | None
    installer_backend_version: str
    plugin_api_version: str
    python_version: str

    @property
    def active_plugins(self) -> tuple[PluginIdentity, ...]:
        return tuple(
            PluginIdentity(
                plugin_id=package.metadata.plugin_id,
                plugin_version=package.metadata.plugin_version,
            )
            for package in self.packages
        )


class WheelLockReader:
    def read(self, path: Path) -> WheelLock:
        try:
            with path.open('r', encoding='utf-8') as file:
                data = json.load(file)
        except OSError as exc:
            raise _dependency_error(
                'Cannot read wheel lock',
                code='plugin_wheel_lock_read_failed',
                safe_details={'lock_path': str(path)},
            ) from exc
        except JSONDecodeError as exc:
            raise _dependency_error(
                'Wheel lock is not valid JSON',
                code='plugin_wheel_lock_invalid_json',
                safe_details={'lock_path': str(path)},
            ) from exc
        if not isinstance(data, Mapping):
            raise _dependency_error(
                'Wheel lock must be a JSON object',
                code='plugin_wheel_lock_invalid',
                safe_details={'lock_path': str(path)},
            )
        wheels = data.get('wheels')
        if not isinstance(wheels, list):
            raise _dependency_error(
                'Wheel lock wheels field must be a list',
                code='plugin_wheel_lock_invalid',
                safe_details={'lock_path': str(path), 'field': 'wheels'},
            )
        return WheelLock(
            path=path,
            wheels=tuple(_wheel_entry_from_dict(item, lock_path=path) for item in wheels),
        )


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open('rb') as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b''):
            hasher.update(chunk)
    return hasher.hexdigest()


class PluginDependencyPlanner:
    def __init__(self, *, wheel_lock_reader: WheelLockReader | None = None) -> None:
        self._wheel_lock_reader = wheel_lock_reader or WheelLockReader()

    def plan(
        self,
        activation_plan: PluginActivationPlan,
        *,
        shared_wheelhouse: Path | None,
        installer_backend_version: str,
    ) -> PluginDependencyPlan:
        requirements: list[RequirementRecord] = []
        plugin_wheel_locks: list[PluginWheelLock] = []
        for package in activation_plan.enabled_packages:
            plugin_id = package.metadata.plugin_id
            requirements_path = _contained_package_path(
                package.root,
                package.metadata.dependencies.requirements,
                plugin_id=plugin_id,
            )
            if not requirements_path.is_file():
                raise _dependency_error(
                    'Plugin requirements file is missing',
                    plugin_id=plugin_id,
                    code='plugin_requirements_missing',
                    safe_details={
                        'plugin_id': plugin_id,
                        'requirements': package.metadata.dependencies.requirements,
                    },
                )
            requirements.append(
                RequirementRecord(
                    plugin_id=plugin_id,
                    path=requirements_path,
                    sha256=sha256_file(requirements_path),
                ),
            )

            wheel_dir = package.root / package.metadata.dependencies.wheels_path
            lock_path = wheel_dir / 'wheels.lock.json'
            wheel_lock = self._wheel_lock_reader.read(lock_path)
            plugin_wheel_locks.append(
                PluginWheelLock(plugin_id=plugin_id, wheel_dir=wheel_dir, lock=wheel_lock),
            )

        return PluginDependencyPlan(
            packages=activation_plan.enabled_packages,
            requirements=tuple(requirements),
            plugin_wheel_locks=tuple(plugin_wheel_locks),
            shared_wheelhouse=shared_wheelhouse,
            installer_backend_version=installer_backend_version,
            plugin_api_version=activation_plan.plugin_api_version,
            python_version=activation_plan.python_version,
        )


def verify_wheel_hashes(plan: PluginDependencyPlan) -> tuple[WheelRecord, ...]:
    records: list[WheelRecord] = []
    for plugin_wheel_lock in plan.plugin_wheel_locks:
        for locked_wheel in plugin_wheel_lock.lock.wheels:
            wheel_path, source = _find_locked_wheel(
                locked_wheel.file,
                plugin_wheel_lock.wheel_dir,
                plan.shared_wheelhouse,
            )
            actual_sha256 = sha256_file(wheel_path)
            if actual_sha256.lower() != locked_wheel.sha256.lower():
                raise _dependency_error(
                    'Wheel SHA-256 does not match lock',
                    plugin_id=plugin_wheel_lock.plugin_id,
                    code='plugin_wheel_hash_mismatch',
                    safe_details={
                        'plugin_id': plugin_wheel_lock.plugin_id,
                        'wheel': locked_wheel.file,
                        'expected_sha256': locked_wheel.sha256.lower(),
                        'actual_sha256': actual_sha256.lower(),
                    },
                )
            records.append(
                WheelRecord(
                    plugin_id=plugin_wheel_lock.plugin_id,
                    file=locked_wheel.file,
                    sha256=locked_wheel.sha256.lower(),
                    path=wheel_path,
                    source=source,
                ),
            )
    return tuple(records)


def compute_env_hash(plan: PluginDependencyPlan) -> str:
    wheel_material = [
        {
            'plugin_id': wheel_lock.plugin_id,
            'wheels': [
                {'file': entry.file, 'sha256': entry.sha256.lower()}
                for entry in sorted(wheel_lock.lock.wheels, key=lambda item: item.file)
            ],
        }
        for wheel_lock in plan.plugin_wheel_locks
    ]
    material = {
        'installer_backend_version': plan.installer_backend_version,
        'plugin_api_version': plan.plugin_api_version,
        'python_version': plan.python_version,
        'active_plugins': [
            {'plugin_id': plugin.plugin_id, 'plugin_version': plugin.plugin_version}
            for plugin in plan.active_plugins
        ],
        'requirements': [
            {'plugin_id': requirement.plugin_id, 'sha256': requirement.sha256.lower()}
            for requirement in plan.requirements
        ],
        'wheel_locks': wheel_material,
    }
    encoded = json.dumps(material, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _find_locked_wheel(
    wheel_file: str,
    plugin_wheel_dir: Path,
    shared_wheelhouse: Path | None,
) -> tuple[Path, str]:
    plugin_path = plugin_wheel_dir / wheel_file
    if plugin_path.is_file():
        return plugin_path, 'plugin'
    if shared_wheelhouse is not None:
        shared_path = shared_wheelhouse / wheel_file
        if shared_path.is_file():
            return shared_path, 'shared'
    raise _dependency_error(
        'Locked wheel file is missing',
        code='plugin_wheel_missing',
        safe_details={'wheel': wheel_file},
    )


def _wheel_entry_from_dict(data: object, *, lock_path: Path) -> WheelLockEntry:
    if not isinstance(data, Mapping):
        raise _dependency_error(
            'Wheel lock entry must be an object',
            code='plugin_wheel_lock_invalid',
            safe_details={'lock_path': str(lock_path)},
        )
    wheel_file = data.get('file')
    sha256 = data.get('sha256')
    if not isinstance(wheel_file, str) or not wheel_file:
        raise _dependency_error(
            'Wheel lock entry file must be a non-empty string',
            code='plugin_wheel_lock_invalid',
            safe_details={'lock_path': str(lock_path), 'field': 'file'},
        )
    if not isinstance(sha256, str) or not _is_sha256_hex(sha256):
        raise _dependency_error(
            'Wheel lock entry sha256 must be a SHA-256 hex digest',
            code='plugin_wheel_lock_invalid',
            safe_details={'lock_path': str(lock_path), 'wheel': wheel_file, 'field': 'sha256'},
        )
    if not _is_safe_wheel_file_name(wheel_file):
        raise _dependency_error(
            'Wheel lock entry file name is unsafe',
            code='plugin_wheel_name_unsafe',
            safe_details={'lock_path': str(lock_path), 'wheel': wheel_file},
        )
    return WheelLockEntry(file=wheel_file, sha256=sha256.lower())


def _is_safe_wheel_file_name(value: str) -> bool:
    if ':' in value:
        return False
    path = PurePosixPath(value.replace('\\', '/'))
    return (
        len(path.parts) == 1
        and path.name == value
        and not path.is_absolute()
        and path.name not in {'.', '..'}
    )


def _contained_package_path(root: Path, value: str, *, plugin_id: str) -> Path:
    if ':' in value:
        raise _unsafe_requirements_path(plugin_id=plugin_id, requirements=value)
    path = PurePosixPath(value.replace('\\', '/'))
    if path.is_absolute() or '..' in path.parts or path.name in {'', '.', '..'}:
        raise _unsafe_requirements_path(plugin_id=plugin_id, requirements=value)
    candidate = root.joinpath(*path.parts)
    try:
        candidate.resolve(strict=False).relative_to(root.resolve(strict=False))
    except (OSError, ValueError) as exc:
        raise _unsafe_requirements_path(plugin_id=plugin_id, requirements=value) from exc
    return candidate


def _unsafe_requirements_path(*, plugin_id: str, requirements: str) -> PluginDependencyError:
    return _dependency_error(
        'Plugin requirements path is unsafe',
        plugin_id=plugin_id,
        code='plugin_requirements_path_unsafe',
        safe_details={'plugin_id': plugin_id, 'requirements': requirements},
    )


def _is_sha256_hex(value: str) -> bool:
    if len(value) != 64:
        return False
    return all(character in '0123456789abcdefABCDEF' for character in value)


def _dependency_error(
    message: str,
    *,
    code: str,
    plugin_id: str | None = None,
    safe_details: Mapping[str, object] | None = None,
) -> PluginDependencyError:
    return PluginDependencyError(
        message,
        plugin_id=plugin_id,
        phase='dependency_plan',
        code=code,
        safe_details=safe_details,
    )


__all__ = [
    'PluginDependencyPlan',
    'PluginDependencyPlanner',
    'PluginIdentity',
    'PluginWheelLock',
    'RequirementRecord',
    'WheelLock',
    'WheelLockEntry',
    'WheelLockReader',
    'WheelRecord',
    'compute_env_hash',
    'verify_wheel_hashes',
]
