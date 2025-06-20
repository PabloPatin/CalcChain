from datetime import datetime
from enum import StrEnum
from typing import NamedTuple, Literal


class Info(NamedTuple):
    xml: str
    url: str
    relative_url: str
    entry_kind: str
    entry_path: str
    entry_revision: int
    repository_root: str
    repository_uuid: str
    commit_author: str | None
    commit_date: datetime
    commit_revision: int


class Action(StrEnum):
    @classmethod
    def find_key(cls, value: str) -> StrEnum | None:
        for sub in Action.__members__.values():
            if sub.value == value:
                return sub
        return None

    ADD = 'A'
    MODIFY = 'M'
    DELETE = 'D'


class Depth(StrEnum):
    EMPTY = 'empty'  # Только папка без содержимого
    FILES = 'files'  # Папка и файлы, хранящиеся в ней
    IMMEDIATES = 'immediates'  # Папка и все объекты непосредственно в ней находящиеся
    INFINITY = 'infinity'  # Папка со всем содержимым


class LogPath(NamedTuple):
    prop_mods: bool
    text_mods: bool
    kind: Literal['dir', 'file']
    action: StrEnum
    path: str


class LogRecord(NamedTuple):
    xml: str
    revision: int
    author: str
    date: datetime
    paths: tuple[LogPath] | None
    msg: str | None


class StorageNode(NamedTuple):
    xml: str
    rel_path: str
    kind: Literal['file', 'dir']
    name: str
    size: int | None
    revision: int
    author: str
    date: datetime


class StorageTree(NamedTuple):
    xml: str
    root: str
    nodes: tuple[StorageNode]
