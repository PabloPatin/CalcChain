from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SourceAdapter(Protocol):
    def validate_config(self, ref: Mapping[str, Any], context: 'SourceContext') -> None:
        ...

    def resolve_lock_ref(self, ref: Mapping[str, Any], context: 'SourceContext') -> dict[str, Any]:
        ...

    def validate_lock_ref(self, ref: Mapping[str, Any], context: 'SourceContext') -> None:
        ...

    def list_files(self, ref: Mapping[str, Any], context: 'SourceContext') -> list[str]:
        ...

    def read_file(self, ref: Mapping[str, Any], relative_path: str, context: 'SourceContext') -> bytes:
        ...

    def is_versionable(self, ref: Mapping[str, Any], context: 'SourceContext') -> bool:
        ...


@runtime_checkable
class TargetAdapter(Protocol):
    def validate_config(self, ref: Mapping[str, Any], context: 'TargetContext') -> None:
        ...

    def resolve_lock_ref(self, ref: Mapping[str, Any], context: 'TargetContext') -> dict[str, Any]:
        ...

    def validate_lock_ref(self, ref: Mapping[str, Any], context: 'TargetContext') -> None:
        ...

    def ensure_root(self, ref: Mapping[str, Any], context: 'TargetContext') -> dict[str, Any]:
        ...

    def write_file(
        self,
        ref: Mapping[str, Any],
        relative_path: str,
        data: bytes,
        context: 'TargetContext',
    ) -> Mapping[str, Any]:
        ...

    def is_versionable(self, ref: Mapping[str, Any], context: 'TargetContext') -> bool:
        ...


@runtime_checkable
class ReportAdapter(Protocol):
    def describe(self, context: 'ReportContext') -> 'ReportDescriptor':
        ...

    def render(self, request: 'ReportRequest', context: 'ReportContext') -> 'ReportResult':
        ...


@runtime_checkable
class SecretsAdapter(Protocol):
    def can_resolve(self, key: str, context: 'SecretsContext') -> bool:
        ...

    def resolve(self, key: str, context: 'SecretsContext') -> str:
        ...


__all__ = [
    'ReportAdapter',
    'SecretsAdapter',
    'SourceAdapter',
    'TargetAdapter',
]
