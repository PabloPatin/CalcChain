from pathlib import Path
from typing import Any
import json


def read_json(path: Path) -> dict[str, Any]:
    with Path(path).open('r', encoding='utf-8') as file:
        return json.load(file)


def write_json(data: dict[str, Any], path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + '\n',
        encoding='utf-8',
    )
