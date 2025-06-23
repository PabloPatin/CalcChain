import hashlib
import json
import os
import tomllib
from dataclasses import asdict

import toml

from workspace_management.connectors.local_source_tool import LocalSourceTool
from workspace_management.connectors.svn_tool import SvnTool
from workspace_management.validation.data_structures import SvnExportConfig, \
    LocalExportConfig
from .structure_info_data import InfoRoot, SvnSource, LocalSource
from .validation.data_structures import Config


class PathNotFoundError(OSError):
    pass


class IncorrectDirectoryError(Exception):
    pass


class ConfigNotFoundError(Exception):
    pass


class WorkspaceManager:
    __config_name = 'config.toml'
    __exec_rel_path = 'exec'

    def __init__(self, path_to_workspace: str):
        self.exec_config = None
        self.work_path = path_to_workspace
        self.__check_workspace_init()
        os.chdir(self.work_path)
        self.config = self.read_toml_config()
        self.info = InfoRoot()
        self.svn_tool = SvnTool()
        self.local_source_tool = LocalSourceTool()

    def __check_workspace_init(self) -> None:
        if not os.path.exists(self.work_path):
            raise PathNotFoundError(f'Не найдена директория по пути {self.work_path}')
        workspace_content = os.listdir(self.work_path)
        if workspace_content != [self.__config_name]:
            sep = '\n'
            raise IncorrectDirectoryError(f'Директория должна содержать только файл config.toml\n'
                                          f'Сейчас она содержит:\n{sep.join(workspace_content)}')

    def read_toml_config(self) -> Config:
        with open(self.__config_name, 'rb') as file:
            return Config(**tomllib.load(file))

    # def validate_config(self) -> None:
    #     match self.configs:    # noqa pycharm
    #         case {
    #             'data': _,
    #             'res_data': _,
    #             'exec': dict(exec_config),
    #             }:
    #             self.exec_config = exec_config
    #         case _:
    #             raise ConfigNotFoundError('Конфигурационный файл составлен некорректно')

    # @staticmethod
    # def try_get_config(dictionary: dict, *keys: str,
    #                    error_message: str = '') -> Any:  # noqa ANN401
    #     try:
    #         for key in keys:
    #             dictionary = dictionary[key]
    #     except KeyError:
    #         print(dictionary)
    #         raise ConfigNotFoundError(error_message)
    #     else:
    #         return dictionary

    def load_exec(self) -> None:
        """
        Загружает в рабочее пространство исполняемый файл, указанный в конфигурации
        :param exec_name: Имя программы, указанное в конфигурационном файле
        """
        os.makedirs(self.__exec_rel_path, exist_ok=True)
        exec_config = self.config.exec
        if isinstance(exec_config, SvnExportConfig):
            self.load_exec_from_svn(exec_config, to_local_dir=self.__exec_rel_path)
        elif isinstance(exec_config, LocalExportConfig):
            self.load_exec_from_local(exec_config, to_local_dir=self.__exec_rel_path)
        else:
            raise ConfigNotFoundError('Конфигурация для exec некорректна')
        self.hash_all()

    def load_exec_from_svn(self, svn_config: SvnExportConfig, to_local_dir: str) -> None:
        file_info = self.svn_tool.load_directory_from_config(url=svn_config.url,
                                                             revision=svn_config.revision,
                                                             local_path=to_local_dir)
        svn_config.revision = file_info.commit_revision
        svn_data = SvnSource(
                url=file_info.url,
                rev=file_info.commit_revision,
                repo_uuid=file_info.repository_uuid,
                type='exec',
                )
        self.info.sources.append(svn_data)

    def load_exec_from_local(self, local_config: LocalExportConfig, to_local_dir: str) -> None:
        self.local_source_tool.load_directory_from_config(path=local_config.path,
                                                          local_path=to_local_dir)
        self.info.sources.append(LocalSource(type='exec'))

    def hash_dir(self, dir_path: str) -> None:
        """
        Хэширует все файлы в указанном каталоге рекурсивно и записывает их в info
        :param dir_path: Относительный путь к каталогу для хэширования
        """
        for dir_rel_path, sub_dirs, files in os.walk(dir_path):
            for filename in files:
                file_path = os.path.join(dir_rel_path, filename)
                file_hash = self.hash_file(file_path)
                self.info.hash_sums[file_path] = file_hash

    def hash_file(self, file_path: str) -> str:
        """
        :param file_path: Относительный путь к файлу для хэширования
        :return: Возвращает хэш файла
        """
        with open(file_path, 'rb') as file:
            hasher = hashlib.new('sha256')
            while True:
                chunk = file.read(4096)
                if not chunk:
                    break
                hasher.update(chunk)
        return hasher.hexdigest()

    def hash_all(self) -> None:
        """Хэширует все файлы в рабочей области"""
        self.hash_dir('.')

    def dump_config(self) -> None:
        with open('config.lock.toml', 'w', encoding='utf-8') as file:
            toml.dump(self.config.dict(), file)

    def dump_info(self) -> None:
        info_path = 'info.json'
        info = asdict(self.info)
        with open(info_path, 'w', encoding='utf-8') as file:
            # toml.dump(info, file)
            json.dump(info, file, ensure_ascii=False, indent=4)
