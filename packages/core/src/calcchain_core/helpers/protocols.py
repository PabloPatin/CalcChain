from collections.abc import Callable
from dataclasses import dataclass
import inspect
from typing import Any


@dataclass(frozen=True)
class ProtocolCompatibilityError(TypeError):
    protocol_name: str
    missing_methods: tuple[str, ...]

    def __str__(self) -> str:
        methods = ', '.join(self.missing_methods)
        return f'{self.protocol_name} implementation is missing callable methods: {methods}'


def protocol_method_names(protocol: type) -> tuple[str, ...]:
    methods: list[str] = []
    seen: set[str] = set()
    for cls in reversed(inspect.getmro(protocol)):
        if cls.__module__ == 'typing':
            continue
        for name, value in cls.__dict__.items():
            if name.startswith('_') or name in seen:
                continue
            if _is_protocol_method(value):
                methods.append(name)
                seen.add(name)
    return tuple(methods)


def missing_protocol_methods(protocol: type, candidate: object) -> tuple[str, ...]:
    return tuple(
        name
        for name in protocol_method_names(protocol)
        if not callable(getattr(candidate, name, None))
    )


def ensure_protocol_methods(protocol: type, candidate: object) -> None:
    missing = missing_protocol_methods(protocol, candidate)
    if missing:
        raise ProtocolCompatibilityError(protocol.__name__, missing)


def _is_protocol_method(value: Any) -> bool:
    if isinstance(value, staticmethod | classmethod):
        return isinstance(value.__func__, Callable)
    return inspect.isfunction(value)
