from collections.abc import Mapping
import re
from typing import Any

from ..common.errors import ConfigFormatError

_SHA256_RE = re.compile(r'^[0-9a-fA-F]{64}$')


def required_mapping(data: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    if key not in data:
        raise ConfigFormatError(f'missing required field: {key}')
    return mapping_value(data[key], key)


def optional_mapping(data: Mapping[str, Any], key: str) -> Mapping[str, Any] | None:
    if key not in data:
        return None
    return mapping_value(data[key], key)


def mapping_value(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ConfigFormatError(f'{field} must be an object')
    return value


def required_list(data: Mapping[str, Any], key: str) -> list[Any]:
    if key not in data:
        raise ConfigFormatError(f'missing required field: {key}')
    return list_value(data[key], key)


def optional_list(data: Mapping[str, Any], key: str) -> list[Any]:
    if key not in data:
        return []
    return list_value(data[key], key)


def list_value(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ConfigFormatError(f'{field} must be a list')
    return value


def optional_str(data: Mapping[str, Any], key: str) -> str | None:
    if key not in data:
        return None
    return string_value(data[key], key)


def required_str(data: Mapping[str, Any], key: str) -> str:
    if key not in data:
        raise ConfigFormatError(f'missing required field: {key}')
    return string_value(data[key], key)


def required_sha256(data: Mapping[str, Any], key: str) -> str:
    value = required_str(data, key)
    if _SHA256_RE.fullmatch(value) is None:
        raise ConfigFormatError(f'{key} must be a sha256 hex digest')
    return value.lower()


def string_mapping(data: Mapping[str, Any]) -> dict[str, str]:
    return {string_value(key, 'mapping key'): string_value(value, f'{key} value') for key, value in data.items()}


def string_value(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ConfigFormatError(f'{field} must be a string')
    return value
