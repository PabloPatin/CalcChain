from collections.abc import Callable
from functools import wraps
from pathlib import Path, PurePath

from svn import SvnClient, SvnError
from svn.data_structures import Depth
from workspace_management.loaders.base import BaseLoader, LoaderError
from workspace_management.mapping import create_file_translation_map
from workspace_management.simple_config import config


def raise_error(method: Callable) -> Callable:
    no_repo_err_codes = ('E170013', 'E180001', 'E155007')
    no_node_err_code = ('E200009',)

    def match_svn_errors(
            error_codes: tuple[str, ...],
            match_codes: tuple[str, ...],
            ) -> bool:
        return any(code in match_codes for code in error_codes)

    @wraps(method)
    def wrapper(*_, **__) -> ...:
        try:
            return method(*_, **__)
        except SvnError as err:
            if match_svn_errors(err.error_codes, no_repo_err_codes):
                raise LoaderError(
                        f'\nРепозиторий не найден\n{err.stderr}',
                        )
            elif match_svn_errors(err.error_codes, no_node_err_code):
                raise LoaderError(
                        f'\nФайл в репозитории не найден\n{err.stderr}',
                        )
            return None

    return wrapper


@config
class SvnLoaderConfig:
    type: str
    url: str
    revision: str | int = 'HEAD'


class SvnLoader(BaseLoader[SvnLoaderConfig]):
    _type = 'svn'
    _config_cls = SvnLoaderConfig

    @raise_error
    def __init__(self, configs: dict) -> None:
        super().__init__(configs)
        self._client = SvnClient(self.config.url)
        self.config.revision = self._client.info(
                revision=self.config.revision,
                ).entry_revision

    @property
    def info(self) -> dict:
        return self.config.to_dict() | {'repo_uuid': self._client.info().repository_uuid}

    @property
    @raise_error
    def src_files(self) -> list[PurePath]:
        file_tree = self._client.list(recursive=True, revision=self.config.revision)
        files = [PurePath(node.rel_path) for node in file_tree.nodes if node.kind == 'file']
        return files

    @raise_error
    def fetch_data(self, dst_dir: str | Path, *, rules: list[str, str]) -> None:
        files = self.src_files
        file_translation_map = create_file_translation_map(
                files=files,
                rules=rules,
                additional_markers={'source:desc': PurePath(self.config.url).name},
                check_skipped_files=True,
                )

        for src_file, dst_file in file_translation_map.items():
            dst_path = Path(dst_dir) / dst_file
            self._fetch_file(src_file, dst_path)

    def _fetch_file(self, src_file: str | PurePath, dst_path: str | Path) -> None:
        dst_path = Path(dst_path)
        if dst_path.exists():
            raise LoaderError(f'Невозможно перезаписать файл {dst_path}')
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        self._client.export(
                PurePath(src_file).as_posix(),
                str(dst_path),
                revision=self.config.revision,
                depth=Depth.EMPTY)
