import abc
import os
from dataclasses import dataclass, asdict
from typing import Literal, ClassVar

from svn import SvnClient, SvnError


class ValidationError(Exception):
    pass


@dataclass
class ExportConfig(metaclass=abc.ABCMeta):
    source_type: Literal['local', 'svn']


@dataclass
class SvnExportConfig(ExportConfig):
    url: str
    revision: Literal['HEAD'] | int = 'HEAD'

    no_repo_err_codes = ('E170013', 'E180001', 'E155007')
    no_node_err_code = ('E200009',)

    def __init__(self, url: str, revision: str | int = 'HEAD', **__):
        super().__init__(source_type='svn')
        self.url = url
        self.revision = revision
        self.__post_init__()

    def __post_init__(self) -> None:
        try:
            client = SvnClient(self.url)
            client.info()
            self.url = client.url
        except SvnError as err:
            if self.__match_svn_errors(err.error_codes, self.no_repo_err_codes):
                raise ValidationError('\nurl задан некорректно в файле конфигурации\n'
                                      f'Не обнаружено репозитория по ссылке {self.url}')
            elif self.__match_svn_errors(err.error_codes, self.no_node_err_code):
                raise ValidationError('\nurl задан некорректно в файле конфигурации\n'
                                      f'Объект по ссылке {self.url} не найден в репозитории')

    def __match_svn_errors(self,
                           error_codes: tuple[str, ...],
                           match_codes: tuple[str, ...],
                           ) -> bool:
        return any(code in match_codes for code in error_codes)


@dataclass
class LocalExportConfig(ExportConfig):
    path: str

    def __init__(self, path: str, **__):
        super().__init__(source_type='local')
        self.path = path

    def __post_init__(self) -> None:
        if not os.path.exists(self.path) and os.path.isdir(self.path):
            raise ValidationError('path задан некорректно в файле конфигурации\n'
                                  f'Не обнаружена директория по пути {self.path}')


@dataclass
class DataConfig:
    # TODO
    pass


@dataclass()
class Config:
    __export_configs: ClassVar = {
        'local': LocalExportConfig,
        'svn': SvnExportConfig,
        }

    def __init__(self, data: dict, exec: dict, title: str = ''):
        self.data = self.__form_data(data)
        self.exec = self.__form_exec(exec)
        self.title = title

    data: DataConfig
    exec: ExportConfig

    @staticmethod
    def __form_data(data: dict) -> DataConfig:
        return DataConfig()

    @classmethod
    def __form_exec(cls, exec: dict) -> ExportConfig:
        match exec:
            case {'source_type': source_type}:
                tool = cls.__select_export_config(source_type)
                return tool(**exec)
            case _:
                raise ValidationError('\nНе указан source_type конфигурационном файле')

    @classmethod
    def __select_export_config(cls, source_type: str) -> type[ExportConfig]:
        config_type = cls.__export_configs.get(source_type)
        if config_type:
            return config_type
        else:
            raise ValidationError('\nsource_type указан некорректно в конфигурационном файле\n'
                                  'укажите одно из корректных значений: '
                                  f'{", ".join(cls.__export_configs.keys())}')

    def dict(self) -> dict:
        return asdict(self)
