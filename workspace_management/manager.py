import os
import tomllib
from typing import Any

from .abstract import AbstractManager
from .local_source_tool import LocalSourceTool
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
        self.info = {}
        self.svn_tool = SvnTool(self.work_path)
        self.local_source_tool = LocalSourceTool(self.work_path)

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
        with open(os.path.join(self.work_path, self.__config_name), 'rb') as file:
            return tomllib.load(file)

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
        for exec_name in self.try_get_config(self.configs, 'exec'):
            self.load_exec(exec_name)

    def load_exec(self, exec_name: str) -> None:
        """
        Загружает в рабочее пространство исполняемый файл, указанный в конфигурации
        :param exec_name: Имя программы, указанное в конфигурационном файле
        """
        exec_path = os.path.join(self.work_path, self._exec_rel_path)
        os.makedirs(exec_path, exist_ok=True)
        exec_config = self.try_get_config(self.configs, 'exec', exec_name,
                                   error_message=f'Не найдена конфигурация для {exec_name}')
        svn_config = exec_config.get('svn')
        local_config = exec_config.get('local')
        if isinstance(svn_config, dict):
            self.load_exec_from_svn(svn_config, self._exec_rel_path)
        elif isinstance(local_config, dict):
            self.local_source_tool.load_file_from_config(**local_config,
                                                         to_local_dir=self._exec_rel_path)
        else:
            raise ConfigNotFoundError(f'Конфигурация для {exec_name} некорректна')

    def load_exec_from_svn(self, svn_config: dict, to_local_dir: str) -> None:
        file_info = self.svn_tool.load_file_from_config(**svn_config, to_local_dir=to_local_dir)
        svn_config['revision'] = file_info.commit_revision
