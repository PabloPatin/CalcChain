from abc import ABCMeta, abstractmethod
from pathlib import Path

from workspace_management.simple_config import ConfigInterface


class LoaderError(Exception):
    pass


class LoaderNotFoundError(LoaderError):
    pass


class RecorderError(Exception):
    pass


class RecorderNotFoundError(RecorderError):
    pass


class BaseHandler(metaclass=ABCMeta):
    _type: str = None
    _config_cls: type[ConfigInterface] = None

    def __init__(self, configs: dict | ConfigInterface):
        self.config = configs \
            if isinstance(configs, self._config_cls) \
            else self._config_cls(configs)

    @classmethod
    def can_handle_source(cls, configs: dict) -> bool:
        return configs.get('type') == cls._type

    @classmethod
    @property
    @abstractmethod
    def is_versionable(cls) -> bool:
        pass

    @property
    def info(self) -> dict:
        return self.config.to_dict() | {'versionable': self.is_versionable}

    @classmethod
    @property
    def config_cls(cls) -> type[ConfigInterface]:
        return cls._config_cls


class BaseLoader(BaseHandler, metaclass=ABCMeta):
    @property
    @abstractmethod
    def src_files(self) -> list[Path]:
        pass

    @abstractmethod
    def fetch_data(self, dst_dir: str | Path, *, rules: list | None = None) -> None:
        pass


class BaseRecorder(BaseHandler, metaclass=ABCMeta):
    def __init__(self, configs: dict | ConfigInterface, ):
        super().__init__(configs)
        self._res_files = None

    def _find_res_files(self) -> list[Path]:
        self.res_files = ...
        return self.res_files

    @property
    def res_files(self) -> list[Path]:
        return self._res_files or self._find_res_files()

    @abstractmethod
    def send_data(self, dst_dir: str | Path, *, rules: list | None = None) -> None:
        pass
