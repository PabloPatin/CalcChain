from collections.abc import Iterable
import hashlib
from pathlib import Path


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open('rb') as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b''):
            hasher.update(chunk)
    return hasher.hexdigest()


def tree_sha256(entries: Iterable[tuple[str, str]]) -> str:
    hasher = hashlib.sha256()
    normalized_entries = sorted(
        (_normalize_work_path(work_path), file_hash.lower()) for work_path, file_hash in entries
    )
    for work_path, file_hash in normalized_entries:
        hasher.update(work_path.encode('utf-8'))
        hasher.update(b'\0')
        hasher.update(file_hash.encode('ascii'))
        hasher.update(b'\n')
    return hasher.hexdigest()


def _normalize_work_path(path: str) -> str:
    return path.replace('\\', '/').strip('/')
