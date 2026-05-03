from pathlib import Path
import json
import tomllib

import tomlkit

from calcchain_core.models import (
    BuildConfig,
    BuildLock,
    Manifest,
    PublishConfig,
    PublishLock,
    RulesFile,
    RunConfig,
)


def read_build(path: Path) -> BuildConfig:
    return BuildConfig.from_dict(_read_toml(path), default_build_name=path.parent.name)


def write_build_lock(lock: BuildLock, path: Path) -> None:
    _write_toml(lock.to_dict(), path)


def read_build_lock(path: Path) -> BuildLock:
    return BuildLock.from_dict(_read_toml(path))


def read_run(path: Path) -> RunConfig:
    return RunConfig.from_dict(_read_toml(path))


def read_publish(path: Path) -> PublishConfig:
    return PublishConfig.from_dict(_read_toml(path))


def write_publish_lock(lock: PublishLock, path: Path) -> None:
    _write_toml(lock.to_dict(), path)


def read_rules(path: Path) -> RulesFile:
    with path.open('r', encoding='utf-8') as file:
        return RulesFile.from_dict(json.load(file))


def write_manifest(manifest: Manifest, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='\n') as file:
        json.dump(manifest.to_dict(), file, ensure_ascii=False, indent=2)
        file.write('\n')


def _read_toml(path: Path) -> dict:
    with path.open('rb') as file:
        return tomllib.load(file)


def _write_toml(data: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='\n') as file:
        file.write(tomlkit.dumps(data))
