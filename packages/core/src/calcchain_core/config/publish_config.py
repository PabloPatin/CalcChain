from pathlib import Path

from calcchain_core.config.common import read_toml, write_toml
from calcchain_core.models import PublishConfig, PublishLock


def read_publish(path: Path) -> PublishConfig:
    return PublishConfig.from_dict(read_toml(path))


def write_publish_lock(lock: PublishLock, path: Path) -> None:
    write_toml(lock.to_dict(), path)
