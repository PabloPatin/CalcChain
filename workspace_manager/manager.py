import os
import tomllib


class PathNotFoundError(OSError):
    pass


class IncorrectDirectoryError(Exception):
    pass


class WorkspaceManager:
    config_name = 'config.toml'

    def __init__(self, path_to_workspace: str):
        self.work_path = path_to_workspace
        self.__check_workspace_init()
        self.configs = None

    def __check_workspace_init(self):
        if not os.path.exists(self.work_path):
            raise PathNotFoundError(f'Не найдена директория по пути {self.work_path}')
        workspace_content = os.listdir(self.work_path)
        # if not all([path.lower().endswith('.toml') for path in workspace_content]):
        #     raise IncorrectDirectoryError(f'Директория должна содержать только файлы формата TOML')
        if workspace_content != [self.config_name]:
            sep = '\n'
            raise IncorrectDirectoryError(f'Директория должна содержать только файл config.toml\n'
                                          f'Сейчас она содержит:\n{sep.join(workspace_content)}')

    def read_toml(self):
        # with open(os.path.join(self.work_path, self.config_name)) as file:
        self.configs = tomllib.loads(os.path.join(self.work_path, self.config_name))
