from pathlib import Path, PurePath

from svn import SvnClient, SvnError
from svn.data_structures import Depth
from workspace_management.config_wrapper import config
from workspace_management.loaders.base import BaseLoader
from workspace_management.mapping import create_file_translation_map


class ValidationError(Exception):
    pass


@config
class SvnLoaderConfig:
    type: str
    url: str
    revision: str | int = 'HEAD'


class SvnLoader(BaseLoader[SvnLoaderConfig]):
    _type = 'svn'
    _config_cls = SvnLoaderConfig

    no_repo_err_codes = ('E170013', 'E180001', 'E155007')
    no_node_err_code = ('E200009',)

    def _match_svn_errors(self,
                          error_codes: tuple[str, ...],
                          match_codes: tuple[str, ...],
                          ) -> bool:
        return any(code in match_codes for code in error_codes)

    def __init__(self, configs: dict) -> None:
        super().__init__(configs)
        try:
            self._connector = SvnClient(self.config.url)
            self.config.revision = self._connector.info(
                    revision=self.config.revision,
                    ).entry_revision

        except SvnError as err:
            if self._match_svn_errors(err.error_codes, self.no_repo_err_codes):
                raise ValidationError(
                        '\nurl задан некорректно в файле конфигурации\n'
                        f'Не обнаружено репозитория по ссылке {self.config.url}',
                        )
            elif self._match_svn_errors(err.error_codes, self.no_node_err_code):
                raise ValidationError(
                        '\nurl задан некорректно в файле конфигурации\n'
                        f'Объект по ссылке {self.config.url} не найден в репозитории',
                        )

    @property
    def info(self) -> dict:
        return self.config.to_dict() | {'repo_uuid': self._connector.info().repository_uuid}

    @property
    def src_files(self) -> list[PurePath]:
        file_tree = self._connector.list(recursive=True, revision=self.config.revision)
        files = [PurePath(node.rel_path) for node in file_tree.nodes if node.kind == 'file']
        return files

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
            if not Path(dst_path).exists():
                location = Path(dst_path).parent
                location.mkdir(parents=True, exist_ok=True)
                self._connector.export(
                        src_file.as_posix(),
                        str(dst_path),
                        revision=self.config.revision,
                        depth=Depth.EMPTY)


if __name__ == '__main__':
    print(SvnLoader.can_handle_source({'source_type': 'svn'}))
    print(SvnLoaderConfig({'source_type': 'svn', 'url': 'skdjasd'}))
    print(SvnLoader({'source_type': 'svn', 'url': 'skdjasd'}))
    print(loader := SvnLoader(configs={'source_type': 'svn', 'url': 'skdjasd'}))
    print(loader.config)
