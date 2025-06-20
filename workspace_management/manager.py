import hashlib
import json
import os
import tomllib
from dataclasses import asdict
from typing import Any

import toml

from .abstract import AbstractManager
from .local_source_tool import LocalSourceTool
from .structure_info_data import InfoRoot, SvnSource, LocalSource
from .svn_tool import SvnTool


class PathNotFoundError(OSError):
    pass


class IncorrectDirectoryError(Exception):
    pass


class ConfigNotFoundError(Exception):
    pass


class WorkspaceManager(AbstractManager):
    __config_name = 'config.toml'
    __exec_rel_path = 'exec'

    def __init__(self, path_to_workspace: str):
        self.exec_config = None
        self.work_path = path_to_workspace
        self.__check_workspace_init()
        os.chdir(self.work_path)
        self.configs = self.read_toml()
        self.info = InfoRoot()
        self.svn_tool = SvnTool()
        self.local_source_tool = LocalSourceTool()

    def __check_workspace_init(self) -> None:
        if not os.path.exists(self.work_path):
            raise PathNotFoundError(f'Не найдена директория по пути {self.work_path}')
        workspace_content = os.listdir(self.work_path)
        # if not all([path.lower().endswith('.toml') for path in workspace_content]):
        #     raise IncorrectDirectoryError(
        #             f'Директория должна содержать только файлы формата TOML')
        if workspace_content != [self.__config_name]:
            sep = '\n'
            raise IncorrectDirectoryError(f'Директория должна содержать только файл config.toml\n'
                                          f'Сейчас она содержит:\n{sep.join(workspace_content)}')

    def read_toml(self) -> dict:
        with open(self.__config_name, 'rb') as file:
            return tomllib.load(file)

    def validate_config(self) -> None:
        match self.configs:
            case {
                "data": _,
                "res_data": _,
                "exec": dict(exec_config)
                }:
                self.exec_config = exec_config
            case _:
                raise ConfigNotFoundError('Конфигурационный файл составлен некорректно')

    @staticmethod
    def try_get_config(dictionary: dict, *keys: str,
                       error_message: str = '') -> Any:  # noqa ANN401
        try:
            for key in keys:
                dictionary = dictionary[key]
        except KeyError:
            print(dictionary)
            raise ConfigNotFoundError(error_message)
        else:
            return dictionary

    def load_all_exec(self) -> None:
        """
        Загружает все исполняемые файлы описанные в конфигурации
        """
        for exec_name in self.try_get_config(self.configs, 'exec'):
            self.load_exec(exec_name)
        self.hash_all()

    def load_exec(self, exec_name: str) -> None:
        """
        Загружает в рабочее пространство исполняемый файл, указанный в конфигурации
        :param exec_name: Имя программы, указанное в конфигурационном файле
        """
        os.makedirs(self.__exec_rel_path, exist_ok=True)
        exec_config = self.try_get_config(self.configs, 'exec', exec_name,
                                          error_message=f'Не найдена конфигурация для {exec_name}')
        svn_config = exec_config.get('svn')
        local_config = exec_config.get('local')
        if isinstance(svn_config, dict):
            self.load_exec_from_svn(svn_config, self.__exec_rel_path)
        elif isinstance(local_config, dict):
            self.load_exec_from_local(local_config, self.__exec_rel_path)
        else:
            raise ConfigNotFoundError(f'Конфигурация для {exec_name} некорректна')

    def load_exec_from_svn(self, svn_config: dict, to_local_dir: str) -> None:
        file_info = self.svn_tool.load_file_from_config(**svn_config, to_local_dir=to_local_dir)
        svn_config['revision'] = file_info.commit_revision
        svn_data = SvnSource(
                url=file_info.url,
                rev=file_info.commit_revision,
                repo_uuid=file_info.repository_uuid,
                type='exec',
                )
        self.info.sources.append(svn_data)

    def load_exec_from_local(self, local_config: dict, to_local_dir: str) -> None:
        self.local_source_tool.load_file_from_config(**local_config,
                                                     to_local_dir=to_local_dir)
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
        # TODO: подумать о том, TOML или YAML использовать для конфигурации?
        with open('config.lock.toml', 'w', encoding='utf-8') as file:
            toml.dump(self.configs, file)

    def dump_info(self) -> None:
        info_path = 'info.json'
        info = asdict(self.info)
        with open(info_path, 'w', encoding='utf-8') as file:
            # toml.dump(info, file)
            json.dump(info, file, ensure_ascii=False, indent=4)
