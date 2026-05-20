from pathlib import Path
import tomllib

from calcchain_core.models import RunConfig


def read_run(path: Path) -> RunConfig:
    with Path(path).open('rb') as file:
        return RunConfig.from_dict(tomllib.load(file))
