import hashlib
import json
import tomllib
from dataclasses import asdict
from pathlib import Path

import toml

from .config_wrapper import config, ConfigInterface
from .loaders import handle_source
from .structure_info_data import Info

exec_rules = {
    'bin/libs/*.dat': '<parent>/tot/<name>',
    'bin/*': '<name>',
    '*.exe*': 'bin/<name>',
    '*': '<name>',
    }


@config
class Config:
    exec: dict | ConfigInterface
    data: list[dict | ConfigInterface]


class WorkspaceNotFoundError(OSError):
    def __init__(self, path: Path):
        super().__init__(f'Не найдена директория по пути {path.resolve()}')


class WrongWorkspaceError(Exception):
    def __init__(self, ws_content: list[str]):
        ws_content = '\n'.join(ws_content)
        super().__init__(
                'Директория должна содержать только файл config.toml\n'
                f'Сейчас она содержит:\n{ws_content}',
                )


class WorkspaceManager:
    __config_file = Path('config.toml')
    __exec_dir = Path('exec')

    def __init__(self, ws_path: str | Path):
        self.work_path = Path(ws_path).resolve()
        self.__check_ws_initial()
        self.config = self.read_config()
        self.info = Info()

    def __check_ws_initial(self) -> None:
        if not self.work_path.is_dir():
            raise WorkspaceNotFoundError(self.work_path)
        ws_content = [path.name for path in self.work_path.iterdir()]
        if ws_content != [self.__config_file.name]:
            raise WrongWorkspaceError(ws_content)

    def read_config(self) -> Config | ConfigInterface:
        config_file = self.work_path / self.__config_file
        with config_file.open('rb') as f:
            return Config(tomllib.load(f))

    def load_exec(self) -> None:
        """
        Загружает в рабочее пространство исполняемый файл, указанный в конфигурации
        """
        exec = self.work_path / self.__exec_dir
        exec.mkdir(parents=True, exist_ok=True)

        loader = handle_source(self.config.exec)
        loader.fetch_data(exec, rules=exec_rules)
        self.info.sources.append(loader.info)
        self.hash_all()

    # def load_exec_from_svn(self, svn_config: SvnExportConfig, to_local_dir: str) -> None:
    #     file_info = self.svn_tool.load_directory_from_config(url=svn_config.url,
    #                                                          revision=svn_config.revision,
    #                                                          local_path=to_local_dir)
    #     svn_config.revision = file_info.commit_revision
    #     svn_data = SvnSource(
    #             url=file_info.url,
    #             rev=file_info.commit_revision,
    #             repo_uuid=file_info.repository_uuid,
    #             type='exec',
    #             )
    #     self.info.sources.append(svn_data)
    #
    # def load_exec_from_local(self, local_config: LocalExportConfig, to_local_dir: str) -> None:
    #     self.local_source_tool.load_directory_from_config(path=local_config.path,
    #                                                       local_path=to_local_dir)
    #     self.info.sources.append(LocalSource(type='exec'))

    def hash_dir(self, dir_path: str | Path) -> None:
        """
        Хэширует все файлы в указанном каталоге рекурсивно и записывает их в info
        """
        dir_path = Path(dir_path)
        for path, dirs, files in dir_path.walk():
            for file in files:
                file_path = path / file
                file_hash = self.hash_file(file_path)
                self.info.hash_sums[str(file_path)] = file_hash

    def hash_file(self, file: str | Path) -> str:
        file = Path(file)
        with file.open('rb') as f:
            hasher = hashlib.new('sha256')
            while True:
                chunk = f.read(4096)
                if not chunk:
                    break
                hasher.update(chunk)
        return hasher.hexdigest()

    def hash_all(self) -> None:
        """Хэширует все файлы в рабочей области"""
        self.hash_dir('.')

    def dump_config(self) -> None:
        config_lock = self.work_path / 'config.lock.toml'
        with config_lock.open('w', encoding='utf-8') as f:
            toml.dump(self.config.to_dict(), f)

    def dump_info(self) -> None:
        info_path = self.work_path / 'info.json'
        with info_path.open('w', encoding='utf-8') as file:
            # toml.dump(info, file)
            json.dump(asdict(self.info), file, ensure_ascii=False, indent=4)
