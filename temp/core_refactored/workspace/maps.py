from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ..common.hash import sha256_dict, tree_sha256
from ..io.source import SourceRef
from ..rules import RuleUse
from ..utils.validation import mapping_value, optional_list, required_list, required_mapping, required_str
from .file_map import FileMapEntry


@dataclass(frozen=True)
class FileSetMap:
    name: str
    tree_sha256: str
    sources: list[SourceRef] = field(default_factory=list)
    rules: RuleUse | None = None
    map: list[FileMapEntry] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]):
        return cls(
            name=required_str(data, 'name'),
            tree_sha256=required_str(data, 'tree_sha256'),
            sources=[
                SourceRef.from_dict(dict(mapping_value(item, f'sources[{index}]')))
                for index, item in enumerate(optional_list(data, 'sources'), start=1)
            ],
            rules=RuleUse.from_dict(required_mapping(data, 'rules')) if 'rules' in data else None,
            map=[
                FileMapEntry.from_dict(mapping_value(item, f'map[{index}]'))
                for index, item in enumerate(required_list(data, 'map'), start=1)
            ],
        )

    def to_dict(self) -> dict[str, Any]:
        result = {
            'name': self.name,
            'tree_sha256': self.tree_sha256,
            'sources': [source.to_dict() for source in self.sources],
            'map': [entry.to_dict() for entry in self.map],
        }
        if self.rules is not None:
            result['rules'] = self.rules.to_dict()
        return result


def file_set_from_entries(name: str, entries: Iterable[Any]) -> FileSetMap:
    entries = list(entries)
    file_map = [
        FileMapEntry(
            sha256=entry.sha256 or '',
            source_path=entry.source_path,
            work_path=entry.work_path,
            target_path=None,
        )
        for entry in entries
    ]
    return FileSetMap(
        name=name,
        tree_sha256=tree_sha256((entry.work_path or '', entry.sha256 or '') for entry in file_map),
        sources=_unique_sources(entry.source for entry in entries),
        rules=_common_rules(entries),
        map=file_map,
    )


def _unique_sources(sources: Iterable[SourceRef]) -> list[SourceRef]:
    seen: set[str] = set()
    result: list[SourceRef] = []
    for source in sources:
        key = sha256_dict(source.to_dict())
        if key in seen:
            continue
        seen.add(key)
        result.append(source)
    return result


def _common_rules(entries: list[Any]) -> RuleUse | None:
    rules = [entry.rules for entry in entries if entry.rules is not None]
    if not rules:
        return None
    first = rules[0]
    if all(rule == first for rule in rules):
        return first
    return None
