from pathlib import Path


def get_files_in_dir(
        target_dir: Path,
        *,
        base_dir: Path | None = None,
        ) -> list[Path]:
    target_dir = target_dir.resolve()
    files = [file for file in target_dir.rglob('*') if file.is_file()]
    if base_dir:
        files = [file.relative_to(base_dir.resolve()) for file in files]
    return files


def _test_get_files_in_dir(
        target_dir: Path,
        base_dir: Path | None = None,
        ) -> None:
    for file in get_files_in_dir(target_dir, base_dir=base_dir):
        print(file)
    print()


def main() -> None:
    target_dir = Path('test_dir')
    _test_get_files_in_dir(target_dir, base_dir=None)
    _test_get_files_in_dir(target_dir, base_dir=target_dir)


if __name__ == '__main__':
    main()
