import shutil
import socket
from abc import ABCMeta
from collections.abc import Callable
from functools import wraps
from pathlib import Path

from workspace_management.mapping.search_files import get_files_in_dir
from workspace_management.simple_config import config
from .base import BaseFileHandler, BaseRecorder, BaseLoader, FileHandlerError


def raise_error(method: Callable) -> Callable:
    @wraps(method)
    def wrapper(*_, **__) -> ...:
        try:
            return method(*_, **__)
        except OSError as err:
            raise FileHandlerError(err.__repr__())

    return wrapper


@config
class LocalLoaderConfig:
    type: str
    path: str


@config
class LocalRecorderConfig:
    type: str
    path: str


class BaseLocalHandler(BaseFileHandler, metaclass=ABCMeta):
    _type = 'local'

    @property
    def is_versionable(self) -> bool:
        return False

    @property
    def info(self) -> dict:
        return {'hostname': socket.gethostname()} | super().info


class LocalLoader(BaseLocalHandler, BaseLoader):
    _config_cls = LocalLoaderConfig

    @property
    @raise_error
    def src_files(self) -> list[Path]:
        target_dir = Path(self.config.path).resolve()
        files = get_files_in_dir(target_dir, base_dir=target_dir)
        return files

    @raise_error
    def fetch_data(
            self,
            dst_dir: str | Path,
            *,
            rules: list | None = None,
            ensure_all_files: bool = False,
            ) -> dict[Path, Path]:
        file_translation_map = self._create_file_translation_map(
                rules=rules,
                additional_markers={'source:desc': Path(self.config.path).name},
                check_skipped=ensure_all_files,
                )

        for src_file, dst_file in file_translation_map.items():
            src_path = Path(self.config.path) / src_file
            dst_path = Path(dst_dir) / dst_file
            self._fetch_file(src_path, dst_path)

        return file_translation_map

    def _fetch_file(self, src_file: str | Path, dst_path: str | Path) -> None:
        dst_path = Path(dst_path)
        if dst_path.exists():
            raise FileHandlerError(f'Невозможно перезаписать файл {dst_path}')
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_file, dst_path)


class LocalRecorder(BaseLocalHandler, BaseRecorder):
    _config_cls = LocalRecorderConfig

    @raise_error
    def send_data(
            self,
            *,
            rules: list,
            ensure_all_files: bool = False,
            ) -> dict[Path, Path]:
        file_translation_map = self._create_file_translation_map(
                rules,
                check_skipped=ensure_all_files,
                )

        dst_dir = Path(self.config.path)
        self._check_dst_dir(dst_dir)

        for src_file, dst_file in file_translation_map.items():
            src_path = self.src_dir / src_file
            dst_path = dst_dir / dst_file
            if dst_path.exists():
                raise FileHandlerError(f'Невозможно перезаписать файл {dst_path}')
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dst_path)

        return file_translation_map

    def _check_dst_dir(self, dst_dir: Path) -> None:
        if any(dst_dir.iterdir()):
            raise FileHandlerError('Папка для выгрузки не пуста')
