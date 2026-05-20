from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import PurePosixPath

from calcchain_core.errors import BuildPlanError, ConfigFormatError, RulesError, SourceError
from calcchain_core.models import (
    BuildConfig,
    BuildInfo,
    BuildLock,
    CodeConfig,
    FileMapEntry,
    InputConfig,
    LockMetadata,
    RuleSet,
    RuleSetType,
    RuleUse,
    RulesFile,
    RulesReference,
    SourceRef,
    SourceType,
)
from calcchain_core.rules import apply_rule_set, get_rule_set
from calcchain_core.sources import SourceRegistry, sanitize_source_error_message, validate_source_ref


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
    try:
        _validate_build_sources(build)
    except (ConfigFormatError, SourceError) as err:
        raise BuildPlanError(sanitize_source_error_message(str(err))) from err

    if _uses_rules(build) and rules is None:
        raise BuildPlanError('rules are required when build uses rule_set')

    try:
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
    except SourceError as err:
        raise BuildPlanError(sanitize_source_error_message(str(err))) from err

    return BuildLock(
        schema_version=build.schema_version,
        lock=LockMetadata(
            created_at=datetime.now(timezone.utc).isoformat(),
            created_from='build.toml',
            source_sha256=_stable_sha256(build.to_dict()),
            source_sha256_field='build_toml_sha256',
        ),
        build=BuildInfo(name=build.build.name, description=build.build.description),
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
    try:
        _validate_lock_sources(lock)
    except SourceError as err:
        raise BuildPlanError(sanitize_source_error_message(str(err))) from err

    if _lock_uses_rules(lock) and rules is None:
        raise BuildPlanError('rules are required when lock uses rule_set')
    if rules is not None and lock.rules is not None and lock.rules.resolved is not None:
        expected_sha256 = lock.rules.resolved.get('sha256')
        actual_sha256 = _stable_sha256(rules.to_dict())
        if expected_sha256 is not None and expected_sha256.lower() != actual_sha256:
            raise BuildPlanError('rules sha256 does not match build lock')

    entries: list[BuildPlanEntry] = []
    used_work_paths: dict[str, BuildPlanEntry] = {}
    try:
        _validate_source_lock_ref(lock.code.source, registry)
        _ensure_concrete_revision(lock.code.source)
        entries.extend(_entries_for_code(lock, registry, rules))
        for input_config in lock.inputs:
            _validate_source_lock_ref(input_config.source, registry)
            _ensure_concrete_revision(input_config.source)
            entries.extend(_entries_for_input(input_config, registry, rules))
    except (ConfigFormatError, RulesError, SourceError) as err:
        raise BuildPlanError(sanitize_source_error_message(str(err))) from err

    for entry in entries:
        if entry.work_path in used_work_paths:
            previous = used_work_paths[entry.work_path]
            raise BuildPlanError(
                f'duplicate work path: {entry.work_path} '
                f'({previous.source_name} and {entry.source_name})',
            )
        used_work_paths[entry.work_path] = entry

    if lock.rules is not None and lock.rules.source is not None:
        _validate_source_lock_ref(lock.rules.source, registry)
        _ensure_concrete_revision(lock.rules.source)

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
            'sha256': _stable_sha256(rules.to_dict()),
        }
    return RulesReference(source=source, resolved=resolved)


def _validate_build_sources(build: BuildConfig) -> None:
    validate_source_ref(build.code.source)
    for input_config in build.inputs:
        validate_source_ref(input_config.source)
    if build.rules is not None and build.rules.source is not None:
        validate_source_ref(build.rules.source)


def _validate_lock_sources(lock: BuildLock) -> None:
    validate_source_ref(lock.code.source)
    for input_config in lock.inputs:
        validate_source_ref(input_config.source)
    if lock.rules is not None and lock.rules.source is not None:
        validate_source_ref(lock.rules.source)


def _resolve_source_for_lock(source: SourceRef, registry: SourceRegistry) -> SourceRef:
    registry.validate_config(source)
    resolved = registry.resolve_lock_ref(source)
    _validate_serializable_lock_ref(resolved)
    registry.validate_lock_ref(resolved)
    return resolved


def _validate_source_lock_ref(source: SourceRef, registry: SourceRegistry) -> None:
    _validate_serializable_lock_ref(source)
    registry.validate_lock_ref(source)


def _validate_serializable_lock_ref(source: SourceRef) -> None:
    SourceRef.from_dict(source.to_dict(), resolved_revision=_type_id(source.type) == SourceType.SVN.value)


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
    mapped_entries = apply_rule_set(files, rule_set) if rule_set is not None else _full_tree_map(files)
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


def _full_tree_map(files: list[str]) -> list[FileMapEntry]:
    entries = [
        FileMapEntry(sha256='', source_path=safe_file, work_path=safe_file)
        for safe_file in sorted(_normalize_relative_path(file, field='source path') for file in files)
    ]
    destinations: set[str] = set()
    for entry in entries:
        if entry.work_path in destinations:
            raise RulesError(f'duplicate destination path: {entry.work_path}')
        destinations.add(entry.work_path or '')
    return entries


def _required_entry_path(value: str | None, field: str) -> str:
    if value is None:
        raise BuildPlanError(f'{field} is required')
    return value


def _uses_rules(build: BuildConfig) -> bool:
    return build.code.rule_set is not None or any(input_config.rule_set is not None for input_config in build.inputs)


def _lock_uses_rules(lock: BuildLock) -> bool:
    return lock.code.rule_set is not None or any(input_config.rule_set is not None for input_config in lock.inputs)


def _ensure_concrete_revision(source: SourceRef) -> None:
    if _type_id(source.type) != SourceType.SVN.value:
        return
    revision = source.revision
    if isinstance(revision, int) and revision >= 0:
        return
    if isinstance(revision, str) and revision.isdecimal():
        return
    raise BuildPlanError('svn source revision must be concrete in build lock')


def _stable_sha256(data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def _normalize_relative_path(value: str, *, field: str) -> str:
    normalized = value.replace('\\', '/')
    if normalized.startswith('/') or _has_windows_drive(normalized):
        raise RulesError(f'{field} must be relative: {value}')
    path = PurePosixPath(normalized)
    if '..' in path.parts:
        raise RulesError(f'{field} must not contain path traversal: {value}')
    result = path.as_posix()
    if result in {'', '.'}:
        raise RulesError(f'{field} must identify a file: {value}')
    return result


def _has_windows_drive(value: str) -> bool:
    return len(value) >= 2 and value[1] == ':' and value[0].isalpha()


def _type_id(value: SourceType | str) -> str:
    if isinstance(value, SourceType):
        return value.value
    return value
