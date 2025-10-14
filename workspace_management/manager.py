import hashlib
import json
import tempfile
import tomllib
from collections.abc import Callable
from copy import deepcopy
from dataclasses import asdict
from functools import wraps
from pathlib import Path, PurePath
from typing import Any, NewType

import tomlkit

from .file_handlers import find_loader, find_recorder
from .file_handlers.auth import AuthorizationError
from .info_data import Info, dataclass_from_dict
from .simple_config import config, ConfigInterface, ConfigUnion


@config
class DefaultRules:
    default_data_rules: str | None = None
    default_result_rules: str | None = None


@config
class RuleSet:
    rules: list
    ensure_all_files: bool = False
    description: str = ''


@config
class RulesConfig:
    rule_set: str = None


@config
class InitialConfig:
    exec: dict | ConfigInterface
    data: list[dict | ConfigInterface]


@config
class RecorderConfig:
    result: dict | ConfigInterface


class WorkspaceNotFoundError(OSError):
    def __init__(self, path: Path):
        super().__init__(f'Не найдена директория по пути "{path.resolve()}"')


class WrongWorkspaceError(Exception):
    def __init__(self, ws_content: list[str]):
        ws_content = '\n'.join(ws_content)
        super().__init__(
                'Директория должна содержать только файл config.toml\n'
                f'Сейчас она содержит:\n{ws_content}',
                )


class RuleSetNotFoundError(KeyError):
    def __init__(self, name: str):
        super().__init__(f'Не найден набор правил {name}')


class RecordingError(Exception):
    pass


class LoadingError(Exception):
    pass


SourceAddress = NewType('SourceAddress', str)
AuthParam = NewType('AuthParam', str)
type Credentials = dict[AuthParam, str]


class WorkspaceManager:
    __config_file = Path('config.toml')
    __config_lock_file = Path('config.lock.toml')
    __recorder_config_file = Path('commit_config.toml')
    __info_file = Path('info.json')
    __rules_file = Path('rules.json')

    def __init__(
            self,
            ws_path: str | Path,
            dry_run: bool = False,
            auth_callback: Callable[[SourceAddress, list[AuthParam]], Credentials] | None = None,
            try_save_credentials: bool = False,
            ):
        self._dry_run = dry_run
        self._auth_callback = auth_callback
        self._auth_cache = {}
        self.try_save_credentials = try_save_credentials
        self.work_path = Path(ws_path).resolve()
        self.info = Info()
        self.config = None
        self.default_rules = DefaultRules({})
        self.rule_sets = {}

    @staticmethod
    def authorize(func: Callable) -> Callable:
        @wraps(func)
        def callback_handler(self: Any, *_, **__) -> Any:  # noqa: ANN401
            try:
                return func(self, *_, **__)
            except AuthorizationError as err:
                if not self._auth_callback:
                    err.add_note('Передайте auth_callback, возвращающий соответствующие значения '
                                 'для указанного ресурса в WorkspaceManager!')
                    raise err
                auth_params = self._auth_callback(
                        err.source_address,
                        err.required_parameters,
                        )

                self.set_credentials({err.source_address: auth_params})
                return func(self, *_, **__)

        return callback_handler

    def set_credentials(self, credentials: dict[SourceAddress, dict[AuthParam, str]]) -> None:
        self._auth_cache.update(credentials)

    def get_credentials(self) -> dict[SourceAddress, dict[AuthParam, str]]:
        return self._auth_cache

    def initialize_ws(self, dry_run: bool = False) -> None:
        if self._dry_run or dry_run:
            return self._dry_load()

        self._check_ws_initial()
        self.config = self.read_toml_config(self.__config_file, InitialConfig)

        self.config.exec = self.load_exec()
        self.load_ws_rules()
        self.config.data = self.load_data()

        self.lock_config()
        self.hash_ws_files()
        self.save_ws_info()
        return None

    def _dry_load(self) -> None:
        self.config = self.read_toml_config(self.__config_file, InitialConfig)
        temp_dir = tempfile.TemporaryDirectory()
        temp_path = Path(temp_dir.name).resolve()
        self.work_path, old_work_path = temp_path, self.work_path
        self.config.exec = self.load_exec(dst_path=temp_path)
        self.load_ws_rules()
        self.config.data = self.load_data(dst_path=temp_path)
        self.work_path = old_work_path
        temp_dir.cleanup()

    def _check_ws_initial(self) -> None:
        if not self.work_path.is_dir():
            raise WorkspaceNotFoundError(self.work_path)
        ws_content = [path.name for path in self.work_path.iterdir()]
        if ws_content != [self.__config_file.name]:
            raise WrongWorkspaceError(ws_content)

    def read_toml_config(
            self,
            config_file: str | Path,
            config_cls: type[ConfigInterface] | None = None,
            ) -> dict | ConfigInterface:
        config_file = self.work_path / config_file
        with config_file.open('rb') as f:
            return config_cls(tomllib.load(f)) if config_cls else tomllib.load(f)

    @authorize
    def load_exec(
            self,
            dst_path: str | Path | None = None,
            config: dict | None = None,
            ) -> ConfigInterface:
        if not dst_path:
            dst_path = self.work_path
        elif not PurePath(dst_path).is_absolute():
            dst_path = self.work_path / dst_path
            dst_path.mkdir(parents=True, exist_ok=True)
        if not dst_path.is_relative_to(self.work_path) and not self._dry_run:
            raise LoadingError('Неверно указана директория для сохранения исполняемых файлов. '
                               'Укажите папку внутри рабочего пространства!')

        if not config:
            config = deepcopy(self.config.exec)

        loader_cls = find_loader(config)

        loader = loader_cls(
                configs=config,
                credentials=self._auth_cache,
                try_save_credentials=self.try_save_credentials,
                )
        loader.fetch_data(dst_path)

        config = loader.config
        self.info.sources.append(loader.info)
        return config

    @authorize
    def load_data(
            self,
            dst_path: str | Path | None = None,
            config: dict | None = None,
            ) -> list[ConfigInterface]:
        if not dst_path:
            dst_path = self.work_path
        elif not PurePath(dst_path).is_absolute():
            dst_path = self.work_path / dst_path
            dst_path.mkdir(parents=True, exist_ok=True)
        if not dst_path.is_relative_to(self.work_path) and not self._dry_run:
            raise LoadingError('Неверно указана директория для сохранения файлов данных. '
                               'Укажите папку внутри рабочего пространства!')

        if not config:
            config = deepcopy(self.config.data)

        data_configs = []
        for data_config_dict in config:
            loader_cls = find_loader(data_config_dict)

            data_config = ConfigUnion(
                    data_config_dict,
                    source=loader_cls.config_cls,  # noqa pycharm
                    rules=RulesConfig,
                    )
            loader = loader_cls(
                    configs=data_config.source,
                    credentials=self._auth_cache,
                    try_save_credentials=self.try_save_credentials,
                    )

            data_config.rule_set = data_config.rule_set or self.default_rules.default_data_rules
            rule_set = self.get_rule_set(data_config.rule_set)
            loader.fetch_data(
                    dst_path,
                    rules=rule_set.rules,
                    ensure_all_files=rule_set.ensure_all_files,
                    )

            data_config.source = loader.config
            data_configs.append(data_config)
            self.info.sources.append(loader.info)
        return data_configs

    def load_ws_rules(self) -> None:
        rules_path = self.work_path / self.__rules_file
        with rules_path.open('r', encoding='utf-8') as file:
            rules = json.load(file)
        rule_sets = rules.pop('rule_sets', {})
        self.default_rules = DefaultRules(rules)
        for name, rule_set in rule_sets.items():
            self.add_rule_set(name, rule_set)

    def add_rule_set(self, name: str, rule_set: dict) -> None:
        self.rule_sets[name] = RuleSet(rule_set)

    def get_rule_set(self, name: str) -> RuleSet:
        if rule_set := self.rule_sets.get(name):
            return rule_set
        else:
            raise RuleSetNotFoundError(name)

    def hash_dir(self, dir_path: str | Path) -> None:
        dir_path = self.work_path / dir_path
        for path, dirs, files in dir_path.walk():
            for file in files:
                file_path = path / file
                file_hash = self.hash_file(file_path)
                self.info.hash_sums[str(file_path.relative_to(self.work_path))] = file_hash

    def hash_file(self, file: str | Path) -> str:
        file = self.work_path / Path(file)
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

    def lock_config(self) -> None:
        config_lock = self.work_path / self.__config_lock_file
        with config_lock.open('w', encoding='utf-8') as f:
            tomlkit.dump(self.config.to_dict(), f)

    def save_ws_info(self) -> None:
        info_path = self.work_path / self.__info_file
        with info_path.open('w', encoding='utf-8') as file:
            json.dump(asdict(self.info), file, ensure_ascii=False, indent=4)

    def load_ws_info(self) -> Info:
        info_path = self.work_path / self.__info_file
        with info_path.open('r', encoding='utf-8') as file:
            self.info = dataclass_from_dict(json.load(file), Info)
        return self.info

    def check_hashes(
            self,
            hashes: dict[str, str],
            ignore: list[str] | None = None,
            ) -> list[Path]:
        if ignore is None:
            ignore = []
        changed_files = [
            Path(file)
            for file, file_hash in hashes.items()
            if self.hash_file(file) != file_hash
               and not any(Path(file).is_relative_to(Path(path)) for path in ignore)
            ]
        return changed_files

    def _check_non_versionable_sources(self, sources: list[dict]) -> list[dict]:
        return list(filter(lambda source: not source['versionable'], sources))

    def record_results(self, *, dry_run: bool = False) -> None:
        self.config = self.read_toml_config(self.__recorder_config_file, RecorderConfig)
        self.load_ws_rules()

        if self._dry_run or dry_run:
            self._dry_save()
            return

        self.config.record = self.save_results()

    def _dry_save(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        temp_path = Path(temp_dir.name).resolve()

        recorder_cls = find_recorder(self.config.result)
        if recorder_cls.is_versionable:
            self.check_results()

        config = {
            'type': 'local',
            'path': str(temp_path),
            'rule_set': self.config.result.get('rule_set')
                        or self.default_rules.default_result_rules,
            }
        self.save_results(config=config)

        temp_dir.cleanup()

    def check_results(self) -> None:
        self.load_ws_info()
        if self._check_non_versionable_sources(self.info.sources):
            raise RecordingError('Не все исходные данные версированы')
        if self.check_hashes(self.info.hash_sums):
            raise RecordingError('Файлы источников были изменены')

    @authorize
    def save_results(
            self,
            src_path: str | Path | None = None,
            config: dict | None = None,
            ) -> ConfigInterface:
        if not src_path:
            src_path = self.work_path
        elif not PurePath(src_path).is_absolute():
            src_path = self.work_path / src_path
            src_path.mkdir(parents=True, exist_ok=True)
        if not src_path.is_relative_to(self.work_path):
            raise RecordingError('Неверно указана директория с файлами результатов. '
                                 'Укажите папку внутри рабочего пространства!')

        if not config:
            config = deepcopy(self.config.result)

        recorder_cls = find_recorder(config)

        if recorder_cls.is_versionable:
            self.check_results()

        config = ConfigUnion(
                config,
                receiver=recorder_cls.config_cls,  # noqa pycharm
                rules=RulesConfig,
                )
        recorder = recorder_cls(
                src_dir=src_path,
                configs=config.receiver,
                credentials=self._auth_cache,
                try_save_credentials=self.try_save_credentials,
                )
        config.receiver = recorder.config
        config.rule_set = config.rule_set or self.default_rules.default_result_rules
        rule_set = self.get_rule_set(config.rule_set)
        recorder.send_data(
                rules=rule_set.rules,
                ensure_all_files=rule_set.ensure_all_files,
                )
        return config
