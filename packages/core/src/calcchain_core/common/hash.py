from collections.abc import Iterable
import hashlib
import json
from pathlib import Path
from typing import Any

from ..utils.files import normalize_path


def sha256_dict(data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open('rb') as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b''):
            hasher.update(chunk)
    return hasher.hexdigest()


def tree_sha256(entries: Iterable[tuple[str, str]]) -> str:
    hasher = hashlib.sha256()
    normalized_entries = sorted(
        (normalize_path(work_path), file_hash.lower()) for work_path, file_hash in entries
    )
    for work_path, file_hash in normalized_entries:
        hasher.update(work_path.encode('utf-8'))
        hasher.update(b'\0')
        hasher.update(file_hash.encode('ascii'))
        hasher.update(b'\n')
    return hasher.hexdigest()
