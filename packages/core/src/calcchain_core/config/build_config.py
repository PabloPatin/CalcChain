from pathlib import Path

from calcchain_core.config.common import read_toml, write_toml
from calcchain_core.models import BuildConfig, BuildLock


def read_build(path: Path) -> BuildConfig:
    path = Path(path)
    return BuildConfig.from_dict(read_toml(path), default_build_name=path.parent.name)


def write_build_lock(lock: BuildLock, path: Path) -> None:
    write_toml(lock.to_dict(), path)


def read_build_lock(path: Path) -> BuildLock:
    return BuildLock.from_dict(read_toml(path))
