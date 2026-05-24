from pathlib import Path


def get_files_in_dir(
    target_dir: Path,
    *,
    base_dir: Path | None = None,
    wildcard: str = '*',
) -> list[Path]:
    target_dir = target_dir.resolve()
    if not target_dir.is_dir():
        raise FileNotFoundError(f'directory not found: {target_dir}')
    files = [file for file in target_dir.rglob(wildcard) if file.is_file()]
    if base_dir:
        files = [file.relative_to(base_dir.resolve()) for file in files]
    return files
