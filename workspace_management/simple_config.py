from abc import ABCMeta, abstractmethod
from collections.abc import KeysView, Callable
from copy import copy
from dataclasses import dataclass
from functools import wraps, WRAPPER_ASSIGNMENTS
from types import UnionType, GenericAlias
from typing import get_origin, Any


class ConfigValidationError(Exception):
    pass


class LostConfigsError(ConfigValidationError):
    def __init__(self, lost_configs: set[str]) -> None:
        super().__init__(f'Не найдены конфигурации: {lost_configs}')


class ConfigTypeError(ConfigValidationError):
    def __init__(self, configuration: str, _type: str, conf_type: type) -> None:
        super().__init__(
                f'Неправильный тип конфигурации {configuration}: '
                f'{conf_type}, должен быть {_type}',
                )


class ExcessParamsError(ConfigValidationError):
    def __init__(self, excess_keys: set[str]) -> None:
        super().__init__(
                f'В файле конфигурации заданы лишние параметры {excess_keys}',
                )


class ConfigInterface(metaclass=ABCMeta):
    @abstractmethod
    def __init__(self, configs: dict):
        pass

    @abstractmethod
    def to_dict(self) -> dict:
        pass


def asdict(data: Any) -> dict | list:  # noqa ANN401
    if isinstance(data, ConfigInterface):
        return data.to_dict()
    if isinstance(data, dict):
        return {key: asdict(value) for key, value in data.items()}
    elif isinstance(data, list | tuple | set):
        return [asdict(item) for item in data]
    else:
        return data


def _split_excess_configs(configs: dict, annotations: dict) -> tuple[dict, dict]:
    other_keys = configs.keys() - annotations.keys()
    others = {key: configs.pop(key) for key in other_keys}
    return configs, others


def _check_needed_configs(
        configs: dict,
        annotations: dict,
        defaults: KeysView[str],
        ) -> None:
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


def config[T](cls: type[T] | None = None, partial: bool = False) -> (
        type[T] | type[ConfigInterface] | Callable
):
    def decorator(config_cls: type[T]) -> type[T] | type[ConfigInterface]:
        config_cls = dataclass(config_cls)

        @wraps(config_cls,
               assigned=(*WRAPPER_ASSIGNMENTS, '__dataclass_fields__', '__dataclass_params__'),
               updated=())
        class ConfigWrapper(config_cls, ConfigInterface):
            def __init__(self, configs: dict, _allow_extra: bool = partial):
                configs, extra_configs = _split_excess_configs(configs, config_cls.__annotations__)
                if extra_configs and not _allow_extra:
                    raise ExcessParamsError(set(extra_configs.keys()))
                _check_needed_configs(configs, config_cls.__annotations__, vars(config_cls).keys())
                configs = _expand_config(configs, config_cls.__annotations__)
                _check_configs_types(configs, config_cls.__annotations__)

                config_cls.__init__(self, **configs)
                self.__extra_configs__ = extra_configs if partial else {}

            def to_dict(self: type[T]) -> dict:
                data = copy(self.__dict__)
                data.pop('__extra_configs__')
                return asdict(data)

            @property
            def extra_configs(self) -> dict:
                return self.__extra_configs__

        return ConfigWrapper

    if cls is None:
        return decorator
    else:
        return decorator(cls)


class ConfigUnion(ConfigInterface):
    def __init__(self, configs: dict, **config_classes: type[ConfigInterface]):
        self.configs = {}
        remain = configs
        for attr, config_cls in config_classes.items():
            found, remain = _split_excess_configs(remain, config_cls.__annotations__)
            self.configs[attr] = config_cls(found)
        if remain:
            raise ExcessParamsError(set(remain.keys()))

    def __getattribute__(self, item: str) -> ...:
        try:
            return object.__getattribute__(self, item)
        except AttributeError:
            pass
        for config_name in self.configs:
            if item == config_name:
                return self.configs[config_name]
        for config_values in self.configs.values():
            try:
                return config_values.__getattribute__(item)
            except AttributeError:
                pass
        raise AttributeError

    def to_dict(self) -> dict:
        data = {}
        for conf in self.configs.values():
            data |= conf.to_dict()
        return data
