from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib

from ..common.errors import BuildPlanError, RulesError, SourceError
from ..common.hash import sha256_dict
from ..io.source import SourceRef, SourceRegistry
from ..rules import RuleSet, RuleSetType, RuleUse, RulesFile, get_rule_set
from ..workspace.file_map import FileMapEntry, apply_rule_set, full_tree_map
from .config import BuildConfig, CodeConfig, InputConfig, RulesReference
from .lock import BuildLock, LockMetadata


@dataclass(frozen=True)
class BuildPlanEntry:
    role: str
    source_name: str
    source: SourceRef
    source_path: str
    work_path: str
    sha256: str | None = None
    rules: RuleUse | None = None


@dataclass(frozen=True)
class BuildPlan:
    lock: BuildLock
    entries: list[BuildPlanEntry]
    warnings: list[str]


def create_build_lock(
    build: BuildConfig,
    registry: SourceRegistry,
    rules: RulesFile | None,
) -> BuildLock:
    if _uses_rules(build) and rules is None:
        raise BuildPlanError('rules are required when build uses rule_set')

    build_data = build.to_dict()
    code_source = _resolve_source_for_lock(build.code.source, registry)
    input_configs = [
        InputConfig(
            source=_resolve_source_for_lock(input_config.source, registry),
            name=input_config.name,
            rule_set=input_config.rule_set,
        )
        for input_config in build.inputs
    ]
    rules_reference = _resolve_rules_reference(build.rules, registry, rules)

    return BuildLock(
        schema_version=build.schema_version,
        lock=LockMetadata(
            created_at=datetime.now(timezone.utc).isoformat(),
            created_from='build.toml',
            source_sha256=sha256_dict(build_data),
        ),
        build=build.build,
        code=CodeConfig(
            source=code_source,
            name=build.code.name,
            version=build.code.version,
            rule_set=build.code.rule_set,
        ),
        inputs=input_configs,
        rules=rules_reference,
    )


def validate_build_lock(
    lock: BuildLock,
    registry: SourceRegistry,
    rules: RulesFile | None,
) -> BuildPlan:
    if _lock_uses_rules(lock) and rules is None:
        raise BuildPlanError('rules are required when lock uses rule_set')
    if rules is not None and lock.rules is not None and lock.rules.resolved is not None:
        expected_sha256 = lock.rules.resolved.get('sha256')
        actual_sha256 = sha256_dict(rules.to_dict())
        if expected_sha256 is not None and str(expected_sha256).lower() != actual_sha256:
            raise BuildPlanError('rules sha256 does not match build lock')

    entries: list[BuildPlanEntry] = []
    used_work_paths: dict[str, BuildPlanEntry] = {}

    try:
        registry.validate_lock_ref(lock.code.source)
        entries.extend(_entries_for_code(lock, registry, rules))
        for input_config in lock.inputs:
            registry.validate_lock_ref(input_config.source)
            entries.extend(_entries_for_input(input_config, registry, rules))
        if lock.rules is not None and lock.rules.source is not None:
            registry.validate_lock_ref(lock.rules.source)
    except (RulesError, SourceError) as err:
        raise BuildPlanError(str(err)) from err

    for entry in entries:
        if entry.work_path in used_work_paths:
            previous = used_work_paths[entry.work_path]
            raise BuildPlanError(
                f'duplicate work path: {entry.work_path} '
                f'({previous.source_name} and {entry.source_name})',
            )
        used_work_paths[entry.work_path] = entry

    return BuildPlan(lock=lock, entries=entries, warnings=[])


def _resolve_rules_reference(
    reference: RulesReference | None,
    registry: SourceRegistry,
    rules: RulesFile | None,
) -> RulesReference | None:
    if reference is None:
        return None
    source = _resolve_source_for_lock(reference.source, registry) if reference.source is not None else None
    resolved = None
    if rules is not None:
        resolved = {
            'schema_version': rules.schema_version,
            'sha256': sha256_dict(rules.to_dict()),
        }
    return RulesReference(source=source, resolved=resolved)


def _resolve_source_for_lock(source: SourceRef, registry: SourceRegistry) -> SourceRef:
    try:
        registry.validate_config(source)
        resolved = registry.resolve_lock_ref(source)
        registry.validate_lock_ref(resolved)
    except SourceError as err:
        raise BuildPlanError(str(err)) from err
    return resolved


def _entries_for_code(
    lock: BuildLock,
    registry: SourceRegistry,
    rules: RulesFile | None,
) -> list[BuildPlanEntry]:
    rule_set = None
    if lock.code.rule_set is not None:
        if rules is None:
            raise BuildPlanError('rules are required when code uses rule_set')
        rule_set = get_rule_set(rules, lock.code.rule_set, RuleSetType.CODE)
    return _entries_for_source(
        role='code',
        source_name=lock.code.name,
        source=lock.code.source,
        rule_set_name=lock.code.rule_set,
        rule_set=rule_set,
        registry=registry,
    )


def _entries_for_input(
    input_config: InputConfig,
    registry: SourceRegistry,
    rules: RulesFile | None,
) -> list[BuildPlanEntry]:
    rule_set = None
    if input_config.rule_set is not None:
        if rules is None:
            raise BuildPlanError('rules are required when input uses rule_set')
        rule_set = get_rule_set(rules, input_config.rule_set, RuleSetType.INPUT)
    return _entries_for_source(
        role='input',
        source_name=input_config.name,
        source=input_config.source,
        rule_set_name=input_config.rule_set,
        rule_set=rule_set,
        registry=registry,
    )


def _entries_for_source(
    *,
    role: str,
    source_name: str,
    source: SourceRef,
    rule_set_name: str | None,
    rule_set: RuleSet | None,
    registry: SourceRegistry,
) -> list[BuildPlanEntry]:
    files = registry.list_files(source)
    mapped_entries = apply_rule_set(files, rule_set) if rule_set is not None else full_tree_map(files)
    rule_use = None
    if rule_set is not None and rule_set_name is not None:
        rule_use = RuleUse(set=rule_set_name, status=rule_set.status or None)
    return [
        BuildPlanEntry(
            role=role,
            source_name=source_name,
            source=source,
            source_path=_required_entry_path(entry.source_path, 'source_path'),
            work_path=_required_entry_path(entry.work_path, 'work_path'),
            sha256=hashlib.sha256(
                registry.read_file(source, _required_entry_path(entry.source_path, 'source_path')),
            ).hexdigest(),
            rules=rule_use,
        )
        for entry in mapped_entries
    ]


def _required_entry_path(value: str | None, field: str) -> str:
    if value is None:
        raise BuildPlanError(f'{field} is required')
    return value


def _uses_rules(build: BuildConfig) -> bool:
    return build.code.rule_set is not None or any(input_config.rule_set is not None for input_config in build.inputs)


def _lock_uses_rules(lock: BuildLock) -> bool:
    return lock.code.rule_set is not None or any(input_config.rule_set is not None for input_config in lock.inputs)
