from .base import FileHandlerError


class AuthorizationError(FileHandlerError):
    def __init__(
            self,
            *,
            auth_parameters: list[str],
            source_address: str,
            ):
        super().__init__(f'Ошибка авторизации для ресурса {source_address}. '
                         f'Не указаны параметры {auth_parameters}.')
        self._auth_parameters = auth_parameters
        self._source_address = source_address

    @property
    def source_address(self) -> str:
        return self._source_address

    @property
    def required_parameters(self) -> list[str]:
        return self._auth_parameters
