import shutil
import tempfile
from abc import ABCMeta
from collections.abc import Callable
from functools import wraps
from pathlib import Path, PurePath

from svn import SvnClient, SvnError
from workspace_management.simple_config import config
from .auth import AuthorizationError
from .base import BaseLoader, FileHandlerError, BaseFileHandler, BaseRecorder


def raise_error(method: Callable) -> Callable:
    wrong_repo_err_codes = ('E180001', 'E155007', 'E731001', 'E730061')
    wrong_node_err_codes = ('E200009',)
    wrong_revision_err_codes = ('E160006',)
    cannot_rewrite_file_err_codes = ('E160020',)
    cannot_get_credentials_err_codes = ('E170001',)
    destination_directory_exists = ('E155000',)

    def match_error_codes(
            error_codes: tuple[str, ...],
            match_codes: tuple[str, ...],
            ) -> bool:
        return any(code in match_codes for code in error_codes)

    @wraps(method)
    def wrapper(*_, **__) -> ...:
        try:
            return method(*_, **__)
        except OSError as err:
            raise FileHandlerError(err.__repr__())
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
            elif match_error_codes(err.error_codes, destination_directory_exists):
                raise FileHandlerError(
                        f'\nПапка назначения уже существует\n{err.stderr}',
                        )
            elif match_error_codes(err.error_codes, cannot_get_credentials_err_codes):
                raise AuthorizationError(
                        source_address=err.url,
                        auth_parameters=['username', 'password']
                        )
            return None

    return wrapper


@config
class SvnLoaderConfig:
    type: str
    repo_url: str
    path: str | PurePath = ''
    revision: str | int = 'HEAD'


@config
class SvnRecorderConfig:
    type: str
    repo_url: str
    path: str | PurePath = ''


class BaseSvnHandler(BaseFileHandler, metaclass=ABCMeta):
    _type = 'svn'
    _repo_info_cache = {}

    @raise_error
    def __init__(self, configs: dict, check_exists: bool = False, **__) -> None:
        BaseFileHandler.__init__(self, configs, **__)

        self._auth_data = self._find_credentials()
        self._client = SvnClient(
                self.config.repo_url,
                username=self._auth_data.get('username'),
                password=self._auth_data.get('password'),
                check_exists=check_exists,
                cache_auth=self.try_save_credentials,
                )

        if not self.config.repo_url in self._repo_info_cache:
            self._repo_info_cache[self.config.repo_url] = self._client.info()

    @property
    def is_versionable(self) -> bool:
        return True

    @property
    def info(self) -> dict:
        return ({'repo_uuid': self._repo_info_cache[self.config.repo_url].repository_uuid}
                | super().info)

    def _find_credentials(self) -> dict:
        for url in sorted(self._credentials.keys(), key=lambda _: len(_)):
            if self.config.repo_url.startswith(url):
                return self._credentials[url]
        return {}


class SvnLoader(BaseSvnHandler, BaseLoader):
    _config_cls = SvnLoaderConfig

    def __init__(self, configs: dict, **__) -> None:
        BaseSvnHandler.__init__(self, configs, **__)
        self.config.revision = self.config.revision \
            if self.config.revision != 'HEAD' \
            else self._repo_info_cache[self.config.repo_url].entry_revision

    @property
    @raise_error
    def src_files(self) -> list[PurePath]:
        file_tree = self._client.list(
                path=self.config.path,
                recursive=True,
                revision=self.config.revision
                )
        files = [PurePath(node.rel_path) for node in file_tree.nodes if node.kind == 'file']
        return files

    @raise_error
    def fetch_data(
            self,
            dst_dir: str | PurePath,
            *,
            rules: list | None = None,
            ensure_all_files: bool = False,
            ) -> dict[Path, Path]:

        temp_dir = tempfile.TemporaryDirectory()
        src_dir = Path(temp_dir.name).resolve()

        self._client.export(self.config.path, src_dir, force=True)

        file_translation_map = self._create_file_translation_map(
                rules=rules,
                additional_markers={
                    'source:desc': PurePath(self.config.path or self.config.repo_url).name
                    },
                check_skipped=ensure_all_files,
                )

        for src_file, dst_file in file_translation_map.items():
            src_path = src_dir / src_file
            dst_path = Path(dst_dir) / dst_file
            self._fetch_file(src_path, dst_path)

        temp_dir.cleanup()
        return file_translation_map

    def _fetch_file(self, src_path: str | PurePath, dst_path: str | Path) -> None:
        dst_path = Path(dst_path)
        if dst_path.exists():
            raise FileHandlerError(f'Невозможно перезаписать файл {dst_path}')
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dst_path)


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
        BaseSvnHandler.__init__(self, configs, check_exists=False, **__)

    @raise_error
    def send_data(
            self,
            *,
            rules: list | None = None,
            ensure_all_files: bool = False,
            ) -> dict[Path, Path]:
        file_translation_map = self._create_file_translation_map(
                rules,
                check_skipped=ensure_all_files,
                )

        self._check_dst_dir(self.config.path)

        temp_dir = tempfile.TemporaryDirectory()
        dst_dir = Path(temp_dir.name).resolve()

        for src_file, dst_file in file_translation_map.items():
            src_path = self.src_dir / src_file
            dst_path = dst_dir / dst_file
            if dst_path.exists():
                raise FileHandlerError(f'Невозможно перезаписать файл {dst_file}')
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dst_path)
        self._client.import_(temp_dir.name, self.config.path)

        temp_dir.cleanup()
        return file_translation_map

    def _check_dst_dir(self, dst_dir: str | None = None) -> None:
        self._client.mkdir(dst_dir, exist_ok=True)
        if self._client.list(dst_dir, recursive=True).nodes:
            raise FileHandlerError('Папка для выгрузки не пуста')
