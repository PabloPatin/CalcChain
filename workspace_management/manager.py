import hashlib
import json
import tomllib
from dataclasses import asdict
from pathlib import Path

import toml

from .config_wrapper import config, ConfigInterface, ConfigUnion
from .loaders import handle_source
from .structure_info_data import Info
from .test_rules import RULES


@config
class RulesConfig:
    rule_set: str


@config
class Config:
    data_rules_path: str
    exec: dict | ConfigInterface | ConfigUnion
    data: list[dict | ConfigInterface | ConfigUnion]


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
    __data_dir = Path('data')

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
        exec_path = self.work_path / self.__exec_dir
        exec_path.mkdir(parents=True, exist_ok=True)

        loader_cls = handle_source(self.config.exec)
        self.config.exec = ConfigUnion(
                self.config.exec,
                rules=RulesConfig,
                source=loader_cls.config_cls,  # noqa pycharm
                )
        loader = loader_cls(self.config.exec.source)

        loader.fetch_data(exec_path, rules=RULES[self.config.exec.rule_set])
        self.info.sources.append(loader.info)

    def load_data(self) -> None:
        data_path = self.work_path / self.__data_dir
        data_path.mkdir(parents=True, exist_ok=True)
        tmp_config_data = []
        for data_config_dict in self.config.data:
            loader_cls = handle_source(data_config_dict)
            data_config = ConfigUnion(
                    data_config_dict,
                    rules=RulesConfig,
                    source=loader_cls.config_cls,  # noqa pycharm
                    )
            loader = loader_cls(data_config.source)
            loader.fetch_data(data_path, rules=RULES[data_config.rule_set])

            self.info.sources.append(loader.info)
            tmp_config_data.append(data_config)

        self.config.data = tmp_config_data

    def hash_dir(self, dir_path: str | Path) -> None:
        dir_path = self.work_path / dir_path
        for path, dirs, files in dir_path.walk():
            for file in files:
                file_path = path / file
                file_hash = self.hash_file(file_path)
                self.info.hash_sums[str(file_path.relative_to(self.work_path))] = file_hash

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

    def hash_ws_files(self) -> None:
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
