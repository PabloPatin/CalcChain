from dataclasses import dataclass, field
import re

from ..common.errors import RulesError
from ..rules import RuleSetType, RulesFile
from .snapshot import Snapshot, SnapshotDiff, diff_snapshots


@dataclass(frozen=True)
class FileGroups:
    code: list[str] = field(default_factory=list)
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)
    temp: list[str] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    diff: SnapshotDiff | None = None

    def to_dict(self) -> dict:
        return {
            'code': list(self.code),
            'inputs': list(self.inputs),
            'outputs': list(self.outputs),
            'logs': list(self.logs),
            'temp': list(self.temp),
            'ignored': list(self.ignored),
            'unknown': list(self.unknown),
            'deleted': list(self.deleted),
        }


def classify_files(
    build_result,
    pre_run_snapshot: Snapshot,
    post_run_snapshot: Snapshot,
    rules: RulesFile | None,
) -> FileGroups:
    diff = diff_snapshots(pre_run_snapshot, post_run_snapshot)
    changed = [entry.path for entry in [*diff.added, *diff.modified]]
    output_rules_exist = _has_rule_type(rules, RuleSetType.OUTPUT)
    groups: dict[str, list[str]] = {
        'outputs': [],
        'logs': [],
        'temp': [],
        'ignored': [],
        'unknown': [],
    }
    for path in changed:
        group = _classify_changed_path(path, rules)
        if group is None:
            group = 'unknown' if output_rules_exist else 'outputs'
        groups[group].append(path)
    return FileGroups(
        code=_work_paths_from_map(build_result.code_set.map),
        inputs=sorted(path for file_set in build_result.input_sets for path in _work_paths_from_map(file_set.map)),
        outputs=sorted(groups['outputs']),
        logs=sorted(groups['logs']),
        temp=sorted(groups['temp']),
        ignored=sorted(groups['ignored']),
        unknown=sorted(groups['unknown']),
        deleted=sorted(entry.path for entry in diff.deleted),
        diff=diff,
    )


def _classify_changed_path(path: str, rules: RulesFile | None) -> str | None:
    if rules is None:
        return None
    for rule_type, group_name in (
        (RuleSetType.IGNORE, 'ignored'),
        (RuleSetType.TEMP, 'temp'),
        (RuleSetType.LOGS, 'logs'),
        (RuleSetType.OUTPUT, 'outputs'),
    ):
        if _matches_any_rule_set(path, rules, rule_type):
            return group_name
    return None


def _matches_any_rule_set(path: str, rules: RulesFile, rule_type: RuleSetType) -> bool:
    try:
        return any(
            rule_set.type == rule_type and any(re.fullmatch(rule.source, path) for rule in rule_set.rules)
            for rule_set in rules.rule_sets.values()
        )
    except re.error as err:
        raise RulesError(f'invalid output classification regex: {err}') from err


def _has_rule_type(rules: RulesFile | None, rule_type: RuleSetType) -> bool:
    return rules is not None and any(rule_set.type == rule_type for rule_set in rules.rule_sets.values())


def _work_paths_from_map(entries) -> list[str]:
    return sorted(entry.work_path for entry in entries if entry.work_path is not None)
