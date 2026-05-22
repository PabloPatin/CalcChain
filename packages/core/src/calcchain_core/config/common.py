from pathlib import Path
import tomllib

import tomlkit


def read_toml(path: Path) -> dict:
    with Path(path).open('rb') as file:
        return tomllib.load(file)


def write_toml(data: dict, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='\n') as file:
        file.write(tomlkit.dumps(data))
