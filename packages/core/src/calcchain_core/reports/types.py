from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True)
class ReportOwner:
    id: str
    version: str | None = None


@dataclass(frozen=True)
class ReportContext:
    owner: ReportOwner | None
    capability_id: str
    manifest: Mapping[str, Any]

    @property
    def owner_id(self) -> str | None:
        return self.owner.id if self.owner is not None else None

    @property
    def owner_version(self) -> str | None:
        return self.owner.version if self.owner is not None else None


@dataclass(frozen=True)
class ReportDescriptor:
    id: str
    title: str
    content_type: str | None = None
    file_extension: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id:
            raise ValueError('report descriptor id must be a non-empty string')
        if not isinstance(self.title, str) or not self.title:
            raise ValueError('report descriptor title must be a non-empty string')


@dataclass(frozen=True)
class ReportRequest:
    report_id: str
    manifest_path: Path | str | None = None
    parameters: Mapping[str, Any] = field(default_factory=dict)
    output: str = 'return'

    def __post_init__(self) -> None:
        if not isinstance(self.report_id, str) or not self.report_id:
            raise ValueError('report_id must be a non-empty string')
        if self.output not in {'return', 'file'}:
            raise ValueError('report output must be return or file')
        object.__setattr__(self, 'parameters', dict(self.parameters))


@dataclass(frozen=True)
class ReportResult:
    report_id: str
    content: bytes | str | None
    content_type: str
    path: Path | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.report_id, str) or not self.report_id:
            raise ValueError('report_id must be a non-empty string')
        if not isinstance(self.content_type, str) or not self.content_type:
            raise ValueError('report content_type must be a non-empty string')
        object.__setattr__(self, 'path', Path(self.path) if self.path is not None else None)
        object.__setattr__(self, 'metadata', dict(self.metadata))


def freeze_manifest(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): freeze_manifest(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(freeze_manifest(item) for item in value)
    if isinstance(value, set | frozenset):
        return frozenset(freeze_manifest(item) for item in value)
    return value
