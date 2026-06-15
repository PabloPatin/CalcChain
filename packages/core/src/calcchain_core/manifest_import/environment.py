from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import re

from ..build import BuildConfig
from ..config import (
    BUILD_CONFIG_SCHEMA_VERSION,
    PUBLISH_CONFIG_SCHEMA_VERSION,
    RULES_FILE_SCHEMA_VERSION,
    RUN_CONFIG_SCHEMA_VERSION,
)
from ..io.source import SourceRegistry
from ..manifest import Manifest
from ..publish import PublishConfig
from ..restore import RestoreRequest, RestoreResult, restore_from_manifest
from ..rules import RulesFile
from ..run import RunConfig
from ..utils.json import read_json, write_json
from ..utils.toml import write_toml


@dataclass(frozen=True)
class ManifestEnvironmentRequest:
    manifest_path: Path
    target_job_dir: Path
    dry_run: bool = False
    restore_work: bool = True
    write_publish_config: bool = True


@dataclass(frozen=True)
class ManifestEnvironmentResult:
    target_job_dir: Path
    written_files: list[str] = field(default_factory=list)
    restored_files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    status: str = 'created'


class ManifestEnvironmentError(Exception):
    """Raised when a runnable job environment cannot be derived from a manifest."""


def create_environment_from_manifest(
    request: ManifestEnvironmentRequest,
    source_registry: SourceRegistry | None = None,
) -> ManifestEnvironmentResult:
    manifest_path = Path(request.manifest_path)
    target_job_dir = Path(request.target_job_dir)
    manifest = Manifest.from_dict(read_json(manifest_path))
    manifest_data = manifest.to_dict()
    warnings: list[str] = []

    generated_manifest = _environment_manifest(manifest_data, target_job_dir)
    build_config = _build_config_from_manifest(generated_manifest, warnings)
    run_config = _run_config_from_manifest(generated_manifest, warnings)
    publish_config, rules_config = (
        _publish_config_from_manifest(generated_manifest, warnings)
        if request.write_publish_config
        else (None, None)
    )

    planned_files = ['manifest.json', 'build.toml']
    if run_config is not None:
        planned_files.append('run.toml')
    if publish_config is not None:
        planned_files.append('publish.toml')
    if rules_config is not None:
        planned_files.append('rules.json')

    restore_result = RestoreResult(status='skipped')
    if request.restore_work:
        restore_result = restore_from_manifest(
            RestoreRequest(
                manifest_path=manifest_path,
                target_job_dir=target_job_dir,
                dry_run=request.dry_run,
            ),
            source_registry or SourceRegistry(),
        )

    if request.dry_run:
        return ManifestEnvironmentResult(
            target_job_dir=target_job_dir,
            written_files=planned_files,
            restored_files=list(restore_result.restored_files),
            warnings=warnings,
            status='planned',
        )

    target_job_dir.mkdir(parents=True, exist_ok=True)
    write_json(generated_manifest, target_job_dir / 'manifest.json')
    write_toml(build_config, target_job_dir / 'build.toml')
    if run_config is not None:
        write_toml(run_config, target_job_dir / 'run.toml')
    if publish_config is not None:
        write_toml(publish_config, target_job_dir / 'publish.toml')
    if rules_config is not None:
        write_json(rules_config, target_job_dir / 'rules.json')

    return ManifestEnvironmentResult(
        target_job_dir=target_job_dir,
        written_files=planned_files,
        restored_files=list(restore_result.restored_files),
        warnings=warnings,
        status='created',
    )


def _environment_manifest(data: Mapping[str, Any], target_job_dir: Path) -> dict[str, Any]:
    result = Manifest.from_dict(data).to_dict()
    job = dict(_required_mapping(result, 'job'))
    job['job_dir'] = str(target_job_dir)
    result['job'] = job
    return result


def _build_config_from_manifest(data: Mapping[str, Any], warnings: list[str]) -> dict[str, Any]:
    job = _required_mapping(data, 'job')
    build = _required_mapping(data, 'build')
    code_set = _required_mapping(build, 'code')

    config: dict[str, Any] = {
        'schema_version': BUILD_CONFIG_SCHEMA_VERSION,
        'build': {
            'name': _string_or(job.get('id'), 'imported_from_manifest'),
            'description': 'Generated from manifest.json',
        },
        'code': {
            'name': _string_or(code_set.get('name'), 'code'),
            'version': _string_or(code_set.get('tree_sha256'), ''),
            'source': _first_source(code_set, 'build.code', warnings),
        },
        'inputs': [],
    }

    for index, raw_input in enumerate(_optional_list(build.get('inputs')), start=1):
        input_set = _mapping(raw_input, f'build.inputs[{index}]')
        if input_set.get('name') == 'frozen_inputs':
            warnings.append('frozen_inputs are restored into work but are not converted to build.toml inputs')
            continue
        config['inputs'].append(
            {
                'name': _string_or(input_set.get('name'), f'input_{index}'),
                'source': _first_source(input_set, f'build.inputs[{index}]', warnings),
            },
        )

    BuildConfig.from_dict(config)
    return config


def _run_config_from_manifest(data: Mapping[str, Any], warnings: list[str]) -> dict[str, Any] | None:
    run = _optional_mapping(data.get('run'))
    if run is None:
        warnings.append('manifest has no run block; run.toml was not generated')
        return None

    command = _optional_list(run.get('command'))
    if not command:
        warnings.append('manifest run block has no command; run.toml was not generated')
        return None

    executable = _string_or(command[0], '')
    if not executable:
        warnings.append('manifest run.command[0] is empty; run.toml was not generated')
        return None

    config: dict[str, Any] = {
        'schema_version': RUN_CONFIG_SCHEMA_VERSION,
        'run': {
            'executable': executable,
            'args': [str(item) for item in command[1:]],
            'cwd': _normalized_run_cwd(run.get('cwd'), warnings),
            'timeout_seconds': run.get('timeout_seconds') if isinstance(run.get('timeout_seconds'), int) else None,
            'encoding': _string_or(run.get('encoding'), 'utf-8'),
            'stdin_mode': 'none',
            'stdin_text': '',
        },
    }

    env = _run_env_from_manifest(run, warnings)
    if env:
        config['run']['env'] = env

    stdin = _optional_mapping(run.get('stdin'))
    if stdin is not None and stdin.get('mode') == 'script':
        text = stdin.get('text')
        if isinstance(text, str):
            config['run']['stdin_mode'] = 'script'
            config['run']['stdin_text'] = text
        else:
            warnings.append('manifest run.stdin has script mode but no text; stdin script was not restored')

    RunConfig.from_dict(config)
    return config


def _publish_config_from_manifest(
    data: Mapping[str, Any],
    warnings: list[str],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    publication = _optional_mapping(data.get('publication'))
    if publication is None:
        warnings.append('manifest has no publication block; publish.toml was not generated')
        return None, None

    service_target = _optional_mapping(publication.get('service_target'))
    if service_target is None:
        warnings.append('manifest publication has no service_target; publish.toml was not generated')
        return None, None

    targets: list[dict[str, Any]] = []
    rule_sets: dict[str, Any] = {}
    used_target_names: set[str] = set()

    for category, rule_type in [('outputs', 'output'), ('logs', 'logs'), ('temp', 'temp')]:
        for index, raw_group in enumerate(_optional_list(publication.get(category)), start=1):
            group = _mapping(raw_group, f'publication.{category}[{index}]')
            target = _optional_mapping(group.get('target'))
            if target is None:
                warnings.append(f'publication.{category}[{index}] has no target; group skipped')
                continue

            rule_set_name = _unique_name(_publication_rule_set_name(group, category, index), set(rule_sets))
            rules = _rules_from_publication_group(group, category, rule_type, warnings)
            if not rules:
                warnings.append(f'publication.{category}[{index}] has no file map; group skipped')
                continue
            rule_sets[rule_set_name] = {
                'type': rule_type,
                'status': 'generated',
                'description': 'Generated from manifest publication map',
                'ensure_all_files': False,
                'rules': rules,
            }

            target_name = _unique_name(_string_or(group.get('name'), f'{category}_{index}'), used_target_names)
            used_target_names.add(target_name)
            targets.append(
                {
                    'name': target_name,
                    **dict(target),
                    'rule_sets': [rule_set_name],
                },
            )

    if not targets:
        warnings.append('manifest publication has no restorable result targets; publish.toml was not generated')
        return None, None

    publish_config = {
        'schema_version': PUBLISH_CONFIG_SCHEMA_VERSION,
        'publish': {'message': 'Generated from manifest.json'},
        'service_target': dict(service_target),
        'targets': targets,
    }
    rules_config = {
        'schema_version': RULES_FILE_SCHEMA_VERSION,
        'rules_file': {'generated_from': 'manifest.json'},
        'rule_sets': rule_sets,
    }

    PublishConfig.from_dict(publish_config)
    RulesFile.from_dict(rules_config)
    return publish_config, rules_config


def _run_env_from_manifest(run: Mapping[str, Any], warnings: list[str]) -> dict[str, Any]:
    raw_env = _optional_mapping(run.get('env')) or {}
    public: dict[str, str] = {}
    secret_names: list[str] = []

    for key, value in raw_env.items():
        if key == 'secrets':
            secret_names.extend(str(item) for item in _optional_list(value))
            continue
        if isinstance(value, str):
            public[str(key)] = value
        elif isinstance(value, int | float | bool):
            public[str(key)] = str(value)

    secret_names.extend(str(item) for item in _optional_list(run.get('secret_names')))
    if secret_names:
        warnings.append(
            'secret env names are present in manifest but secret refs/values are not recoverable: '
            + ', '.join(sorted(set(secret_names))),
        )

    return {'public': public} if public else {}


def _rules_from_publication_group(
    group: Mapping[str, Any],
    category: str,
    rule_type: str,
    warnings: list[str],
) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for index, raw_entry in enumerate(_optional_list(group.get('map')), start=1):
        entry = _mapping(raw_entry, f'publication.{category}.map[{index}]')
        work_path = _relative_path(entry.get('work_path') or entry.get('source_path'))
        target_path = _relative_path(entry.get('target_path') or entry.get('work_path'))
        if work_path is None or target_path is None:
            warnings.append(f'publication {rule_type} map entry {index} has no usable paths; entry skipped')
            continue
        result.append({'source': f'^{re.escape(work_path)}$', 'destination': target_path})
    return result


def _first_source(container: Mapping[str, Any], label: str, warnings: list[str]) -> dict[str, Any]:
    sources = _optional_list(container.get('sources'))
    if not sources:
        raise ManifestEnvironmentError(f'{label} has no sources')
    if len(sources) > 1:
        warnings.append(f'{label} has multiple sources; the first source was used for config generation')
    return dict(_mapping(sources[0], f'{label}.sources[0]'))


def _publication_rule_set_name(group: Mapping[str, Any], category: str, index: int) -> str:
    rules = _optional_mapping(group.get('rules'))
    if rules is not None:
        value = rules.get('set')
        if isinstance(value, str) and value:
            return value
    return _string_or(group.get('name'), f'{category}_{index}')


def _normalized_run_cwd(value: object, warnings: list[str]) -> str:
    cwd = _string_or(value, '.')
    normalized = cwd.replace('\\', '/')
    if _is_absolute_path(normalized):
        if normalized.rstrip('/').endswith('/work') or normalized.rstrip('/').endswith(':'):
            return '.'
        warnings.append(f'absolute run.cwd from manifest was replaced with "." in run.toml: {cwd}')
        return '.'
    return normalized or '.'


def _relative_path(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return value.replace('\\', '/').lstrip('/')


def _unique_name(name: str, used: set[str]) -> str:
    candidate = name
    suffix = 2
    while candidate in used:
        candidate = f'{name}_{suffix}'
        suffix += 1
    return candidate


def _required_mapping(data: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = data.get(key)
    if not isinstance(value, Mapping):
        raise ManifestEnvironmentError(f'manifest {key} block is required')
    return value


def _optional_mapping(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ManifestEnvironmentError(f'{label} must be an object')
    return value


def _optional_list(value: object) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _string_or(value: object, default: str) -> str:
    return value if isinstance(value, str) and value else default


def _is_absolute_path(value: str) -> bool:
    return value.startswith('/') or (len(value) >= 3 and value[1] == ':' and value[2] == '/')
