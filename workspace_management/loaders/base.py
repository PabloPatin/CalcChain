from abc import ABCMeta, abstractmethod
from pathlib import Path

from workspace_management.simple_config import ConfigInterface


class LoaderError(Exception):
    pass


class LoaderNotFoundError(LoaderError):
    pass


class BaseLoader[T](metaclass=ABCMeta):
    _type: str = None
    _config_cls: type[T] = None

    def __init__(self, configs: dict | T):
        if isinstance(configs, self._config_cls):
            self.config: T | ConfigInterface = configs
        else:
            self.config: T | ConfigInterface = self._config_cls(configs)

    @classmethod
    def can_handle_source(cls, configs: dict) -> bool:
        return configs.get('type') == cls._type

    @property
    @abstractmethod
    def info(self) -> dict:
        pass

    @abstractmethod
    def fetch_data(self, dst_dir: str | Path, *, rules: dict[str, str]) -> None:
        pass

    @property
    @abstractmethod
    def src_files(self) -> list[Path]:
        pass

    @classmethod
    @property
    def config_cls(cls) -> type[ConfigInterface]:
        return cls._config_cls
