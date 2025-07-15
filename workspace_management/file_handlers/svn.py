import shutil
import tempfile
from abc import ABCMeta
from collections.abc import Callable
from functools import wraps
from pathlib import Path, PurePath

from svn import SvnClient, SvnError
from svn.data_structures import Depth
from workspace_management.file_handlers.base import BaseLoader, FileHandlerError, \
    BaseFileHandler, BaseRecorder, AuthorizationError
from workspace_management.simple_config import config


def raise_error(method: Callable) -> Callable:
    wrong_repo_err_codes = ('E180001', 'E155007', 'E731001', 'E730061')
    wrong_node_err_codes = ('E200009',)
    wrong_revision_err_codes = ('E160006',)
    cannot_rewrite_file_err_codes = ('E160020',)
    cannot_get_credentials_err_codes = ('E170001',)

    def match_error_codes(
            error_codes: tuple[str, ...],
            match_codes: tuple[str, ...],
            ) -> bool:
        return any(code in match_codes for code in error_codes)

    @wraps(method)
    def wrapper(*_, **__) -> ...:
        try:
            return method(*_, **__)
        except SvnError as err:
            if match_error_codes(err.error_codes, wrong_repo_err_codes):
                raise FileHandlerError(
                        f'\nРепозиторий не найден\n{err.stderr}',
                        )
            elif match_error_codes(err.error_codes, wrong_node_err_codes):
                raise FileHandlerError(
                        f'\nФайл в репозитории не найден\n{err.stderr}',
                        )
            elif match_error_codes(err.error_codes, wrong_revision_err_codes):
                raise FileHandlerError(
                        f'\nНеверно указана ревизия\n{err.stderr}',
                        )
            elif match_error_codes(err.error_codes, cannot_rewrite_file_err_codes):
                raise FileHandlerError(
                        f'\nНевозможно перезаписать файл\n{err.stderr}',
                        )
            elif match_error_codes(err.error_codes, cannot_get_credentials_err_codes):
                raise AuthorizationError(
                        _type=BaseSvnHandler._type,  # noqa pycharm
                        source_address=err.url,
                        auth_parameters=['username', 'password'],
                        )
            return None

    return wrapper


@config
class SvnLoaderConfig:
    type: str
    url: str
    revision: str | int = 'HEAD'


@config
class SvnRecorderConfig:
    type: str
    url: str


class BaseSvnHandler(BaseFileHandler, metaclass=ABCMeta):
    _type = 'svn'

    @property
    def is_versionable(self) -> bool:
        return True

    @raise_error
    def __init__(self, configs: dict, **__) -> None:
        BaseFileHandler.__init__(self, configs, **__)
        self._auth_data = self._credentials.get(self.config.url, {})
        self._client = SvnClient(
                self.config.url,
                username=self._auth_data.get('username'),
                password=self._auth_data.get('password'),
                )

    @property
    def info(self) -> dict:
        return {'repo_uuid': self._client.info().repository_uuid} | super().info


class SvnLoader(BaseSvnHandler, BaseLoader):
    _config_cls = SvnLoaderConfig

    @raise_error
    def __init__(self, configs: dict, **__) -> None:
        BaseSvnHandler.__init__(self, configs, **__)
        self.config.revision = self._client.info(
                revision=self.config.revision,
                ).entry_revision

    @property
    @raise_error
    def src_files(self) -> list[PurePath]:
        file_tree = self._client.list(recursive=True, revision=self.config.revision)
        files = [PurePath(node.rel_path) for node in file_tree.nodes if node.kind == 'file']
        return files

    @raise_error
    def fetch_data(
            self,
            dst_dir: str | PurePath,
            *,
            rules: list | None = None,
            ) -> dict[Path, Path]:
        file_translation_map = self._create_file_translation_map(
                rules=rules,
                additional_markers={'source:desc': PurePath(self.config.url).name},
                )

        for src_file, dst_file in file_translation_map.items():
            dst_path = Path(dst_dir) / dst_file
            self._fetch_file(src_file, dst_path)

        return file_translation_map

    def _fetch_file(self, src_file: str | PurePath, dst_path: str | Path) -> None:
        dst_path = Path(dst_path)
        if dst_path.exists():
            raise FileHandlerError(f'Невозможно перезаписать файл {dst_path}')
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        self._client.export(
                src_file,
                dst_path,
                revision=self.config.revision,
                depth=Depth.EMPTY
                )


class SvnRecorder(BaseRecorder, BaseSvnHandler):
    _config_cls = SvnRecorderConfig

    def __init__(
            self,
            configs: dict,
            *,
            src_dir: str | Path,
            **__,
            ) -> None:
        BaseRecorder.__init__(self, configs, src_dir=src_dir, **__)
        self._client = SvnClient(self.config.url, check_exists=False)

    @raise_error
    def send_data(
            self,
            *,
            rules: list | None = None,
            ) -> dict[Path, Path]:
        file_translation_map = self._create_file_translation_map(rules)

        self._check_dst_dir()
        temp_dir = self._prepare_temp_dir(file_translation_map)
        self._client.import_(temp_dir.name, '')
        temp_dir.cleanup()

        return file_translation_map

    def _prepare_temp_dir(self, trans_map: dict[Path, Path]) -> tempfile.TemporaryDirectory:
        temp_dir = tempfile.TemporaryDirectory()
        dst_dir = Path(temp_dir.name).resolve()
        for src_file, dst_file in trans_map.items():
            src_path = self.src_dir / src_file
            dst_path = dst_dir / dst_file
            if dst_path.exists():
                raise FileHandlerError(f'Невозможно перезаписать файл {dst_file}')
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dst_path)
        return temp_dir

    def _check_dst_dir(self, dst_dir: str | None = None) -> None:
        self._client.mkdir(dst_dir, exist_ok=True)
        if self._client.list(dst_dir, recursive=True).nodes:
            raise FileHandlerError('Папка для выгрузки не пуста')
