import os
import tomllib
from typing import Any

from .abstract import AbstractManager
from .svn_tool import SvnTool


class PathNotFoundError(OSError):
    pass


class IncorrectDirectoryError(Exception):
    pass


class ConfigNotFoundError(Exception):
    pass

class WorkspaceManager(AbstractManager):
    __config_name = 'config.toml'

    def __init__(self, path_to_workspace: str):
        super().__init__(path_to_workspace)
        self.__check_workspace_init()
        self.configs = self.read_toml()
        self.__exec_path = os.path.join(self.work_path, self.__exec_rel_path)
        self.svn_tool = SvnTool(self.work_path)

    def __check_workspace_init(self) -> None:
        if not os.path.exists(self.work_path):
            raise PathNotFoundError(f'Не найдена директория по пути {self.work_path}')
        workspace_content = os.listdir(self.work_path)
      # if not all([path.lower().endswith('.toml') for path in workspace_content]):
      #     raise IncorrectDirectoryError(f'Директория должна содержать только файлы формата TOML')
        if workspace_content != [self.__config_name]:
            sep = '\n'
            raise IncorrectDirectoryError(f'Директория должна содержать только файл config.toml\n'
                                          f'Сейчас она содержит:\n{sep.join(workspace_content)}')

    def read_toml(self) -> dict:
        with open(os.path.join(self.work_path, self.__config_name), 'rb') as file:
            return tomllib.load(file)

    def load_all_exec(self) -> None:
        for exec_name in self.configs['exec']:
            self.load_exec(exec_name)

    @staticmethod
    def try_get(dictionary: dict, key: str, *keys: str, error_message: str = '') -> Any: # noqa ANN401
        keys = (key, *keys)
        try:
            for key in keys:
                value = dictionary[key]
        except KeyError:
            raise ConfigNotFoundError(error_message)
        else:
            return value

    def load_exec(self, exec_name: str) -> None:
        if not os.path.exists(self.__exec_path) or not os.path.isdir(self.__exec_path):
            os.mkdir(self.__exec_path)
        exec_config = self.try_get(self.configs, 'exec', exec_name,
                                   f'Не найдена конфигурация для {exec_name}')
        svn_config = exec_config.get('svn')
        local_config = exec_config.get('local')
        if isinstance(svn_config, dict):
            return self.svn_tool.load_file_from_config(**svn_config, to_local_path=
                                                       os.path.join(self.__exec_path, exec_name))
        elif isinstance(local_config, dict):
            return self.load_exec_local(local_config)
        else:
            raise ConfigNotFoundError(f'Конфигурация для {exec_name} некорректна')


    def load_exec_local(self, local_config: dict) -> None:
        # TODO: Сделать, когда напишу тесты
        pass
