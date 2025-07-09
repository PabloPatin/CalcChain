import shutil
import socket
from collections.abc import Callable
from functools import wraps
from pathlib import Path

from workspace_management.loaders.base import BaseLoader, LoaderError
from workspace_management.mapping import create_file_translation_map
from workspace_management.simple_config import config


def raise_error(method: Callable) -> Callable:
    @wraps(method)
    def wrapper(*_, **__) -> ...:
        try:
            return method(*_, **__)
        except OSError as err:
            raise LoaderError(err.__repr__())

    return wrapper


@config
class LocalLoaderConfig:
    type: str
    path: str


class LocalLoader(BaseLoader[LocalLoaderConfig]):
    _type = 'local'
    _config_cls = LocalLoaderConfig

    @property
    def info(self) -> dict:
        return (
                self.config.to_dict() |
                {'hostname': socket.gethostname(),
                 'versionable': False}
        )

    @property
    @raise_error
    def src_files(self) -> list[Path]:
        target_dir = Path(self.config.path).resolve()
        if not target_dir.is_dir():
            raise FileNotFoundError(f'Не найдена директория {target_dir}')
        files = [file for file in target_dir.rglob('*') if file.is_file()]
        files = [file.relative_to(target_dir.resolve()) for file in files]
        return files

    @raise_error
    def fetch_data(self, dst_dir: str | Path, *, rules: list | None = None) -> None:
        if rules is None:
            rules = [['.*', '<>']]

        file_translation_map = create_file_translation_map(
                files=self.src_files,
                rules=rules,
                additional_markers={'source:desc': Path(self.config.path).name},
                check_skipped_files=True,
                )

        for src_file, dst_file in file_translation_map.items():
            src_path = Path(self.config.path) / src_file
            dst_path = Path(dst_dir) / dst_file
            self._fetch_file(src_path, dst_path)

    def _fetch_file(self, src_file: str | Path, dst_path: str | Path) -> None:
        dst_path = Path(dst_path)
        if dst_path.exists():
            raise LoaderError(f'Невозможно перезаписать файл {dst_path}')
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_file, dst_path)
