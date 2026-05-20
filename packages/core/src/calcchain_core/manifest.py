from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from calcchain_core.artifacts import artifact_ref, published_source
from calcchain_core.models import ArtifactRef, JobStatus, Manifest, TargetRef


class ManifestWriter:
    @staticmethod
    def create_after_build(job, build_result, snapshots) -> Manifest:
        job_data = _job_dict(job, JobStatus.BUILT.value)
        data: dict[str, Any] = {
            'schema_version': '1.0',
            'job': job_data,
            'build': _build_dict(job, build_result),
        }
        rules = _rules_ref(job, build_result)
        if rules is not None:
            data['rules'] = rules.to_dict()
        snapshot_refs = _snapshot_refs(snapshots)
        if snapshot_refs:
            data['snapshots'] = snapshot_refs
        return Manifest.from_dict(data)

    @staticmethod
    def create_after_run(job, build_result, run_result, file_groups, snapshots) -> Manifest:
        status = _value(run_result, 'status')
        status_value = status.value if hasattr(status, 'value') else str(status)
        data = ManifestWriter.create_after_build(job, build_result, snapshots).to_dict()
        data['job']['status'] = status_value
        data['run'] = _run_dict(job, run_result, file_groups)
        return Manifest.from_dict(data)

    @staticmethod
    def create_after_publish(existing_manifest, publish_result) -> Manifest:
        data = existing_manifest.to_dict() if isinstance(existing_manifest, Manifest) else deepcopy(dict(existing_manifest))
        data.setdefault('schema_version', '1.0')
        data.setdefault('job', {})['status'] = JobStatus.PUBLISHED.value
        publication = _publication_dict(publish_result)
        if publication:
            data['publication'] = publication
        _append_published_log_sources(data, publish_result)
        return Manifest.from_dict(data)


def write_manifest(manifest: Manifest, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='\n') as file:
        json.dump(manifest.to_dict(), file, ensure_ascii=False, indent=2)
        file.write('\n')


def _job_dict(job, status: str) -> dict[str, Any]:
    source = _object_to_dict(job)
    result: dict[str, Any] = {}
    for key in ('id', 'created_at', 'job_dir', 'user', 'hostname'):
        value = source.get(key)
        if value is not None:
            result[key] = str(value)
    result['status'] = status
    return result


def _build_dict(job, build_result) -> dict[str, Any]:
    result: dict[str, Any] = {}
    lock = _artifact_from_candidate(_path_candidate(job, 'build_lock_path'))
    if lock is not None:
        result['lock'] = lock.to_dict()
    result['code'] = _file_set_dict(_value(build_result, 'code_set'))
    result['inputs'] = [_file_set_dict(item) for item in _value(build_result, 'input_sets') or []]
    frozen_inputs = _value(build_result, 'frozen_inputs')
    if frozen_inputs is not None:
        result['inputs'].append(_file_set_dict(frozen_inputs))
    return result


def _rules_ref(job, build_result) -> ArtifactRef | None:
    rules_artifact = _value(build_result, 'rules_artifact')
    if rules_artifact is None:
        return None
    path = _value(rules_artifact, 'path')
    if path is None:
        return None
    artifact_path = _resolve_job_path(job, path)
    if not artifact_path.is_file():
        return None
    return artifact_ref(artifact_path)


def _run_dict(job, run_result, file_groups) -> dict[str, Any]:
    env = dict(_value(run_result, 'env') or {})
    secret_names = list(_value(run_result, 'secret_names') or [])
    if secret_names:
        env['secrets'] = secret_names
    result: dict[str, Any] = {
        'command': list(_value(run_result, 'command') or []),
        'cwd': _value(run_result, 'cwd'),
        'timeout_seconds': _value(run_result, 'timeout_seconds'),
        'encoding': _value(run_result, 'encoding'),
        'env': env,
        'stdin': _stdin_dict(job, _value(run_result, 'stdin') or {}),
        'status': _status_value(_value(run_result, 'status')),
        'return_code': _value(run_result, 'return_code'),
        'file_groups': _file_groups_dict(file_groups),
        'started_at': _value(run_result, 'started_at'),
        'finished_at': _value(run_result, 'finished_at'),
    }
    stdout = _stream_log_dict(job, _value(run_result, 'stdout_log'))
    if stdout is not None:
        result['stdout'] = {'log': stdout.to_dict()}
    stderr = _stream_log_dict(job, _value(run_result, 'stderr_log'))
    if stderr is not None:
        result['stderr'] = {'log': stderr.to_dict()}
    return result


def _stdin_dict(job, stdin: dict[str, Any]) -> dict[str, Any]:
    result = dict(stdin)
    log = result.get('log')
    if isinstance(log, str):
        log_ref = _stream_log_dict(job, log)
        if log_ref is not None:
            result['log'] = log_ref.to_dict()
    return result


def _stream_log_dict(job, log_path: str | None) -> ArtifactRef | None:
    if log_path is None:
        return None
    path = _resolve_job_path(job, log_path)
    if not path.is_file():
        return None
    return artifact_ref(path)


def _file_groups_dict(file_groups) -> dict[str, list[str]]:
    if file_groups is None:
        return {'code': [], 'inputs': [], 'outputs': [], 'logs': [], 'temp': [], 'ignored': [], 'unknown': []}
    data = file_groups.to_dict() if hasattr(file_groups, 'to_dict') else _object_to_dict(file_groups)
    result = {
        'code': list(data.get('code') or []),
        'inputs': list(data.get('inputs') or []),
        'outputs': list(data.get('outputs') or []),
        'logs': list(data.get('logs') or []),
        'temp': list(data.get('temp') or []),
        'ignored': list(data.get('ignored') or []),
        'unknown': list(data.get('unknown') or []),
    }
    if 'deleted' in data:
        result['deleted'] = list(data.get('deleted') or [])
    return result


def _publication_dict(publish_result) -> dict[str, Any]:
    data = _object_to_dict(publish_result)
    result: dict[str, Any] = {}
    lock = _artifact_from_candidate(data.get('publish_lock_artifact') or data.get('lock') or data.get('lock_path'))
    if lock is not None:
        result['lock'] = lock.to_dict()
    if data.get('groups'):
        for group in data['groups']:
            group_data = _file_set_dict(group)
            category = _value(group, 'category')
            if category in {'outputs', 'logs', 'temp'}:
                result.setdefault(category, []).append(group_data)
    for key in ('outputs', 'logs', 'temp'):
        values = [_file_set_dict(item) for item in data.get(key) or []]
        if values:
            result.setdefault(key, []).extend(values)
    return result


def _append_published_log_sources(data: dict[str, Any], publish_result) -> None:
    target = _service_target(publish_result)
    if target is None:
        return
    run = data.get('run')
    if not isinstance(run, dict):
        return
    for container in (run.get('stdin'), run.get('stdout'), run.get('stderr')):
        if not isinstance(container, dict):
            continue
        log = container.get('log')
        if not isinstance(log, dict):
            continue
        sources = log.get('sources')
        if not isinstance(sources, list) or not sources:
            continue
        relative = _published_log_relative_path(sources[0])
        if relative is None:
            continue
        if target.path.replace('\\', '/').rstrip('/').endswith('/_calcchain') or target.path.replace('\\', '/') == '_calcchain':
            relative = relative.removeprefix('_calcchain/')
        source = published_source(target, relative).to_dict()
        if source not in sources:
            sources.append(source)


def _published_log_relative_path(source: Any) -> str | None:
    if not isinstance(source, dict):
        return None
    path = str(source.get('path') or '').replace('\\', '/')
    marker = '/.calcchain/logs/'
    if marker in path:
        return f'_calcchain/logs/{path.split(marker, maxsplit=1)[1]}'
    if path.startswith('.calcchain/logs/'):
        return f'_calcchain/logs/{path.removeprefix(".calcchain/logs/")}'
    return f'_calcchain/logs/{Path(path).name}' if path else None


def _snapshot_refs(snapshots) -> dict[str, Any]:
    result: dict[str, Any] = {}
    data = _object_to_dict(snapshots)
    for key, value in data.items():
        ref = _artifact_from_candidate(value)
        if ref is not None:
            result[str(key)] = ref.to_dict()
    return result


def _file_set_dict(file_set) -> dict[str, Any]:
    if hasattr(file_set, 'to_dict'):
        return file_set.to_dict()
    return deepcopy(dict(file_set))


def _artifact_from_candidate(candidate) -> ArtifactRef | None:
    if candidate is None:
        return None
    if isinstance(candidate, ArtifactRef):
        return candidate
    if isinstance(candidate, dict) and 'sha256' in candidate and 'sources' in candidate:
        return ArtifactRef.from_dict(candidate)
    path = Path(candidate)
    if not path.is_file():
        return None
    return artifact_ref(path)


def _service_target(publish_result) -> TargetRef | None:
    data = _object_to_dict(publish_result)
    target = data.get('service_target') or data.get('target')
    if target is None:
        return None
    if isinstance(target, TargetRef):
        return target
    return TargetRef.from_dict(target, resolved_revision=True)


def _path_candidate(job, key: str):
    data = _object_to_dict(job)
    if key in data:
        return data[key]
    layout = data.get('layout')
    if layout is not None and key == 'build_lock_path':
        build_dir = _value(layout, 'build_artifacts_dir')
        if build_dir is not None:
            return Path(build_dir) / 'build_lock.json'
    return None


def _resolve_job_path(job, path: str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    job_dir = _object_to_dict(job).get('job_dir')
    if job_dir is None and _object_to_dict(job).get('layout') is not None:
        job_dir = _value(_object_to_dict(job)['layout'], 'job_dir')
    return Path(job_dir) / candidate if job_dir is not None else candidate


def _status_value(status) -> str:
    return status.value if hasattr(status, 'value') else str(status)


def _object_to_dict(value) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, 'to_dict'):
        return value.to_dict()
    if hasattr(value, '__dict__'):
        return dict(value.__dict__)
    return {}


def _value(obj, name: str):
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)
