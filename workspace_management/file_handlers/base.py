from abc import ABCMeta, abstractmethod
from pathlib import Path
from collections.abc import Iterable

from workspace_management.mapping import get_files_in_dir, create_file_translation_map
from workspace_management.simple_config import ConfigInterface


class FileHandlerError(Exception):
    pass


class FileHandlerNotFoundError(FileHandlerError):
    pass


class LoaderNotFoundError(FileHandlerNotFoundError):
    pass


class RecorderNotFoundError(FileHandlerNotFoundError):
    pass


class AuthorizationError(FileHandlerError):
    def __init__(self, _type: str, *, auth_parameters: Iterable[str], source_address: str):
        super().__init__(f'Ошибка авторизации для ресурса {source_address}. '
                         f'Не указаны параметры {auth_parameters}.')
        self._type = _type
        self._auth_parameters = auth_parameters
        self._source_address = source_address

    @property
    def type(self) -> str:
        return self._type

    @property
    def source_address(self) -> str:
        return self._source_address

    @property
    def required_parameters(self) -> Iterable[str]:
        return self._auth_parameters


class BaseFileHandler(metaclass=ABCMeta):
    _type: str = None
    _config_cls: type[ConfigInterface] = None

    def __init__(self, configs: dict | ConfigInterface, *, credentials: dict | None = None):
        self._credentials = credentials or {}
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


class BaseLoader(BaseFileHandler, metaclass=ABCMeta):
    @property
    @abstractmethod
    def src_files(self) -> list[Path]:
        pass

    def _create_file_translation_map(
            self,
            rules: list | None = None,
            *,
            additional_markers: dict[str, str] | None = None,
            check_skipped: bool = True,
            ) -> dict[Path, Path]:
        rules = rules or [['.*', '<>']]
        additional_markers = additional_markers or {}

        return create_file_translation_map(
                files=self.src_files,
                rules=rules,
                additional_markers=additional_markers,
                check_skipped_files=check_skipped,
                )

    @abstractmethod
    def fetch_data(
            self,
            dst_dir: str | Path,
            *,
            rules: list | None = None,
            ) -> None:
        pass


class BaseRecorder(BaseFileHandler, metaclass=ABCMeta):
    def __init__(
            self,
            configs: dict | ConfigInterface,
            *,
            src_dir: str | Path,
            credentials: dict | None = None,
            ):
        BaseFileHandler.__init__(self, configs, credentials=credentials)
        self.src_dir = Path(src_dir).resolve()

    @property
    def local_files(self) -> list[Path]:
        return get_files_in_dir(self.src_dir, base_dir=self.src_dir)

    def _create_file_translation_map(
            self,
            rules: list,
            *,
            additional_markers: dict[str, str] | None = None,
            ) -> dict[Path, Path]:
        additional_markers = additional_markers or {}

        return create_file_translation_map(
                files=self.local_files,
                rules=rules,
                additional_markers=additional_markers,
                check_skipped_files=False,
                )

    @abstractmethod
    def send_data(self, *, rules: list | None = None) -> dict[Path, Path]:
        pass

    @abstractmethod
    def _check_dst_dir(self, dst_dir: str | Path) -> None:
        pass
