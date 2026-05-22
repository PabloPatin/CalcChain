from dataclasses import dataclass
import json
from typing import Any

from calcchain_core.build.plan import BuildPlanEntry
from calcchain_core.common.hash import tree_sha256
from calcchain_core.models import FileMapEntry, RuleUse, SourceRef, SourceType


@dataclass(frozen=True)
class FileSetMap:
    name: str
    tree_sha256: str
    source: SourceRef | None
    sources: list[SourceRef]
    rules: RuleUse | None
    map: list[FileMapEntry]

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            'name': self.name,
            'tree_sha256': self.tree_sha256,
            'map': [entry.to_dict() for entry in self.map],
        }
        if self.source is not None:
            result['source'] = self.source.to_dict()
        if self.sources:
            result['sources'] = [source.to_dict() for source in self.sources]
        if self.rules is not None:
            result['rules'] = self.rules.to_dict()
        return result


def create_file_set_map(entries: list[BuildPlanEntry]) -> FileSetMap:
    if not entries:
        raise ValueError('file set map requires entries')
    roles = {entry.role for entry in entries}
    names = {entry.source_name for entry in entries}
    if len(roles) != 1 or len(names) != 1:
        raise ValueError('file set map entries must belong to one file set')

    sorted_entries = sorted(entries, key=lambda entry: (entry.work_path, entry.source_path))
    file_map = [
        FileMapEntry(
            sha256=_required_sha256(entry),
            source_path=entry.source_path,
            work_path=entry.work_path,
        )
        for entry in sorted_entries
    ]
    unique_sources = _unique_sources(entry.source for entry in sorted_entries)
    rules = _common_rules(sorted_entries)
    return FileSetMap(
        name=sorted_entries[0].source_name,
        tree_sha256=tree_sha256((entry.work_path, _required_sha256(entry)) for entry in sorted_entries),
        source=unique_sources[0] if len(unique_sources) == 1 else None,
        sources=unique_sources if len(unique_sources) != 1 else [],
        rules=rules,
        map=file_map,
    )


def _required_sha256(entry: BuildPlanEntry) -> str:
    if entry.sha256 is None:
        raise ValueError(f'build plan entry has no sha256: {entry.work_path}')
    return entry.sha256


def _unique_sources(sources) -> list[SourceRef]:
    result: list[SourceRef] = []
    seen: set[tuple] = set()
    for source in sources:
        key = (_type_id(source.type), source.location, source.path, source.revision, _plugin_key(source), _stable_extra(source))
        if key not in seen:
            seen.add(key)
            result.append(source)
    return result


def _common_rules(entries: list[BuildPlanEntry]) -> RuleUse | None:
    rules = [entry.rules for entry in entries if entry.rules is not None]
    if not rules:
        return None
    first = rules[0]
    if all(rule == first for rule in rules) and len(rules) == len(entries):
        return first
    return None


def _type_id(value: SourceType | str) -> str:
    if isinstance(value, SourceType):
        return value.value
    return value


def _plugin_key(source: SourceRef) -> tuple[str, str] | None:
    if source.plugin is None:
        return None
    return source.plugin.id, source.plugin.version


def _stable_extra(source: SourceRef) -> str:
    return json.dumps(source.extra, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
