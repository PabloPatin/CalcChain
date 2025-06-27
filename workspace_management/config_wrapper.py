import warnings
from abc import ABCMeta, abstractmethod
from collections.abc import KeysView
from dataclasses import dataclass, asdict
from functools import wraps, WRAPPER_ASSIGNMENTS
from os import GenericAlias
from types import UnionType
from typing import get_origin


class ConfigValidationError(Exception):
    pass


class LostConfigsError(ConfigValidationError):
    def __init__(self, lost_configs: set) -> None:
        super().__init__(f'Не найдены конфигурации: {lost_configs}')


class ConfigTypeError(ConfigValidationError):
    def __init__(self, configuration: str, _type: str, conf_type: type) -> None:
        super().__init__(
                f'Не правильный тип конфигурации {configuration}: '
                f'{conf_type}, должен быть {_type}',
                )


class ExcessParamsWarning(Warning):
    pass


def _drop_excess_configs(configs: dict, annotations: dict) -> dict:
    if other_keys := configs.keys() - annotations.keys():
        warnings.warn(
                f'В файле конфигурации заданы лишние параметры {other_keys}',
                ExcessParamsWarning,
                )

    for key in other_keys:
        configs.pop(key)

    return configs


def _check_needed_configs(configs: dict, annotations: dict, defaults: KeysView[str]) -> None:
    lost_keys = {
        key for key, value in annotations.items()
        if key not in configs.keys() | defaults
        }
    if lost_keys:
        raise LostConfigsError(lost_keys)


def _check_configs_types(configs: dict, annotations: dict) -> None:
    for key, _type in annotations.items():
        _type = get_origin(_type) if isinstance(_type, GenericAlias) else _type
        if key in configs and not isinstance(configs[key], _type):
            raise ConfigTypeError(key, _type, type(configs[key]))


def _expand_config(configs: dict, annotations: dict) -> dict:
    for key, _type in annotations.items():
        if (
                not isinstance(_type, UnionType)
                and not isinstance(_type, GenericAlias)
                and issubclass(_type, ConfigInterface)
        ):
            configs[key] = _type(configs[key])
    return configs


class ConfigInterface(metaclass=ABCMeta):
    @abstractmethod
    def __init__(self, configs: dict):
        pass

    @abstractmethod
    def to_dict(self) -> dict:
        pass


def config[T](config_cls: type[T]) -> type[ConfigInterface] | type[T]:
    config_cls = dataclass(config_cls)

    @wraps(config_cls,
           assigned=(*WRAPPER_ASSIGNMENTS, '__dataclass_fields__', '__dataclass_params__'),
           updated=())
    class ConfigWrapper(config_cls, ConfigInterface):
        def __init__(self, configs: dict):
            # TODO: сделать функции методами
            configs = _drop_excess_configs(configs, config_cls.__annotations__)

            _check_needed_configs(configs, config_cls.__annotations__, vars(config_cls).keys())

            _check_configs_types(configs, config_cls.__annotations__)

            configs = _expand_config(configs, config_cls.__annotations__)

            config_cls.__init__(self, **configs)

        def to_dict(self: type[T]) -> dict:
            return asdict(self)

    return ConfigWrapper


if __name__ == '__main__':
    @config
    class Data:
        a: int
        b: str
        c: float = 1.8


    d = Data({'a': 1, 'b': 'lol', 'c': 1.9, 'd': 2.1})
    print(d)
