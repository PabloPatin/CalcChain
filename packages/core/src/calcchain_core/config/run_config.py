from pathlib import Path

from calcchain_core.config.common import read_toml
from calcchain_core.models import RunConfig


def read_run(path: Path) -> RunConfig:
    return RunConfig.from_dict(read_toml(Path(path)))
